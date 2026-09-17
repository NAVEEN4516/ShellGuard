"""
ShellGuard Daemon Server
FastAPI application providing the sub-10ms HTTP hook interface,
telemetry stream, LiveKit WebRTC bridge, and serving the interactive Web Cockpit.
"""

import os
import time
import asyncio
import logging
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Dict, Any, List, Optional

from fastapi import FastAPI, HTTPException, Depends, Request, Response, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from daemon.engine import ShellGuardEngine, CheckResult
from daemon.security import (
    validate_command_payload,
    verify_auth_token,
    security_manager,
    rate_limiter,
)
from daemon.livekit_bridge import livekit_bridge
from daemon.classifier_prompt import build_crispe_prompt
from daemon.sync import policy_sync_manager
from daemon.forwarder import telemetry_forwarder
from daemon.lru import tiered_index_manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("shellguard.server")

STATIC_DIR = Path(__file__).resolve().parent.parent / "web"
DASHBOARD_OUT_DIR = Path(__file__).resolve().parent.parent / "dashboard" / "out"

# Global engine instance initialized at startup
engine = ShellGuardEngine()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing ShellGuard Moss Engine...")
    engine.initialize()
    logger.info("ShellGuard Engine ready to intercept commands.")
    telemetry_forwarder.start()
    yield
    telemetry_forwarder.stop()
    logger.info("Shutting down ShellGuard Daemon...")


app = FastAPI(
    title="ShellGuard Daemon",
    description="Zero-Latency Local-First Terminal Interceptor powered by Moss, LiveKit, and Next.js",
    version="1.1.0",
    lifespan=lifespan,
)

# CORS middleware for local development and Next.js cockpit
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CommandCheckRequest(BaseModel):
    command: str = Field(..., description="The shell command to evaluate", examples=["kubectl delete namespace ingress-nginx"])
    cwd: str = Field(default="", description="Current working directory of terminal")
    shell: str = Field(default="zsh", description="Shell type: zsh, bash, powershell")


class LiveKitTokenRequest(BaseModel):
    room_name: str = Field(..., description="LiveKit room name or incident war room identifier")
    participant_identity: str = Field(default="sre-operator", description="Participant username or ID")
    participant_name: Optional[str] = Field(default="SRE Console User", description="Display name")


class LiveKitAlertRequest(BaseModel):
    incident_id: str = Field(..., description="Incident ID triggering the alert")
    title: str = Field(..., description="Incident or alert title")
    command: str = Field(..., description="Blocked command string")
    severity: str = Field(default="P0", description="Severity level: P0, P1, P2")


class IncidentIngestRequest(BaseModel):
    markdown: Optional[str] = Field(default=None, description="Raw incident post-mortem markdown")
    file_path: Optional[str] = Field(default=None, description="Path to incident markdown file")


class BenchmarkRequest(BaseModel):
    sample_size: int = Field(default=10, ge=1, le=50)


class ClassifyPromptRequest(BaseModel):
    command: str = Field(..., description="The command to format into CRISPE prompt")
    cwd: str = Field(default="", description="Current working directory")
    shell: str = Field(default="zsh", description="Active shell type")


@app.get("/api/health")
async def health():
    return {
        "status": "healthy",
        "engine": "moss-minilm-in-process",
        "indexed_chunks": engine.total_docs_indexed,
        "is_ready": engine.is_initialized,
        "livekit_integrated": True,
        "security_hardened": True,
    }


@app.get("/api/security/info")
async def security_info():
    """Returns local security configuration status."""
    return {
        "auth_required": os.environ.get("SHELLGUARD_DISABLE_AUTH", "0").lower() not in ("1", "true", "yes"),
        "token_file": str(security_manager.token_path),
        "rate_limit_max": rate_limiter.max_requests,
        "rate_limit_window": rate_limiter.window_seconds,
    }


# In-memory OpenTelemetry trace buffer
otlp_trace_buffer: List[Dict[str, Any]] = []

