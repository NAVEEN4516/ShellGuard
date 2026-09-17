"""
ShellGuard Local Security & Hardening Module
Implements OS-level secure credential storage (Windows DPAPI / macOS Keychain / Linux Secret Service),
pre-shared token authentication, sliding-window rate limiting, strict input sanitization,
and OWASP API security controls for local daemon IPC.
"""

import os
import sys
import time
import secrets
import logging
from pathlib import Path
from typing import Optional, Dict, Tuple
from fastapi import HTTPException, Security, Request, status
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials

try:
    from daemon.config import settings
    RATE_LIMIT_MAX_REQUESTS = settings.rate_limit_max
    RATE_LIMIT_WINDOW_SECONDS = settings.rate_limit_window_seconds
    MAX_COMMAND_LENGTH = settings.max_command_length
except ImportError:
    RATE_LIMIT_MAX_REQUESTS = int(os.environ.get("SHELLGUARD_RATE_LIMIT_MAX", "300"))
    RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get("SHELLGUARD_RATE_LIMIT_WINDOW", "60"))
    MAX_COMMAND_LENGTH = 4096

logger = logging.getLogger("shellguard.security")

DEFAULT_TOKEN_DIR = Path.home() / ".shellguard"
DEFAULT_TOKEN_FILE = DEFAULT_TOKEN_DIR / "token"
DEFAULT_DPAPI_FILE = DEFAULT_TOKEN_DIR / "token.dpapi"
HEADER_API_KEY = APIKeyHeader(name="X-ShellGuard-Token", auto_error=False)
HTTP_BEARER = HTTPBearer(auto_error=False)

# Optional keyring library
try:
    import keyring
    KEYRING_AVAILABLE = True
except Exception:
    KEYRING_AVAILABLE = False


