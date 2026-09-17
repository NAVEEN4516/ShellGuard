"""
ShellGuard CRISPE Safety Decision Classifier Prompt Specification
Implements formal CRISPE framework prompt engineering with few-shot safety matrix examples
for Layer 7 command classification, blast radius assessment, and safe alternative synthesis.
"""

import json
from typing import Dict, Any, List, Optional


# Formal CRISPE Framework Architecture:
# C - Capacity and Role
# R - Request / Task
# I - Insight & Context
# S - Specifics & Constraints
# P - Personality & Tone
# E - Experiment & Few-Shot Demonstrations

CRISPE_SYSTEM_ROLE = """You are ShellGuard Sentinel, a Principal Site Reliability Engineer and Zero-Trust Terminal Safety Arbiter.
Your sole mission is to prevent catastrophic infrastructure outages, data loss, and security breaches in command-line environments by evaluating developer terminal commands before execution."""

CRISPE_INSTRUCTION_TEMPLATE = """Evaluate the candidate command below against the active infrastructure context and retrieved historical disaster post-mortems.

[CRISPE SPECIFICATION]
- CAPACITY & ROLE: Principal SRE & Terminal Safety Arbiter.
- REQUEST: Classify the command as PASSED, WARNING, or BLOCKED. If WARNING or BLOCKED, determine the severity (P0, P1, P2), quantify the blast radius, match the historical incident ID, and synthesize a single, drop-in safe executable alternative command.
- INSIGHT & CONTEXT:
  * Operating System: {os_type}
  * Shell: {shell_type}
  * Working Directory: {cwd}
  * Active Multi-Cloud Context: {context_badge}
  * Moss Retrieved Disaster Post-Mortems:
{retrieved_incidents}
- SPECIFICS & CONSTRAINTS:
  * You must return ONLY valid, parseable JSON matching the schema below.
  * No conversational filler, no markdown code fence ticks outside JSON, no preamble.
  * If the command is read-only (e.g. get, describe, list, status, log, plan), classify as PASSED.
  * If the command contains non-destructive simulation flags (e.g. --dry-run=client, --dry-run=server, -detailed-exitcode), classify as PASSED.
  * If destructive actions (delete, destroy, rm -rf, prune, flushall, drop) target production or unconstrained scopes, classify as BLOCKED.
- PERSONALITY: Strictly conservative, zero-hallucination, fail-safe. If uncertain between WARNING and BLOCKED in production, choose BLOCKED.

Output Schema:
{{
  "status": "PASSED" | "WARNING" | "BLOCKED",
  "severity": "P0" | "P1" | "P2" | "NONE",
  "matched_incident_id": "INC-XXX" | null,
  "rationale": "<concise explanation in 1 sentence>",
  "blast_radius": "<impacted systems, nodes, or data>",
  "safe_alternative_cmd": "<exact copy-pasteable safe command>" | null,
  "safe_alternative_notes": "<operational guidance for safe execution>" | null
}}
"""