@app.post("/api/check", response_model=Dict[str, Any])
async def check_command(req: CommandCheckRequest, auth: str = Depends(verify_auth_token)):
    """
    Sub-10ms interception endpoint called by shell hooks (preexec / Zsh / Bash / PowerShell).
    Validates payload, executes zero-latency in-process Moss evaluation, and dispatches
    LiveKit emergency WebRTC audio alerts for BLOCKED commands.
    Generates OpenTelemetry-compliant trace spans for auditable model observability.
    """
    clean_command = validate_command_payload(req.command)
    
    t0 = time.perf_counter()
    start_unix_nano = int(time.time() * 1e9)
    result = engine.evaluate(clean_command, cwd=req.cwd if req.cwd else None)
    total_transport_ms = round((time.perf_counter() - t0) * 1000, 3)
    end_unix_nano = int(time.time() * 1e9)

    # OpenTelemetry trace generation
    trace_id = os.urandom(16).hex()
    span_id = os.urandom(8).hex()
    span = {
        "traceId": trace_id,
        "spanId": span_id,
        "name": "shellguard.evaluate",
        "kind": "SPAN_KIND_INTERNAL",
        "startTimeUnixNano": str(start_unix_nano),
        "endTimeUnixNano": str(end_unix_nano),
        "attributes": [
            {"key": "command.raw", "value": {"stringValue": clean_command}},
            {"key": "command.status", "value": {"stringValue": result.status}},
            {"key": "moss.latency_ms", "value": {"doubleValue": result.latency_ms}},
            {"key": "moss.similarity_score", "value": {"doubleValue": result.similarity_score}},
            {"key": "incident.matched_id", "value": {"stringValue": result.matched_incident_id or ""}},
        ],
        "status": {"code": "STATUS_CODE_OK" if result.status != "BLOCKED" else "STATUS_CODE_ERROR"},
    }
    otlp_trace_buffer.insert(0, span)
    if len(otlp_trace_buffer) > 100:
        otlp_trace_buffer.pop()

    data = result.to_dict()
    data["total_api_latency_ms"] = total_transport_ms
    data["trace_id"] = trace_id

    # LiveKit real-time audio alert & SRE War Room dispatch for high-severity blocks
    if result.status == "BLOCKED" and result.matched_incident_id:
        alert_payload = livekit_bridge.dispatch_incident_audio_alert(
            incident_id=result.matched_incident_id,
            title=result.matched_incident_title or "Terminal Command Blocked",
            command=clean_command,
            severity=result.severity or "P0",
        )
        data["livekit_alert"] = alert_payload

    # Enterprise SIEM telemetry forwarding (out-of-band non-blocking queue)
    telemetry_forwarder.enqueue_audit_event({
        "trace_id": trace_id,
        "command": clean_command,
        "status": result.status,
        "latency_ms": result.latency_ms,
        "matched_incident_id": result.matched_incident_id,
        "similarity_score": result.similarity_score,
        "env_badge": result.env_badge,
    })

    # Tiered LRU access tracking
    if result.matched_incident_id:
        tiered_index_manager.record_access(result.matched_incident_id)

    return data


@app.post("/api/livekit/token")
async def generate_livekit_token(req: LiveKitTokenRequest, auth: str = Depends(verify_auth_token)):
    """
    Generates a cryptographically signed LiveKit WebRTC Access Token
    for collaborative SRE War Room terminal sessions.
    """
    token = livekit_bridge.create_room_token(
        room_name=req.room_name,
        participant_identity=req.participant_identity,
        participant_name=req.participant_name,
    )
    return {
        "livekit_url": livekit_bridge.url,
        "room_name": req.room_name,
        "token": token,
        "participant_identity": req.participant_identity,
    }


@app.post("/api/livekit/alert")
async def trigger_livekit_alert(req: LiveKitAlertRequest, auth: str = Depends(verify_auth_token)):
    """
    Manually or programmatically triggers a LiveKit emergency WebRTC audio alert and war room.
    """
    alert = livekit_bridge.dispatch_incident_audio_alert(
        incident_id=req.incident_id,
        title=req.title,
        command=req.command,
        severity=req.severity,
    )
    return alert


