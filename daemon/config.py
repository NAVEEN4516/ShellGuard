"""
ShellGuard 12-Factor App Configuration Module
Implements Factor III (Store config in the environment) using Pydantic BaseSettings.
All configuration is strictly injected via environment variables with 'SHELLGUARD_' prefix.
"""

import os
from pathlib import Path
from typing import Literal, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ShellGuardSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SHELLGUARD_",
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server Network Binding
    host: str = Field(default="127.0.0.1", description="Localhost binding interface")
    port: int = Field(default=8080, description="Local HTTP daemon port")

    # Core Engine & Moss Settings
    moss_model_name: str = Field(default="moss-minilm", description="Local embedded Moss semantic model")
    decision_threshold: float = Field(default=0.70, description="Cosine similarity threshold for BLOCKED decision")
    warning_threshold: float = Field(default=0.40, description="Cosine similarity threshold for WARNING decision")

    # 12-Factor & Enterprise Safety Policies
    fail_policy: Literal["fail_open", "fail_closed"] = Field(
        default="fail_open",
        description="Interception behavior if daemon is offline: 'fail_open' for developer DX, 'fail_closed' for zero-trust security",
    )
    disable_auth: bool = Field(default=False, description="Bypass token authentication for local headless CI")

    # Security & Rate Limiting
    rate_limit_max: int = Field(default=300, description="Max requests per sliding window")
    rate_limit_window_seconds: int = Field(default=60, description="Sliding window duration in seconds")
    max_command_length: int = Field(default=4096, description="Maximum allowed command payload characters")

    # LiveKit Real-Time WebRTC Settings
    livekit_api_key: str = Field(default="devkey", description="LiveKit API key for room tokens")
    livekit_api_secret: str = Field(default="secret", description="LiveKit API secret for HS256 JWT signing")

    # Centralized Policy Distribution & Fleet Sync
    policy_sync_url: Optional[str] = Field(default=None, description="Central policy repo URL for signed delta updates")
    policy_signing_key: str = Field(default="shellguard-enterprise-shared-secret-key-2026", description="Shared secret key for policy signature verification")
    policy_sync_interval_seconds: int = Field(default=300, description="Background polling interval for delta updates in seconds")

    # Central Enterprise Telemetry & SIEM Forwarder
    siem_endpoint_url: Optional[str] = Field(default=None, description="Enterprise SIEM or OpenTelemetry collector URL")
    siem_api_key: Optional[str] = Field(default=None, description="SIEM authorization token or API key")
    siem_batch_size: int = Field(default=25, description="Audit events per batch")
    siem_flush_interval_seconds: float = Field(default=5.0, description="Flush interval in seconds for telemetry forwarder")

    # Tiered Indexing & LRU Memory Manager
    max_hot_chunks: int = Field(default=500, description="Maximum post-mortem chunks retained in Tier 1 hot RAM")
    max_rss_mb: int = Field(default=250, description="Maximum RSS memory ceiling in MB")

    # Data & Paths
    incidents_dir: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parent.parent / "data" / "incidents",
        description="Directory containing immutable source-of-truth incident post-mortems",
    )


# Singleton configuration instance
settings = ShellGuardSettings()
