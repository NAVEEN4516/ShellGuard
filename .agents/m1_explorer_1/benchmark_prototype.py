import os
import re
import time
import configparser
from pathlib import Path

# Prototype ContextDetector to benchmark latency and verify parsing

class PrototypeContextDetector:
    def __init__(self, ttl: float = 0.5):
        self.ttl = ttl
        self._k8s_cache = {"last_check": 0.0, "path": None, "mtime": 0.0, "value": None}
        self._aws_cache = {"last_check": 0.0, "env_sig": None, "cfg_path": None, "cfg_mtime": 0.0, "val": None}
        self._git_cache = {}  # cwd -> {"last_check": float, "head_path": str, "mtime": float, "branch": str}
        self._global_cache = {}  # cwd -> {"last_check": float, "result": dict}

    def _get_k8s_path(self) -> str | None:
        env_kc = os.environ.get("KUBECONFIG")
        if env_kc:
            for p in env_kc.split(os.pathsep):
                p = p.strip()
                if p and os.path.isfile(p):
                    return p
        default_p = os.path.expanduser("~/.kube/config")
        if os.path.isfile(default_p):
            return default_p
        return None

    def _parse_k8s_file(self, path: str) -> str | None:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            pattern = re.compile(
                r"^[ \t]*current-context:[ \t]*(?:['\"]([^'\"]*)['\"]|([^#\r\n\s]+))",
                re.MULTILINE
            )
            m = pattern.search(content)
            if not m:
                return None
            val = (m.group(1) if m.group(1) is not None else m.group(2) or "").strip()
            return val if val else None
        except Exception:
            return None

    def detect_k8s(self, now: float) -> str | None:
        cache = self._k8s_cache
        if now - cache["last_check"] < self.ttl:
            return cache["value"]

        path = self._get_k8s_path()
        if not path:
            cache.update({"last_check": now, "path": None, "mtime": 0.0, "value": None})
            return None

        try:
            mtime = os.stat(path).st_mtime
        except OSError:
            cache.update({"last_check": now, "path": None, "mtime": 0.0, "value": None})
            return None

        if path == cache["path"] and mtime == cache["mtime"]:
            cache["last_check"] = now
            return cache["value"]

        val = self._parse_k8s_file(path)
        cache.update({"last_check": now, "path": path, "mtime": mtime, "value": val})
        return val

    def detect_aws(self, now: float) -> str | None:
        cache = self._aws_cache
        profile_env = os.environ.get("AWS_PROFILE") or os.environ.get("AWS_DEFAULT_PROFILE")
        region_env = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
        env_sig = (profile_env, region_env)

        if now - cache["last_check"] < self.ttl and cache["env_sig"] == env_sig:
            return cache["val"]

        # If both env vars set, no disk check needed
        if profile_env and region_env:
            val = f"{profile_env}:{region_env}"
            cache.update({"last_check": now, "env_sig": env_sig, "val": val})
            return val

        # Check config file
        cfg_path = os.environ.get("AWS_CONFIG_FILE") or os.path.expanduser("~/.aws/config")
        if not os.path.isfile(cfg_path):
            if profile_env:
                val = profile_env
            else:
                val = None
            cache.update({"last_check": now, "env_sig": env_sig, "cfg_path": None, "cfg_mtime": 0.0, "val": val})
            return val

        try:
            mtime = os.stat(cfg_path).st_mtime
        except OSError:
            val = profile_env
            cache.update({"last_check": now, "env_sig": env_sig, "cfg_path": None, "cfg_mtime": 0.0, "val": val})
            return val

        if cfg_path == cache["cfg_path"] and mtime == cache["cfg_mtime"] and cache["env_sig"] == env_sig:
            cache["last_check"] = now
            return cache["val"]

        # Parse config file
        profile = profile_env or "default"
        region = region_env
        try:
            cp = configparser.ConfigParser()
            cp.read(cfg_path, encoding="utf-8")
            sec = f"profile {profile}" if profile != "default" else "default"
            if cp.has_section(sec) and cp.has_option(sec, "region"):
                region = cp.get(sec, "region").strip()
            elif profile != "default" and cp.has_section(profile) and cp.has_option(profile, "region"):
                region = cp.get(profile, "region").strip()
            elif cp.has_section("default") and cp.has_option("default", "region") and not region:
                region = cp.get("default", "region").strip()
        except Exception:
            pass

        if profile_env:
            val = f"{profile_env}:{region}" if region else profile_env
        elif region:
            val = f"{profile}:{region}"
        else:
            val = None

        cache.update({"last_check": now, "env_sig": env_sig, "cfg_path": cfg_path, "cfg_mtime": mtime, "val": val})
        return val

    def detect_git(self, cwd: str, now: float) -> str | None:
        cached = self._git_cache.get(cwd)
        if cached and (now - cached["last_check"] < self.ttl):
            return cached["branch"]

        # Search up to 5 levels
        cur = os.path.abspath(cwd)
        head_path = None
        for _ in range(5):
            dot_git = os.path.join(cur, ".git")
            if os.path.isdir(dot_git):
                head_candidate = os.path.join(dot_git, "HEAD")
                if os.path.isfile(head_candidate):
                    head_path = head_candidate
                    break
            elif os.path.isfile(dot_git):
                try:
                    with open(dot_git, "r", encoding="utf-8", errors="ignore") as f:
                        line = f.readline().strip()
                    if line.startswith("gitdir:"):
                        gdir = line.split(":", 1)[1].strip()
                        if not os.path.isabs(gdir):
                            gdir = os.path.normpath(os.path.join(cur, gdir))
                        head_candidate = os.path.join(gdir, "HEAD")
                        if os.path.isfile(head_candidate):
                            head_path = head_candidate
                            break
                except Exception:
                    pass
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent

        if not head_path:
            self._git_cache[cwd] = {"last_check": now, "head_path": None, "mtime": 0.0, "branch": None}
            return None

        try:
            mtime = os.stat(head_path).st_mtime
        except OSError:
            self._git_cache[cwd] = {"last_check": now, "head_path": None, "mtime": 0.0, "branch": None}
            return None

        if cached and cached["head_path"] == head_path and cached["mtime"] == mtime:
            cached["last_check"] = now
            return cached["branch"]

        # Read HEAD
        branch = None
        try:
            with open(head_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read().strip()
            if content.startswith("ref: refs/heads/"):
                branch = content[16:].strip()
            elif content:
                # Detached commit sha
                sha = content.split()[0]
                branch = f"detached:{sha[:7]}" if len(sha) >= 7 else sha
        except Exception:
            branch = None

        self._git_cache[cwd] = {"last_check": now, "head_path": head_path, "mtime": mtime, "branch": branch}
        return branch

    def detect(self, cwd: str | None = None) -> dict[str, str | None]:
        now = time.monotonic()
        target_cwd = cwd or os.getcwd()
        cached_res = self._global_cache.get(target_cwd)
        if cached_res and (now - cached_res["last_check"] < self.ttl):
            return cached_res["result"]

        res = {
            "k8s": self.detect_k8s(now),
            "aws": self.detect_aws(now),
            "git": self.detect_git(target_cwd, now)
        }
        self._global_cache[target_cwd] = {"last_check": now, "result": res}
        return res

    def format_badge(self, env: dict[str, str | None]) -> str | None:
        parts = []
        if env.get("k8s"):
            parts.append(f"{env['k8s']} (k8s)")
        if env.get("aws"):
            parts.append(f"{env['aws']} (aws)")
        if env.get("git"):
            parts.append(f"{env['git']} (git)")
        if not parts:
            return None
        return f"[ENV: {' | '.join(parts)}]"


if __name__ == "__main__":
    detector = PrototypeContextDetector()
    cwd = os.getcwd()

    # Cold run
    t0 = time.perf_counter()
    cold_res = detector.detect(cwd)
    cold_ms = (time.perf_counter() - t0) * 1000
    badge = detector.format_badge(cold_res)
    print(f"Cold run: {cold_ms:.4f}ms -> res={cold_res}, badge={badge}")

    # Warm runs benchmark (10,000 runs)
    N = 10000
    t0 = time.perf_counter()
    for _ in range(N):
        detector.detect(cwd)
    total_sec = time.perf_counter() - t0
    warm_avg_ms = (total_sec / N) * 1000
    print(f"Warm run average over {N} iterations: {warm_avg_ms:.6f}ms ({warm_avg_ms * 1000:.2f} microseconds)")

    # Test badge formatting variations
    assert detector.format_badge({"k8s": "prod-k8s", "aws": None, "git": None}) == "[ENV: prod-k8s (k8s)]"
    assert detector.format_badge({"k8s": None, "aws": "prod:us-east-1", "git": None}) == "[ENV: prod:us-east-1 (aws)]"
    assert detector.format_badge({"k8s": None, "aws": None, "git": "main"}) == "[ENV: main (git)]"
    assert detector.format_badge({"k8s": "prod-k8s", "aws": "prod:us-east-1", "git": "main"}) == "[ENV: prod-k8s (k8s) | prod:us-east-1 (aws) | main (git)]"
    assert detector.format_badge({"k8s": None, "aws": None, "git": None}) is None
    print("Badge formatting unit checks passed!")