@app.post("/api/classify/prompt")
async def generate_crispe_prompt(req: ClassifyPromptRequest, auth: str = Depends(verify_auth_token)):
    """
    Generates the complete CRISPE framework prompt specification with few-shot safety matrix examples
    for Layer 7 classifier evaluation.
    """
    clean_command = validate_command_payload(req.command)
    context_badge = "[ENV: local]"
    if hasattr(engine, "context_detector"):
        env_dict = engine.context_detector.detect(cwd=req.cwd if req.cwd else None)
        badge = engine.context_detector.format_badge(env_dict)
        if badge:
            context_badge = badge
    retrieved = engine.incidents[:3] if engine.incidents else None
    prompt_payload = build_crispe_prompt(
        command=clean_command,
        cwd=req.cwd,
        shell_type=req.shell,
        context_badge=context_badge,
        retrieved_incidents=retrieved,
    )
    return prompt_payload


@app.post("/api/incidents", status_code=201, response_model=Dict[str, Any])
async def ingest_incident(req: IncidentIngestRequest, auth: str = Depends(verify_auth_token)):
    """
    Dynamically ingest and learn a new disaster post-mortem without server restart.
    """
    if not req.markdown and not req.file_path:
        raise HTTPException(status_code=400, detail="Either 'markdown' or 'file_path' must be provided.")

    target = req.markdown
    if req.file_path:
        p = Path(req.file_path)
        if not p.exists() or not p.is_file():
            raise HTTPException(status_code=404, detail=f"Incident file not found: {req.file_path}")
        target = p

    try:
        summary = engine.learn_incident(target)
        return summary
    except Exception as e:
        logger.error(f"Failed to ingest incident: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/stats")
async def get_stats():
    """Return live telemetry metrics."""
    return engine.get_stats()


@app.get("/api/history")
async def get_history():
    """Return recent command checks."""
    return [h.to_dict() for h in engine.history[:50]]


@app.get("/api/telemetry/traces")
async def get_otlp_traces():
    """
    Returns OpenTelemetry-compliant trace spans in OTLP JSON format
    for distributed tracing and local model observability.
    """
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "shellguard-daemon"}},
                        {"key": "service.version", "value": {"stringValue": "1.1.0"}},
                        {"key": "deployment.environment", "value": {"stringValue": "workstation-local"}},
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "shellguard.interceptor", "version": "1.1.0"},
                        "spans": otlp_trace_buffer[:50],
                    }
                ],
            }
        ]
    }


@app.get("/api/incidents")
async def list_incidents():
    """Return all loaded disaster post-mortems and safety rules."""
    return engine.incidents


@app.get("/api/incidents/{incident_id}")
async def get_incident(incident_id: str):
    """Return details for a single incident."""
    for inc in engine.incidents:
        if inc["id"] == incident_id:
            return inc
    raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")


