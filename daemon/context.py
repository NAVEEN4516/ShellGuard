"""
ShellGuard Multi-Cloud Context Detector.
Sub-millisecond detection of Kubernetes cluster context, AWS profile/region, and Git branch.
Pure Python standard library implementation with zero third-party dependencies (no pyyaml, no boto3, zero subprocess calls).
"""

import os
import re
import time
import threading
import configparser
from pathlib import Path
from typing import Dict, Optional, Any, Tuple, List, Union


# Streaming line regex for K8s current-context extraction
_K8S_CONTEXT_RE = re.compile(
    r"^[ \t]*current-context:[ \t]*(?:['\"]([^'\"]*)['\"]|([^#\r\n\s]+))"
)

# Regex for Git detached HEAD commit SHA (7 to 64 hex characters)
_GIT_HEX_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")


def _split_kubeconfig_env(env_val: Optional[str]) -> List[str]:
    """
    Split KUBECONFIG environment variable string preserving Windows drive letters.
    Uses ';' on Windows or when ';' is present; otherwise ':'.
    Expands '~' for each path.
    """
    if not env_val or not env_val.strip():
        return []

    sep = ";" if (";" in env_val or os.name == "nt") else ":"
    paths: List[str] = []
    for part in env_val.split(sep):
        part = part.strip()
        if part:
            paths.append(os.path.expanduser(part))
    return paths


def _get_default_kubeconfig_path() -> Optional[str]:
    """Resolve default ~/.kube/config path respecting monkeypatched Path.home()."""
    try:
        cand = str(Path.home() / ".kube" / "config")
        return cand
    except Exception:
        return os.path.expanduser("~/.kube/config")