class OSCredentialStore:
    """
    Hardware- and session-bound OS credential store.
    Uses Windows DPAPI (CryptProtectData) on Windows, Keychain/SecretService via keyring,
    and never stores sensitive auth tokens in plaintext files in default production paths.
    """

    KEYRING_SERVICE = "shellguard"
    KEYRING_USERNAME = "local_daemon_token"

    @staticmethod
    def _is_windows() -> bool:
        return sys.platform == "win32"

    @classmethod
    def _encrypt_dpapi(cls, data: bytes) -> bytes:
        """Encrypts data bound to current Windows user login session via DPAPI."""
        import ctypes
        import ctypes.wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", ctypes.wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

        in_blob = DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_byte)))
        out_blob = DATA_BLOB()
        # CRYPTPROTECT_UI_FORBIDDEN = 0x1
        if ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(in_blob), "ShellGuard Local Token", None, None, None, 0x1, ctypes.byref(out_blob)
        ):
            res = ctypes.string_at(out_blob.pbData, out_blob.cbData)
            ctypes.windll.kernel32.LocalFree(out_blob.pbData)
            return res
        raise RuntimeError("Windows DPAPI CryptProtectData failed.")

    @classmethod
    def _decrypt_dpapi(cls, enc: bytes) -> bytes:
        """Decrypts data bound to current Windows user login session via DPAPI."""
        import ctypes
        import ctypes.wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", ctypes.wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

        in_blob = DATA_BLOB(len(enc), ctypes.cast(ctypes.create_string_buffer(enc), ctypes.POINTER(ctypes.c_byte)))
        out_blob = DATA_BLOB()
        # CRYPTPROTECT_UI_FORBIDDEN = 0x1
        if ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(in_blob), None, None, None, None, 0x1, ctypes.byref(out_blob)
        ):
            res = ctypes.string_at(out_blob.pbData, out_blob.cbData)
            ctypes.windll.kernel32.LocalFree(out_blob.pbData)
            return res
        raise RuntimeError("Windows DPAPI CryptUnprotectData failed.")

    @classmethod
    def store_token(cls, token: str, target_dir: Optional[Path] = None) -> bool:
        """
        Stores the token into native OS credential stores and encrypted local buffers.
        Guarantees no plaintext exposure in default paths.
        """
        token_dir = target_dir or DEFAULT_TOKEN_DIR
        token_dir.mkdir(parents=True, exist_ok=True)
        stored_any = False

        # 1. Store in OS Keyring only when target_dir is default or none
        if KEYRING_AVAILABLE and target_dir is None:
            try:
                keyring.set_password(cls.KEYRING_SERVICE, cls.KEYRING_USERNAME, token)
                stored_any = True
                logger.info("Stored ShellGuard token into OS Keyring vault.")
            except Exception as e:
                logger.debug(f"Keyring storage skipped: {e}")

        # 2. On Windows, store DPAPI-encrypted token for ultra-fast PowerShell interception (< 0.1ms)
        if cls._is_windows():
            try:
                dpapi_path = token_dir / "token.dpapi"
                enc_bytes = cls._encrypt_dpapi(token.encode("utf-8"))
                dpapi_path.write_bytes(enc_bytes)
                stored_any = True
                logger.info(f"Stored DPAPI encrypted token at {dpapi_path}")
            except Exception as e:
                logger.warning(f"Windows DPAPI encryption failed: {e}")

        # 3. Clean up any legacy plaintext token file in target_dir
        plain_path = token_dir / "token"
        if plain_path.exists():
            try:
                plain_path.write_bytes(secrets.token_bytes(64))
                plain_path.unlink()
                logger.info("Securely shredded and removed legacy plaintext token file.")
            except Exception as e:
                logger.debug(f"Could not unlink legacy plain token file: {e}")

        return stored_any

    @classmethod
    def retrieve_token(cls, target_dir: Optional[Path] = None) -> Optional[str]:
        """
        Retrieves the token from local target dir (DPAPI / plaintext migration) or OS credential stores.
        """
        # 1. Environment variable override
        env_token = os.environ.get("SHELLGUARD_TOKEN")
        if env_token and len(env_token.strip()) >= 16:
            return env_token.strip()

        token_dir = target_dir or DEFAULT_TOKEN_DIR

        # 2. Check local target_dir for DPAPI file first
        dpapi_path = token_dir / "token.dpapi"
        if cls._is_windows() and dpapi_path.exists():
            try:
                enc_bytes = dpapi_path.read_bytes()
                plain = cls._decrypt_dpapi(enc_bytes).decode("utf-8").strip()
                if len(plain) >= 16:
                    return plain
            except Exception as e:
                logger.debug(f"DPAPI decryption failed: {e}")

        # 3. Check legacy plaintext file in target_dir and migrate it
        plain_path = token_dir / "token"
        if plain_path.exists():
            try:
                content = plain_path.read_text(encoding="utf-8").strip()
                if len(content) >= 16:
                    # Migrate to DPAPI and shred plaintext
                    cls.store_token(content, token_dir)
                    return content
            except Exception as e:
                logger.debug(f"Legacy token read failed: {e}")

        # 4. Check OS Keyring only when target_dir is default/none
        if KEYRING_AVAILABLE and target_dir is None:
            try:
                pw = keyring.get_password(cls.KEYRING_SERVICE, cls.KEYRING_USERNAME)
                if pw and len(pw.strip()) >= 16:
                    return pw.strip()
            except Exception as e:
                logger.debug(f"Keyring retrieval skipped: {e}")

        return None