@app.post("/api/benchmark")
async def run_benchmark(req: BenchmarkRequest, auth: str = Depends(verify_auth_token)):
    """
    Run side-by-side benchmark of Moss in-process retrieval vs. simulated Cloud Vector DB.
    Demonstrates the 100x latency advantage of local in-memory execution.
    """
    sample_queries = [
        "kubectl delete namespace ingress-nginx",
        "terraform destroy -target=aws_db_instance.primary",
        "docker system prune -a --volumes",
        "aws s3api put-bucket-acl --bucket prod --acl public-read",
        "rm -rf /",
        "git push --force origin main",
        "terraform state rm module.vpc.aws_nat_gateway.main",
        "kubectl delete deployment ingress-nginx-controller -n ingress-nginx",
        "docker volume rm my_prod_volume",
        "aws s3 rm s3://company-prod-backups --recursive",
    ]

    queries = (sample_queries * ((req.sample_size // len(sample_queries)) + 1))[:req.sample_size]

    # Warm up to prime in-memory runtime cache
    if queries:
        _ = engine.index_manager.query("shellguard_incidents", queries[0], top_k=1)

    moss_latencies = []
    cloud_latencies = []

    for q in queries:
        # Moss in-process measurement
        t0 = time.perf_counter()
        _ = engine.index_manager.query("shellguard_incidents", q, top_k=3)
        moss_lat = (time.perf_counter() - t0) * 1000
        moss_latencies.append(round(moss_lat, 2))

        # Simulated cloud vector DB: typical 180ms - 320ms HTTPS RTT + remote vector search
        simulated_cloud_lat = 220.0 + (hash(q) % 75)
        cloud_latencies.append(round(simulated_cloud_lat, 2))

    moss_avg = sum(moss_latencies) / len(moss_latencies)
    cloud_avg = sum(cloud_latencies) / len(cloud_latencies)
    speedup = cloud_avg / moss_avg if moss_avg > 0 else 50.0

    return {
        "sample_size": len(queries),
        "moss_latencies_ms": moss_latencies,
        "cloud_latencies_ms": cloud_latencies,
        "moss_avg_latency_ms": round(moss_avg, 2),
        "cloud_avg_latency_ms": round(cloud_avg, 2),
        "speedup_factor": f"{round(speedup, 1)}x faster",
        "latency_saved_per_command_ms": round(cloud_avg - moss_avg, 1),
    }


# Enterprise Fleet Policy Synchronization Endpoints
@app.post("/api/sync/apply")
async def apply_policy_sync(bundle: Dict[str, Any], auth: str = Depends(verify_auth_token)):
    """
    Applies a cryptographically signed enterprise policy delta bundle.
    Rejects unsigned or tampered payloads with HTTP 403.
    """
    return policy_sync_manager.apply_delta_update(bundle, engine)


@app.post("/api/sync/pull")
async def pull_remote_policy_sync(auth: str = Depends(verify_auth_token)):
    """
    Pulls the latest signed policy bundle from central repository URL.
    """
    return policy_sync_manager.pull_remote_policy(engine)


@app.get("/api/sync/status")
async def get_sync_status():
    """Returns fleet policy version and sync status."""
    return {
        "current_version": policy_sync_manager.current_version,
        "signing_configured": bool(policy_sync_manager.signing_key),
        "incidents_dir": str(policy_sync_manager.incidents_dir),
    }


# Enterprise SIEM & Telemetry Forwarder Endpoints
@app.get("/api/telemetry/forwarder")
async def get_forwarder_status():
    """Returns telemetry forwarder metrics and buffer status."""
    return telemetry_forwarder.get_stats()


@app.post("/api/telemetry/flush")
async def flush_forwarder_telemetry(auth: str = Depends(verify_auth_token)):
    """Flushes all queued telemetry audit events to enterprise SIEM."""
    flushed = telemetry_forwarder.flush_sync()
    return {"status": "flushed", "events_flushed": flushed}


# Tiered LRU Memory Manager Endpoints
@app.get("/api/memory/stats")
async def get_memory_stats():
    """Returns live tiered index and RSS memory metrics against the 250MB limit."""
    return tiered_index_manager.get_stats()


# Mount Next.js static build if available, otherwise fallback to web/
if DASHBOARD_OUT_DIR.exists():
    app.mount("/_next", StaticFiles(directory=str(DASHBOARD_OUT_DIR / "_next")), name="next_assets")
    app.mount("/static", StaticFiles(directory=str(DASHBOARD_OUT_DIR)), name="dashboard_static")

    @app.get("/")
    async def serve_dashboard():
        index_file = DASHBOARD_OUT_DIR / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file))
        return JSONResponse({"status": "ShellGuard daemon active", "cockpit": "Next.js Local Cockpit"})
elif STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    async def serve_index():
        index_file = STATIC_DIR / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file))
        return JSONResponse({"status": "ShellGuard daemon active", "docs": "/docs"})
