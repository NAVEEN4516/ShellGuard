"""
ShellGuard Centralized Policy Distribution & Delta Sync Module
Enables automated, cryptographically signed fleet updates of disaster post-mortems
across workstation endpoints over HTTPS with zero daemon downtime.
"""

import os
import json
import time
import hmac
import hashlib
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from fastapi import HTTPException, status

from daemon.config import settings

logger = logging.getLogger("shellguard.sync")


class PolicySyncManager:
    """
    Manages cryptographic verification and live ingestion of enterprise policy bundles.
    Guarantees that unauthorized or tampered post-mortem deltas are rejected prior to execution.
    """

    def __init__(self, signing_key: Optional[str] = None, incidents_dir: Optional[Path] = None):
        self.signing_key = signing_key or settings.policy_signing_key
        self.incidents_dir = incidents_dir or settings.incidents_dir
        self.version_file = Path.home() / ".shellguard" / "policy_version.json"
        self._current_version = self._load_version()

    def _load_version(self) -> str:
        if self.version_file.exists():
            try:
                data = json.loads(self.version_file.read_text(encoding="utf-8"))
                return data.get("version", "2026.09.0-initial")
            except Exception:
                pass
        return "2026.09.0-initial"

    def _save_version(self, version: str, count: int):
        try:
            self.version_file.parent.mkdir(parents=True, exist_ok=True)
            self.version_file.write_text(
                json.dumps({"version": version, "updated_at": time.time(), "total_incidents": count}, indent=2),
                encoding="utf-8",
            )
            self._current_version = version
        except Exception as e:
            logger.warning(f"Could not persist policy version: {e}")

    @property
    def current_version(self) -> str:
        return self._current_version

    @staticmethod
    def compute_signature(payload_dict: Dict[str, Any], secret_key: str) -> str:
        """
        Computes deterministic HMAC-SHA256 over normalized JSON payload (excluding 'signature').
        """
        data_to_sign = {k: v for k, v in payload_dict.items() if k != "signature"}
        serialized = json.dumps(data_to_sign, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hmac.new(secret_key.encode("utf-8"), serialized, hashlib.sha256).hexdigest()

    def verify_signature(self, bundle: Dict[str, Any], secret_key: Optional[str] = None) -> bool:
        """
        Constant-time cryptographic verification of bundle signature.
        """
        candidate_sig = bundle.get("signature")
        if not candidate_sig or not isinstance(candidate_sig, str):
            return False
        key = secret_key or self.signing_key
        expected_sig = self.compute_signature(bundle, key)
        return hmac.compare_digest(candidate_sig.strip(), expected_sig)

    def create_signed_bundle(self, version: str, incidents: List[Dict[str, Any]], secret_key: Optional[str] = None) -> Dict[str, Any]:
        """
        Utility for generating verified enterprise policy bundles.
        """
        bundle = {
            "version": version,
            "timestamp": time.time(),
            "incidents": incidents,
        }
        key = secret_key or self.signing_key
        bundle["signature"] = self.compute_signature(bundle, key)
        return bundle

    def apply_delta_update(
        self,
        bundle: Dict[str, Any],
        engine,
        secret_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Verifies and hot-indexes an incoming signed incident delta bundle with zero daemon restarts.
        """
        start_time = time.perf_counter()

        # 1. Cryptographic Signature Verification
        if not self.verify_signature(bundle, secret_key):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cryptographic verification failed: tampered or unauthorized policy delta payload.",
            )

        incidents = bundle.get("incidents", [])
        if not isinstance(incidents, list):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Bundle 'incidents' field must be a list.",
            )

        version = bundle.get("version", f"delta-{int(time.time())}")
        applied_ids = []
        self.incidents_dir.mkdir(parents=True, exist_ok=True)

        # 2. Extract and persist markdown post-mortems
        for inc in incidents:
            inc_id = inc.get("id") or f"INC-{int(time.time()*1000)%100000}"
            md_content = inc.get("content_markdown")
            if not md_content:
                # Generate clean post-mortem markdown from structured fields
                title = inc.get("title", f"Incident {inc_id}")
                blast = inc.get("blast_radius", "High risk production disruption")
                safe_alt = inc.get("safe_alternative", "kubectl get pods")
                patterns = inc.get("trigger_patterns", [])
                patterns_str = "\n".join([f"- `{p}`" for p in patterns])
                md_content = f"""# {inc_id}: {title}

## Trigger Patterns
{patterns_str}

## Blast Radius
{blast}

## Mandatory Safe Alternative
```bash
{safe_alt}
```
"""
            # Write to disk
            file_path = self.incidents_dir / f"{inc_id}.md"
            file_path.write_text(md_content, encoding="utf-8")

            # 3. Hot-index into active in-memory Moss runtime
            if hasattr(engine, "add_incident_markdown"):
                engine.add_incident_markdown(md_content, source_file=str(file_path))
            elif hasattr(engine, "indexer") and hasattr(engine.indexer, "add_incident"):
                from daemon.indexer import IncidentPostMortem
                ipm = IncidentPostMortem(
                    incident_id=inc_id,
                    title=inc.get("title", f"Incident {inc_id}"),
                    raw_markdown=md_content,
                    safe_alternative_cmd=inc.get("safe_alternative"),
                    safe_alternative_notes=inc.get("blast_radius"),
                    blast_radius=inc.get("blast_radius"),
                )
                engine.indexer.add_incident(ipm)

            applied_ids.append(inc_id)

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        self._save_version(version, len(applied_ids))

        logger.info(f"Successfully applied policy delta {version}: {len(applied_ids)} incidents indexed in {elapsed_ms:.2f}ms")

        return {
            "status": "success",
            "version": version,
            "incidents_applied": applied_ids,
            "count": len(applied_ids),
            "latency_ms": round(elapsed_ms, 3),
        }

    def pull_remote_policy(self, engine, remote_url: Optional[str] = None, secret_key: Optional[str] = None) -> Dict[str, Any]:
        """
        Polls configured remote HTTPS repository for signed delta updates.
        """
        target_url = remote_url or settings.policy_sync_url
        if not target_url:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No remote policy sync URL configured (SHELLGUARD_POLICY_SYNC_URL).",
            )

        import urllib.request
        req = urllib.request.Request(
            target_url,
            headers={"User-Agent": "ShellGuard-Daemon/2.0", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to fetch remote policy bundle from {target_url}: {e}",
            )

        return self.apply_delta_update(data, engine, secret_key=secret_key)


# Global singleton
policy_sync_manager = PolicySyncManager()