CRISPE_FEW_SHOT_EXAMPLES: List[Dict[str, Any]] = [
    {
        "input": {
            "command": "kubectl delete namespace ingress-nginx",
            "context": "[ENV: prod-us-east-1 (k8s: production-cluster)]",
        },
        "output": {
            "status": "BLOCKED",
            "severity": "P0",
            "matched_incident_id": "INC-042",
            "rationale": "Direct namespace deletion destroys all ingress routing, SSL certificates, and public web endpoints.",
            "blast_radius": "All inbound HTTP/HTTPS traffic to production ingress controllers across 3 availability zones.",
            "safe_alternative_cmd": "kubectl get namespace ingress-nginx && kubectl get pods -n ingress-nginx",
            "safe_alternative_notes": "Inspect ingress status and drain specific workloads rather than deleting the entire ingress infrastructure namespace.",
        },
    },
    {
        "input": {
            "command": "aws s3 rm s3://company-prod-backups --recursive",
            "context": "[ENV: prod-account (aws: 8492041920)]",
        },
        "output": {
            "status": "BLOCKED",
            "severity": "P0",
            "matched_incident_id": "INC-109",
            "rationale": "Recursive bucket deletion irreversibly wipes production disaster recovery snapshots and backups.",
            "blast_radius": "Complete destruction of database cold storage and historical backup volumes.",
            "safe_alternative_cmd": "aws s3 ls s3://company-prod-backups/",
            "safe_alternative_notes": "List bucket contents first and review lifecycle retention policies instead of recursive deletion.",
        },
    },
    {
        "input": {
            "command": "git push origin main --force",
            "context": "[ENV: main (git: origin/main)]",
        },
        "output": {
            "status": "BLOCKED",
            "severity": "P0",
            "matched_incident_id": "INC-381",
            "rationale": "Force-pushing to the main protected branch rewrites shared commit history and destroys unmerged release tags.",
            "blast_radius": "Source code repository integrity, CI/CD automated deployments, and peer developer branches.",
            "safe_alternative_cmd": "git push origin HEAD --force-with-lease",
            "safe_alternative_notes": "Use --force-with-lease to verify your local ref matches remote before updating, or merge via pull request.",
        },
    },
    {
        "input": {
            "command": "terraform destroy -auto-approve",
            "context": "[ENV: prod-infrastructure (aws: primary)]",
        },
        "output": {
            "status": "BLOCKED",
            "severity": "P0",
            "matched_incident_id": "INC-883",
            "rationale": "Unattended terraform destroy wipes entire cloud topologies without manual confirmation prompts.",
            "blast_radius": "All managed VPCs, RDS clusters, Kubernetes node pools, and DNS records in current statefile.",
            "safe_alternative_cmd": "terraform plan -destroy",
            "safe_alternative_notes": "Run a speculative destroy plan first to review the full resource dependency graph before teardown.",
        },
    },
    {
        "input": {
            "command": "kubectl get pods -n kube-system",
            "context": "[ENV: prod-us-east-1 (k8s: production-cluster)]",
        },
        "output": {
            "status": "PASSED",
            "severity": "NONE",
            "matched_incident_id": None,
            "rationale": "Read-only inspection command with zero state mutation.",
            "blast_radius": "None",
            "safe_alternative_cmd": None,
            "safe_alternative_notes": None,
        },
    },
    {
        "input": {
            "command": "kubectl delete deployment payment-service -n staging --dry-run=client",
            "context": "[ENV: staging (k8s: staging-cluster)]",
        },
        "output": {
            "status": "PASSED",
            "severity": "NONE",
            "matched_incident_id": None,
            "rationale": "Execution includes safe simulation flag --dry-run=client preventing actual cluster changes.",
            "blast_radius": "None (client-side dry run only)",
            "safe_alternative_cmd": None,
            "safe_alternative_notes": None,
        },
    },
    {
        "input": {
            "command": "docker run -d -p 8080:80 nginx:alpine",
            "context": "[ENV: local-dev (git: feature/auth)]",
        },
        "output": {
            "status": "PASSED",
            "severity": "NONE",
            "matched_incident_id": None,
            "rationale": "Standard container execution on local developer daemon.",
            "blast_radius": "Local port 8080 binding only.",
            "safe_alternative_cmd": None,
            "safe_alternative_notes": None,
        },
    },
]


def build_crispe_prompt(
    command: str,
    cwd: str = "",
    shell_type: str = "zsh",
    os_type: str = "linux/darwin/windows",
    context_badge: str = "[ENV: local]",
    retrieved_incidents: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Constructs a complete, production-grade CRISPE prompt payload including
    system role, instruction template, context grounding, and few-shot examples.
    """
    incidents_text = ""
    if retrieved_incidents:
        for idx, inc in enumerate(retrieved_incidents[:3], 1):
            incidents_text += (
                f"  [{idx}] ID: {inc.get('id', 'N/A')} | Title: {inc.get('title', 'N/A')}\n"
                f"      Trigger: {inc.get('trigger_command', 'N/A')}\n"
                f"      Severity: {inc.get('severity', 'P0')} | Blast Radius: {inc.get('blast_radius', 'N/A')}\n"
                f"      Safe Alternative: {inc.get('safe_alternative_cmd', 'N/A')}\n"
            )
    else:
        incidents_text = "  (No direct incident match retrieved; use general SRE zero-trust principles)\n"

    instructions = CRISPE_INSTRUCTION_TEMPLATE.format(
        os_type=os_type,
        shell_type=shell_type,
        cwd=cwd or "/",
        context_badge=context_badge,
        retrieved_incidents=incidents_text,
    )

    return {
        "framework": "CRISPE",
        "system_role": CRISPE_SYSTEM_ROLE,
        "instructions": instructions,
        "few_shot_examples": CRISPE_FEW_SHOT_EXAMPLES,
        "candidate_command": command,
        "formatted_prompt": (
            f"{CRISPE_SYSTEM_ROLE}\n\n"
            f"{instructions}\n\n"
            f"[FEW-SHOT EXAMPLES]\n"
            f"{json.dumps(CRISPE_FEW_SHOT_EXAMPLES, indent=2)}\n\n"
            f"[CANDIDATE COMMAND TO EVALUATE]\n"
            f"Command: {command}\n"
            f"Active Context: {context_badge}\n"
            f"Response JSON:\n"
        ),
    }