def _parse_k8s_line(line: str) -> Optional[str]:
    """Parse a single line for current-context."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if "current-context:" not in line:
        return None
    match = _K8S_CONTEXT_RE.search(line)
    if not match:
        return None
    val = (match.group(1) if match.group(1) is not None else (match.group(2) or "")).strip()
    if not val or val.lower() in ("null", "~", "''", '""'):
        return None
    return val


def parse_k8s_context(path_or_content: Optional[str] = None) -> Optional[str]:
    """
    Pure Python streaming parser for Kubernetes active cluster context.

    Args:
        path_or_content: Optional file path or raw YAML content string.
                         If None, resolves via $KUBECONFIG or ~/.kube/config.
    """
    if path_or_content is not None:
        if os.path.isfile(path_or_content):
            try:
                with open(path_or_content, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        val = _parse_k8s_line(line)
                        if val:
                            return val
                return None
            except OSError:
                return None
        # String content
        for line in path_or_content.splitlines():
            val = _parse_k8s_line(line)
            if val:
                return val
        return None

    env_kc = os.environ.get("KUBECONFIG")
    paths = _split_kubeconfig_env(env_kc)
    if not paths:
        def_path = _get_default_kubeconfig_path()
        if def_path:
            paths.append(def_path)

    for p in paths:
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    val = _parse_k8s_line(line)
                    if val:
                        return val
        except OSError:
            continue
    return None


def parse_aws_config(
    config_path: Optional[str] = None,
    profile: Optional[str] = None,
    credentials_path: Optional[str] = None,
) -> Optional[str]:
    """
    Pure Python INI parser for AWS profile and region detection.
    Zero boto3 dependency.
    """
    explicit_profile = profile or os.environ.get("AWS_PROFILE") or os.environ.get("AWS_DEFAULT_PROFILE")
    env_region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")

    # Fast path: If both profile and region exist in env vars, zero disk access
    if explicit_profile and env_region:
        return f"{explicit_profile}:{env_region.strip()}"

    # Determine config file path
    if config_path is None:
        cfg_env = os.environ.get("AWS_CONFIG_FILE")
        if cfg_env:
            config_path = os.path.expanduser(cfg_env)
        else:
            try:
                config_path = str(Path.home() / ".aws" / "config")
            except Exception:
                config_path = os.path.expanduser("~/.aws/config")

    # Determine credentials file path
    if credentials_path is None:
        cred_env = os.environ.get("AWS_SHARED_CREDENTIALS_FILE")
        if cred_env:
            credentials_path = os.path.expanduser(cred_env)
        else:
            try:
                credentials_path = str(Path.home() / ".aws" / "credentials")
            except Exception:
                credentials_path = os.path.expanduser("~/.aws/credentials")

    cp_config: Optional[configparser.ConfigParser] = None
    if config_path:
        try:
            cp = configparser.ConfigParser(
                default_section=None,
                inline_comment_prefixes=("#", ";"),
                strict=False,
                allow_no_value=True,
                interpolation=None,
            )
            with open(config_path, "r", encoding="utf-8", errors="replace") as f:
                cp.read_file(f)
            cp_config = cp
        except Exception:
            cp_config = None

    cp_cred: Optional[configparser.ConfigParser] = None
    if credentials_path:
        try:
            cp = configparser.ConfigParser(
                default_section=None,
                inline_comment_prefixes=("#", ";"),
                strict=False,
                allow_no_value=True,
                interpolation=None,
            )
            with open(credentials_path, "r", encoding="utf-8", errors="replace") as f:
                cp.read_file(f)
            cp_cred = cp
        except Exception:
            cp_cred = None

    has_any_file = (cp_config is not None) or (cp_cred is not None)
    if not explicit_profile and not env_region and not has_any_file:
        return None

    target_profile = explicit_profile if explicit_profile else "default"

    if target_profile.lower() == "default":
        candidate_sections = ["default", "profile default"]
    else:
        candidate_sections = [f"profile {target_profile}", target_profile]

    # Region Resolution: Env > Config > Credentials
    region: Optional[str] = env_region.strip() if env_region else None

    def _extract_region(cp: configparser.ConfigParser) -> Optional[str]:
        existing_sections = {s.strip().lower(): s for s in cp.sections()}
        for cand in candidate_sections:
            real_sec = existing_sections.get(cand.strip().lower())
            if real_sec:
                for opt in ("region", "sso_region"):
                    if cp.has_option(real_sec, opt):
                        v = cp.get(real_sec, opt, fallback=None)
                        if v and v.strip():
                            return v.strip()
        return None

    if not region and cp_config:
        region = _extract_region(cp_config)
    if not region and cp_cred:
        region = _extract_region(cp_cred)

    # Verify if target profile exists in files when not explicitly in env
    profile_exists_in_files = False
    for cp in (cp_config, cp_cred):
        if cp:
            existing_sections = {s.strip().lower(): s for s in cp.sections()}
            for cand in candidate_sections:
                if cand.strip().lower() in existing_sections:
                    profile_exists_in_files = True
                    break
            if profile_exists_in_files:
                break

    if not explicit_profile and not profile_exists_in_files and not env_region:
        return None

    active_profile = target_profile if (explicit_profile or profile_exists_in_files) else None

    if active_profile and region:
        return f"{active_profile}:{region}"
    elif active_profile:
        return active_profile
    elif region:
        return region
    return None


def parse_git_head(head_path_or_content: Optional[str] = None) -> Optional[str]:
    """
    Pure Python parser for Git HEAD content.
    Returns branch name or 'detached:<sha[:7]>'.
    Zero subprocess calls.
    """
    content: Optional[str] = None
    if head_path_or_content is not None:
        if os.path.isfile(head_path_or_content):
            try:
                with open(head_path_or_content, "r", encoding="utf-8", errors="replace") as f:
                    content = f.readline().strip()
            except OSError:
                return None
        else:
            lines = head_path_or_content.strip().splitlines()
            content = lines[0].strip() if lines else ""
    else:
        curr = os.path.abspath(os.getcwd())
        for _ in range(6):
            cand = os.path.join(curr, ".git", "HEAD")
            try:
                with open(cand, "r", encoding="utf-8", errors="replace") as f:
                    content = f.readline().strip()
                break
            except OSError:
                pass

            git_p = os.path.join(curr, ".git")
            try:
                if os.path.isfile(git_p):
                    with open(git_p, "r", encoding="utf-8", errors="replace") as f:
                        line = f.readline().strip()
                    if line.startswith("gitdir:"):
                        gdir = line[7:].strip()
                        if not os.path.isabs(gdir):
                            gdir = os.path.normpath(os.path.join(curr, gdir))
                        cand = os.path.join(gdir, "HEAD")
                        with open(cand, "r", encoding="utf-8", errors="replace") as f:
                            content = f.readline().strip()
                        break
            except OSError:
                pass
            parent = os.path.dirname(curr)
            if parent == curr:
                break
            curr = parent

    if not content:
        return None

    if content.startswith("ref:"):
        ref = content[4:].strip()
        if not ref:
            return None
        if ref.startswith("refs/heads/"):
            val = ref[11:].strip()
            return val if val else None
        return ref if ref else None
    elif _GIT_HEX_SHA_RE.match(content):
        return f"detached:{content[:7].lower()}"
    return None


class ContextDetector:
    """
    High-performance, sub-millisecond multi-cloud environment context detector.
    Detects active Kubernetes cluster context, AWS profile/region, and Git branch.
    Zero third-party dependencies (strictly pure standard library).
    Two-tier caching: in-memory TTL window check (<0.001ms) + st_mtime validation (<0.15ms).
    """

    def __init__(self, ttl: float = 0.5, max_cache_size: int = 256):
        """
        Initialize the context detector.

        Args:
            ttl: Time-to-live in seconds for in-memory cache before verifying st_mtime.
                 Default is 0.5s. When <= 0, caching is completely disabled.
            max_cache_size: Maximum entries in directory-keyed caches before eviction.
        """
        self.ttl = ttl
        self.max_cache_size = max_cache_size
        self._lock = threading.Lock()

        # Component-level caches
        # K8s: (last_check, k8s_sig, home_sig, path, mtime, size, value)
        self._k8s_cache: Tuple[float, str, str, Optional[str], float, int, Optional[str]] = (
            0.0, "", "", None, 0.0, 0, None
        )

        # AWS: (last_check, aws_sig, home_sig, cfg_path, cfg_mtime, cred_path, cred_mtime, value)
        self._aws_cache: Tuple[float, Tuple[str, ...], str, Optional[str], float, Optional[str], float, Optional[str]] = (
            0.0, (), "", None, 0.0, None, 0.0, None
        )

        # Git directory cache: cwd -> {"head_path": Optional[str], "expires_at": float}
        self._cwd_to_head: Dict[str, Dict[str, Any]] = {}
        # Git HEAD cache: head_path -> {"branch": Optional[str], "mtime": float, "size": int, "expires_at": float}
        self._head_cache: Dict[str, Dict[str, Any]] = {}

        # Global aggregated cache per cwd:
        # cwd -> {"last_check": float, "k8s_sig": str, "aws_sig": tuple, "home_sig": str, "result": dict}
        self._global_cache: Dict[str, Dict[str, Any]] = {}

    def _get_env_signatures(self) -> Tuple[str, Tuple[str, ...], str]:
        k8s_sig = os.environ.get("KUBECONFIG", "")
        aws_sig = (
            os.environ.get("AWS_PROFILE", ""),
            os.environ.get("AWS_DEFAULT_PROFILE", ""),
            os.environ.get("AWS_REGION", ""),
            os.environ.get("AWS_DEFAULT_REGION", ""),
            os.environ.get("AWS_CONFIG_FILE", ""),
            os.environ.get("AWS_SHARED_CREDENTIALS_FILE", ""),
        )
        home_sig = os.environ.get("USERPROFILE") or os.environ.get("HOME") or ""
        return k8s_sig, aws_sig, home_sig

    def detect_k8s(self, now: Optional[float] = None) -> Optional[str]:
        """Detect active Kubernetes context with TTL-mtime caching."""
        if now is None:
            now = time.monotonic()
        k8s_sig, _, home_sig = self._get_env_signatures()

        if self.ttl > 0:
            last_check, c_k8s_sig, c_home_sig, c_path, c_mtime, c_size, c_val = self._k8s_cache
            # Tier 1: In-memory TTL window check
            if (now - last_check) < self.ttl and k8s_sig == c_k8s_sig and home_sig == c_home_sig:
                return c_val

        paths = _split_kubeconfig_env(k8s_sig)
        if not paths:
            def_path = _get_default_kubeconfig_path()
            if def_path:
                paths.append(def_path)

        target_path: Optional[str] = None
        target_mtime = 0.0
        target_size = 0

        for p in paths:
            try:
                st = os.stat(p)
                target_path = p
                target_mtime = st.st_mtime
                target_size = st.st_size
                break
            except OSError:
                continue

        if not target_path:
            if self.ttl > 0:
                self._k8s_cache = (now, k8s_sig, home_sig, None, 0.0, 0, None)
            return None

        # Tier 2: st_mtime check
        if self.ttl > 0:
            last_check, c_k8s_sig, c_home_sig, c_path, c_mtime, c_size, c_val = self._k8s_cache
            if target_path == c_path and target_mtime == c_mtime and target_size == c_size and k8s_sig == c_k8s_sig and home_sig == c_home_sig:
                self._k8s_cache = (now, k8s_sig, home_sig, target_path, target_mtime, target_size, c_val)
                return c_val

        val = parse_k8s_context(target_path)
        if self.ttl > 0:
            self._k8s_cache = (now, k8s_sig, home_sig, target_path, target_mtime, target_size, val)
        return val

    def detect_aws(self, now: Optional[float] = None) -> Optional[str]:
        """Detect active AWS profile and region with TTL-mtime caching."""
        if now is None:
            now = time.monotonic()
        _, aws_sig, home_sig = self._get_env_signatures()

        if self.ttl > 0:
            last_check, c_aws_sig, c_home_sig, c_cfg_path, c_cfg_mtime, c_cred_path, c_cred_mtime, c_val = self._aws_cache
            # Tier 1: In-memory TTL window check
            if (now - last_check) < self.ttl and aws_sig == c_aws_sig and home_sig == c_home_sig:
                return c_val

        prof_env = os.environ.get("AWS_PROFILE") or os.environ.get("AWS_DEFAULT_PROFILE")
        reg_env = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")

        # Fast path: Profile + region in env -> zero disk access
        if prof_env and reg_env:
            val = f"{prof_env}:{reg_env.strip()}"
            if self.ttl > 0:
                self._aws_cache = (now, aws_sig, home_sig, None, 0.0, None, 0.0, val)
            return val

        cfg_env = os.environ.get("AWS_CONFIG_FILE")
        if cfg_env:
            cfg_path = os.path.expanduser(cfg_env)
        else:
            try:
                cfg_path = str(Path.home() / ".aws" / "config")
            except Exception:
                cfg_path = os.path.expanduser("~/.aws/config")

        cred_env = os.environ.get("AWS_SHARED_CREDENTIALS_FILE")
        if cred_env:
            cred_path = os.path.expanduser(cred_env)
        else:
            try:
                cred_path = str(Path.home() / ".aws" / "credentials")
            except Exception:
                cred_path = os.path.expanduser("~/.aws/credentials")

        cfg_mtime = 0.0
        if cfg_path:
            try:
                cfg_mtime = os.stat(cfg_path).st_mtime
            except OSError:
                cfg_mtime = 0.0

        cred_mtime = 0.0
        if cred_path:
            try:
                cred_mtime = os.stat(cred_path).st_mtime
            except OSError:
                cred_mtime = 0.0

        # Tier 2: st_mtime check
        if self.ttl > 0:
            last_check, c_aws_sig, c_home_sig, c_cfg_path, c_cfg_mtime, c_cred_path, c_cred_mtime, c_val = self._aws_cache
            if (cfg_path == c_cfg_path and cfg_mtime == c_cfg_mtime and
                cred_path == c_cred_path and cred_mtime == c_cred_mtime and
                aws_sig == c_aws_sig and home_sig == c_home_sig):
                self._aws_cache = (now, aws_sig, home_sig, cfg_path, cfg_mtime, cred_path, cred_mtime, c_val)
                return c_val

        val = parse_aws_config(config_path=cfg_path, credentials_path=cred_path)
        if self.ttl > 0:
            self._aws_cache = (now, aws_sig, home_sig, cfg_path, cfg_mtime, cred_path, cred_mtime, val)
        return val

    def _resolve_git_head_path(self, cwd: str) -> Optional[str]:
        """Traverse upwards up to 5 levels to find .git directory or file pointer."""
        curr = os.path.abspath(cwd)
        for _ in range(6):
            cand = os.path.join(curr, ".git", "HEAD")
            try:
                if os.path.isfile(cand):
                    return cand
            except OSError:
                pass

            git_p = os.path.join(curr, ".git")
            try:
                if os.path.isfile(git_p):
                    with open(git_p, "r", encoding="utf-8", errors="replace") as f:
                        line = f.readline().strip()
                    if line.startswith("gitdir:"):
                        gdir = line[7:].strip()
                        if not os.path.isabs(gdir):
                            gdir = os.path.normpath(os.path.join(curr, gdir))
                        cand = os.path.join(gdir, "HEAD")
                        if os.path.isfile(cand):
                            return cand
            except OSError:
                pass
            parent = os.path.dirname(curr)
            if parent == curr:
                break
            curr = parent
        return None

    def detect_git(self, cwd: Optional[str] = None, now: Optional[float] = None) -> Optional[str]:
        """Detect active Git branch or detached SHA with TTL-mtime caching."""
        if now is None:
            now = time.monotonic()
        norm_cwd = os.path.abspath(cwd or os.getcwd())

        head_path: Optional[str] = None
        if self.ttl > 0:
            cwd_entry = self._cwd_to_head.get(norm_cwd)
            if cwd_entry is not None and now < cwd_entry["expires_at"]:
                head_path = cwd_entry["head_path"]
            else:
                head_path = self._resolve_git_head_path(norm_cwd)
                if len(self._cwd_to_head) >= self.max_cache_size:
                    self._cwd_to_head.clear()
                self._cwd_to_head[norm_cwd] = {"head_path": head_path, "expires_at": now + self.ttl}
        else:
            head_path = self._resolve_git_head_path(norm_cwd)

        if not head_path:
            return None

        mtime = 0.0
        size = 0
        try:
            st = os.stat(head_path)
            mtime = st.st_mtime
            size = st.st_size
        except OSError:
            if self.ttl > 0:
                self._cwd_to_head.pop(norm_cwd, None)
                self._head_cache.pop(head_path, None)
            return None

        if self.ttl > 0:
            head_entry = self._head_cache.get(head_path)
            # Tier 1 & Tier 2: Check mtime & size
            if head_entry is not None and head_entry["mtime"] == mtime and head_entry.get("size") == size:
                head_entry["expires_at"] = now + self.ttl
                return head_entry["branch"]

        branch = parse_git_head(head_path)
        if self.ttl > 0:
            if len(self._head_cache) >= self.max_cache_size:
                self._head_cache.clear()
            self._head_cache[head_path] = {"branch": branch, "mtime": mtime, "size": size, "expires_at": now + self.ttl}
        return branch

    def detect(self, cwd: Optional[str] = None) -> Dict[str, Optional[str]]:
        """
        Detect active environment context across Kubernetes, AWS, and Git.

        Args:
            cwd: Working directory to inspect for Git repository. Defaults to os.getcwd().

        Returns:
            Dict containing exactly:
            {
                "k8s": str | None,
                "aws": str | None,
                "git": str | None
            }
        """
        now = time.monotonic()
        norm_cwd = os.path.abspath(cwd or os.getcwd())
        k8s_sig, aws_sig, home_sig = self._get_env_signatures()

        with self._lock:
            if self.ttl > 0:
                cached = self._global_cache.get(norm_cwd)
                if cached is not None:
                    if ((now - cached["last_check"]) < self.ttl and
                        cached["k8s_sig"] == k8s_sig and
                        cached["aws_sig"] == aws_sig and
                        cached["home_sig"] == home_sig):
                        return dict(cached["result"])

            res = {
                "k8s": self.detect_k8s(now),
                "aws": self.detect_aws(now),
                "git": self.detect_git(norm_cwd, now),
            }

            if self.ttl > 0:
                if len(self._global_cache) >= self.max_cache_size:
                    self._global_cache.clear()

                self._global_cache[norm_cwd] = {
                    "last_check": now,
                    "k8s_sig": k8s_sig,
                    "aws_sig": aws_sig,
                    "home_sig": home_sig,
                    "result": res,
                }
            return dict(res)

    @staticmethod
    def format_badge(env: Optional[Dict[str, Optional[str]]]) -> Optional[str]:
        """
        Formats detected environment dictionary into a compact human-readable badge.

        Args:
            env: Dict returned by detect(), e.g. {"k8s": "...", "aws": "...", "git": "..."}

        Returns:
            Formatted badge string, e.g. '[ENV: prod-us-east-1 (k8s)]' or None if all empty.
        """
        if not env or not isinstance(env, dict):
            return None
        parts: List[str] = []
        k8s = env.get("k8s")
        if k8s:
            parts.append(f"{k8s} (k8s)")
        aws = env.get("aws")
        if aws:
            parts.append(f"{aws} (aws)")
        git = env.get("git")
        if git:
            parts.append(f"{git} (git)")
        if not parts:
            return None
        return f"[ENV: {' | '.join(parts)}]"


def detect_environment(cwd: Optional[str] = None) -> Dict[str, Optional[str]]:
    """Convenience functional wrapper around ContextDetector.detect()."""
    return ContextDetector().detect(cwd=cwd)


def format_badge(env: Optional[Dict[str, Optional[str]]]) -> Optional[str]:
    """Convenience functional wrapper around ContextDetector.format_badge()."""
    return ContextDetector.format_badge(env)