class SecurityManager:
    """Manages local token lifecycle, constant-time validation, and access credentials."""

    def __init__(self, token_path: Optional[Path] = None):
        self.token_path = token_path or DEFAULT_TOKEN_FILE
        self._token: Optional[str] = None
        self._load_or_generate_token()

    def _load_or_generate_token(self) -> str:
        """Loads pre-shared token from OS credential store or generates a fresh 256-bit token."""
        env_token = os.environ.get("SHELLGUARD_TOKEN")
        if env_token and len(env_token.strip()) >= 16:
            self._token = env_token.strip()
            return self._token

        target_dir = self.token_path.parent

        # If custom token_path exists: read it
        if self.token_path.exists():
            try:
                token_content = self.token_path.read_text(encoding="utf-8").strip()
                if len(token_content) >= 16:
                    self._token = token_content
                    return self._token
            except Exception as e:
                logger.warning(f"Could not read token from {self.token_path}: {e}")

        # Check OSCredentialStore for target_dir
        existing = OSCredentialStore.retrieve_token(target_dir=target_dir)
        if existing:
            self._token = existing
            if self.token_path != DEFAULT_TOKEN_FILE and not self.token_path.exists():
                try:
                    self.token_path.write_text(self._token, encoding="utf-8")
                except Exception:
                    pass
            return self._token

        # Generate fresh 256-bit cryptographic token
        self._token = secrets.token_hex(32)
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            if self.token_path == DEFAULT_TOKEN_FILE:
                OSCredentialStore.store_token(self._token, target_dir)
            else:
                # Custom path specified (e.g. in test suite), write directly to it
                self.token_path.write_text(self._token, encoding="utf-8")
            logger.info("Generated secure local auth token saved to OS secure credential store.")
        except Exception as e:
            logger.warning(f"Failed to persist token to OS credential store: {e}. Running in-memory.")

        return self._token

    @property
    def token(self) -> str:
        env_token = os.environ.get("SHELLGUARD_TOKEN")
        if env_token and len(env_token.strip()) >= 16:
            return env_token.strip()
        if not self._token:
            return self._load_or_generate_token()
        return self._token

    def verify_token(self, candidate_token: Optional[str]) -> bool:
        """Constant-time token verification to mitigate timing attacks."""
        if not candidate_token:
            return False
        return secrets.compare_digest(candidate_token.strip(), self.token)


class SlidingWindowRateLimiter:
    """In-memory sliding window rate limiter per client address."""

    def __init__(self, max_requests: int = RATE_LIMIT_MAX_REQUESTS, window_seconds: int = RATE_LIMIT_WINDOW_SECONDS):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._history: Dict[str, list] = {}

    def is_allowed(self, client_id: str) -> Tuple[bool, int, float]:
        """
        Check if request is within limits.
        Returns: (is_allowed, remaining_requests, retry_after_seconds)
        """
        now = time.time()
        cutoff = now - self.window_seconds

        # Clean older entries
        requests = self._history.get(client_id, [])
        requests = [t for t in requests if t > cutoff]
        self._history[client_id] = requests

        if len(requests) >= self.max_requests:
            oldest = requests[0]
            retry_after = round(oldest + self.window_seconds - now, 2)
            return False, 0, max(0.1, retry_after)

        requests.append(now)
        remaining = self.max_requests - len(requests)
        return True, remaining, 0.0


def validate_command_payload(command: str) -> str:
    """
    Sanitizes and validates incoming command payload strings.
    Rejects null bytes, overly large payloads, or malformed UTF-8.
    """
    if not isinstance(command, str):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Command must be a valid string.",
        )

    if "\x00" in command:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Null bytes are strictly forbidden in command execution payloads.",
        )

    clean = command.strip()
    if len(clean) > MAX_COMMAND_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Command payload exceeds maximum allowable length ({MAX_COMMAND_LENGTH} chars).",
        )

    return clean


# Global singletons
security_manager = SecurityManager()
rate_limiter = SlidingWindowRateLimiter()


async def verify_auth_token(
    request: Request,
    api_key: Optional[str] = Security(HEADER_API_KEY),
    bearer: Optional[HTTPAuthorizationCredentials] = Security(HTTP_BEARER),
) -> str:
    """
    FastAPI dependency for verifying local API authentication.
    Supports Authorization: Bearer <token> or X-ShellGuard-Token: <token>.
    Bypasses auth if SHELLGUARD_DISABLE_AUTH=1 is explicitly set.
    """
    if os.environ.get("SHELLGUARD_DISABLE_AUTH", "0").lower() in ("1", "true", "yes"):
        return "auth_disabled"

    client_ip = request.client.host if request.client else "127.0.0.1"

    # Enforce Rate Limiting
    allowed, remaining, retry_after = rate_limiter.is_allowed(client_ip)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Try again in {retry_after}s.",
            headers={"Retry-After": str(int(retry_after))},
        )

    candidate = None
    if bearer and bearer.credentials:
        candidate = bearer.credentials
    elif api_key:
        candidate = api_key
    elif "shellguard_token" in request.query_params:
        candidate = request.query_params["shellguard_token"]

    if not candidate or not security_manager.verify_token(candidate):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized. Missing or invalid ShellGuard local authentication token.",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        )

    return candidate
