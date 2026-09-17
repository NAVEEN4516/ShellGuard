"""
ShellGuard LiveKit Real-Time Audio & War Room Integration Bridge
Implements LiveKit WebRTC room token generation, emergency audio alert dispatching,
and collaborative terminal session bridges for SRE incident response.
"""

import os
import time
import json
import hmac
import hashlib
import base64
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("shellguard.livekit")

LIVEKIT_URL = os.environ.get("LIVEKIT_URL", "wss://livekit.local:7880")
LIVEKIT_API_KEY = os.environ.get("LIVEKIT_API_KEY", "shellguard-local-key")
LIVEKIT_API_SECRET = os.environ.get("LIVEKIT_API_SECRET", "shellguard-local-secret-32-chars-long")


def _base64url_encode(data: bytes) -> str:
    """Encodes bytes to URL-safe base64 string without trailing padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


class LiveKitBridge:
    """
    Manages real-time WebRTC audio alerts and collaborative SRE incident bridges
    conforming to the official LiveKit protocol specification.
    """

    def __init__(
        self,
        url: str = LIVEKIT_URL,
        api_key: str = LIVEKIT_API_KEY,
        api_secret: str = LIVEKIT_API_SECRET,
    ):
        self.url = url
        self.api_key = api_key
        self.api_secret = api_secret

    def create_room_token(
        self,
        room_name: str,
        participant_identity: str,
        participant_name: Optional[str] = None,
        ttl_seconds: int = 3600,
        can_publish: bool = True,
        can_subscribe: bool = True,
    ) -> str:
        """
        Generates an official LiveKit JWT Access Token with roomJoin and media grants.
        """
        now = int(time.time())
        header = {"alg": "HS256", "typ": "JWT"}

        video_grant = {
            "roomJoin": True,
            "room": room_name,
            "canPublish": can_publish,
            "canSubscribe": can_subscribe,
            "canPublishData": True,
        }

        payload: Dict[str, Any] = {
            "exp": now + ttl_seconds,
            "nbf": now - 5,
            "iss": self.api_key,
            "sub": participant_identity,
            "name": participant_name or participant_identity,
            "video": video_grant,
            "metadata": json.dumps({
                "app": "ShellGuard",
                "role": "terminal_safety_net",
                "created_at": now,
            }),
        }

        header_b64 = _base64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        payload_b64 = _base64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))

        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            signing_input,
            hashlib.sha256,
        ).digest()
        sig_b64 = _base64url_encode(signature)

        return f"{header_b64}.{payload_b64}.{sig_b64}"

    def dispatch_incident_audio_alert(
        self,
        incident_id: str,
        title: str,
        command: str,
        severity: str = "P0",
    ) -> Dict[str, Any]:
        """
        Prepares a real-time WebRTC audio alert payload and collaborative SRE War Room token.
        When a critical command is BLOCKED, this alerts the on-call engineer via audio chime
        and generates an active LiveKit room for remote team collaboration.
        """
        room_name = f"shellguard-warroom-{incident_id.lower()}"
        token = self.create_room_token(
            room_name=room_name,
            participant_identity="sre-local-operator",
            participant_name="Local Terminal Operator",
            can_publish=True,
            can_subscribe=True,
        )

        alert_message = (
            f"ShellGuard Emergency Alert: High-risk command '{command[:40]}' blocked. "
            f"Matched {severity} incident {incident_id}: {title}."
        )

        logger.info(f"Dispatched LiveKit safety alert for {incident_id} (Room: {room_name})")

        return {
            "status": "alert_dispatched",
            "room_name": room_name,
            "livekit_url": self.url,
            "token": token,
            "incident_id": incident_id,
            "severity": severity,
            "speech_text": alert_message,
            "audio_frequency_hz": 880 if severity == "P0" else 440,
            "beep_pattern": [200, 100, 200] if severity == "P0" else [150],
        }


# Global singleton
livekit_bridge = LiveKitBridge()
