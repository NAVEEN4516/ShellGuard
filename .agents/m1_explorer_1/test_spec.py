import os
import re
import sys
import time
import tempfile
import threading
import configparser
from pathlib import Path
from typing import Dict, Optional, Tuple

class ContextDetector:
    """
    Sub-millisecond multi-cloud environment context detector for Kubernetes, AWS, and Git.
    Zero external dependencies (pure standard library).
    Two-tier caching: in-memory TTL check (<0.001ms) + st_mtime validation.
    """
    _K8S_CONTEXT_RE = re.compile(
        r"^[ \t]*current-context:[ \t]*(?:['\"]([^'\"]*)['\"]|([^#\r\n\s]+))",
        re.MULTILINE
    )

    def __init__(self, ttl: float = 0.5):
        self.ttl = ttl
        self._lock = threading.Lock()
        # k8s cache: (last_check, file_path, mtime, context_val)
        self._k8s_cache: Dict[str, any] = {
            "last_check": 0.0,
            "path": None,
            "mtime": 0.0,
            "value": None
        }
        # aws cache: (last_check, env_tuple, path, mtime, aws_val)
        self._aws_cache: Dict[str, any] = {
            "last_check": 0.0,
            "env_sig": None,
            "path": None,
            "mtime": 0.0,
            "value": None
        }
        # git cache by cwd: cwd -> {"last_check": float, "head_path": str|None, "mtime": float, "branch": str|None}
        self._git_cache: Dict[str, Dict[str, any]] = {}
        # global cache: cwd -> {"last_check": float, "result": dict}
        self._global_cache: Dict[str, Dict[str, any]] = {}

    def _resolve_k8s_file(self) -> Optional[str]:
        env_kc = os.environ.get("KUBECONFIG")
        if env_kc:
            for p in env_kc.split(os.pathsep):
                p = p.strip()
                if p and os.path.isfile(p):
                    return p
        default_kc = os.path.expanduser("~/.kube/config")
        if os.path.isfile(default_kc):
            return default_kc
        return None

    def _parse_k8s_file(self, path: str) -> Optional[str]:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            match = self._K8S_CONTEXT_RE.search(content)
            if not match:
                return None
            val = (match.group(1) if match.group(1) is not None else match.group(2) or "").strip()
            return val if val else None
        except Exception:
            return None

    def detect_k8s(self, now: float) -> Optional[str]:
        cache = self._k8s_cache
        if (now - cache["last_check"]) < self.ttl:
            return cache["value"]

        path = self._resolve_k8s_file()
        if not path:
            cache["last_check"] = now
            cache["path"] = None
            cache["mtime"] = 0.0
            cache["value"] = None
            return None

        try:
            mtime = os.stat(path).st_mtime
        except OSError:
            cache["last_check"] = now
            cache["path"] = None
            cache["mtime"] = 0.0
            cache["value"] = None
            return None

        if path == cache["path"] and mtime == cache["mtime"]:
            cache["last_check"] = now
            return cache["value"]

        val = self._parse_k8s_file(path)
        cache["last_check"] = now
        cache["path"] = path
        cache["mtime"] = mtime
        cache["value"] = val
        return val

    def detect_aws(self, now: float) -> Optional[str]:
        cache = self._aws_cache
        prof_env = os.environ.get("AWS_PROFILE") or os.environ.get("AWS_DEFAULT_PROFILE")
        reg_env = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
        env_sig = (prof_env, reg_env)

        if (now - cache["last_check"]) < self.ttl and cache["env_sig"] == env_sig:
            return cache["value"]

        # If both profile and region exist in env vars, zero disk access required
        if prof_env and reg_env:
            val = f"{prof_env}:{reg_env}"
            cache["last_check"] = now
            cache["env_sig"] = env_sig
            cache["value"] = val
            return val

        cfg_path = os.environ.get("AWS_CONFIG_FILE") or os.path.expanduser("~/.aws/config")
        if not os.path.isfile(cfg_path):
            val = prof_env if prof_env else (reg_env if reg_env else None)
            cache["last_check"] = now
            cache["env_sig"] = env_sig
            cache["path"] = None
            cache["mtime"] = 0.0
            cache["value"] = val
            return val

        try:
            mtime = os.stat(cfg_path).st_mtime
        except OSError:
            val = prof_env if prof_env else (reg_env if reg_env else None)
            cache["last_check"] = now
            cache["env_sig"] = env_sig
            cache["path"] = None
            cache["mtime"] = 0.0
            cache["value"] = val
            return val

        if cfg_path == cache["path"] and mtime == cache["mtime"] and cache["env_sig"] == env_sig:
            cache["last_check"] = now
            return cache["value"]

        target_profile = prof_env or "default"
        found_region = reg_env
        try:
            parser = configparser.RawConfigParser()
            parser.read(cfg_path, encoding="utf-8")
            # AWS config format: [default] or [profile <name>] or [<name>]
            candidate_sections = []
            if target_profile == "default":
                candidate_sections.extend(["default", "profile default"])
            else:
                candidate_sections.extend([f"profile {target_profile}", target_profile])

            if not found_region:
                for sec in candidate_sections:
                    if parser.has_section(sec) and parser.has_option(sec, "region"):
                        found_region = parser.get(sec, "region").strip()
                        break
        except Exception:
            pass

        if prof_env and found_region:
            val = f"{prof_env}:{found_region}"
        elif prof_env:
            val = prof_env
        elif found_region:
            if target_profile == "default":
                val = f"default:{found_region}"
            else:
                val = f"{target_profile}:{found_region}"
        else:
            val = None

        cache["last_check"] = now
        cache["env_sig"] = env_sig
        cache["path"] = cfg_path
        cache["mtime"] = mtime
        cache["value"] = val
        return val

    def detect_git(self, cwd: str, now: float) -> Optional[str]:
        cache = self._git_cache.get(cwd)
        if cache and (now - cache["last_check"]) < self.ttl:
            return cache["branch"]

        cur = os.path.abspath(cwd)
        head_path = None
        for _ in range(5):
            dot_git = os.path.join(cur, ".git")
            if os.path.isdir(dot_git):
                cand = os.path.join(dot_git, "HEAD")
                if os.path.isfile(cand):
                    head_path = cand
                    break
            elif os.path.isfile(dot_git):
                try:
                    with open(dot_git, "r", encoding="utf-8", errors="ignore") as f:
                        line = f.readline().strip()
                    if line.startswith("gitdir:"):
                        gdir = line.split(":", 1)[1].strip()
                        if not os.path.isabs(gdir):
                            gdir = os.path.normpath(os.path.join(cur, gdir))
                        cand = os.path.join(gdir, "HEAD")
                        if os.path.isfile(cand):
                            head_path = cand
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

        if cache and cache["head_path"] == head_path and cache["mtime"] == mtime:
            cache["last_check"] = now
            return cache["branch"]

        branch = None
        try:
            with open(head_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read().strip()
            if content.startswith("ref: refs/heads/"):
                branch = content[16:].strip()
            elif content:
                sha = content.split()[0]
                branch = f"detached:{sha[:7]}" if len(sha) >= 7 else sha
        except Exception:
            branch = None

        self._git_cache[cwd] = {"last_check": now, "head_path": head_path, "mtime": mtime, "branch": branch}
        return branch

    def detect(self, cwd: Optional[str] = None) -> Dict[str, Optional[str]]:
        """
        Detects active environment context for Kubernetes, AWS, and Git.
        Returns: {"k8s": str|None, "aws": str|None, "git": str|None}
        """
        now = time.monotonic()
        target_cwd = cwd or os.getcwd()

        with self._lock:
            cached = self._global_cache.get(target_cwd)
            if cached and (now - cached["last_check"]) < self.ttl:
                # Return shallow copy to protect internal cache from mutation
                return dict(cached["result"])

            res = {
                "k8s": self.detect_k8s(now),
                "aws": self.detect_aws(now),
                "git": self.detect_git(target_cwd, now)
            }
            # Keep cache bounded to 128 directories to prevent memory leaks
            if len(self._global_cache) > 128:
                self._global_cache.clear()
            self._global_cache[target_cwd] = {"last_check": now, "result": res}
            return dict(res)

    def format_badge(self, env: Dict[str, Optional[str]]) -> Optional[str]:
        """
        Formats detected environment dictionary into a compact human-readable badge.
        Returns e.g. '[ENV: prod-us-east-1 (k8s)]' or None if all null/empty.
        """
        if not env:
            return None
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


def test_comprehensive_suite():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # 1. Test K8s parsing with various YAML forms
        k8s_cfg = tmp_path / "kubeconfig"
        k8s_cfg.write_text("apiVersion: v1\nkind: Config\ncurrent-context: my-cluster-prod\nclusters: []\n", encoding="utf-8")
        os.environ["KUBECONFIG"] = str(k8s_cfg)

        # 2. Test AWS parsing with custom config
        aws_cfg = tmp_path / "aws_config"
        aws_cfg.write_text("[profile prod-stage]\nregion = us-west-2\n[default]\nregion = us-east-1\n", encoding="utf-8")
        os.environ["AWS_CONFIG_FILE"] = str(aws_cfg)
        os.environ["AWS_PROFILE"] = "prod-stage"
        os.environ.pop("AWS_REGION", None)

        # 3. Test Git branch detection in temporary repository
        git_dir = tmp_path / "my_repo"
        git_dir.mkdir()
        (git_dir / ".git").mkdir()
        head_file = git_dir / ".git" / "HEAD"
        head_file.write_text("ref: refs/heads/feature/auth-v2\n", encoding="utf-8")
        sub_dir = git_dir / "src" / "deep" / "nested"
        sub_dir.mkdir(parents=True)

        detector = ContextDetector(ttl=0.5)

        res = detector.detect(cwd=str(sub_dir))
        assert res["k8s"] == "my-cluster-prod", f"Expected my-cluster-prod, got {res['k8s']}"
        assert res["aws"] == "prod-stage:us-west-2", f"Expected prod-stage:us-west-2, got {res['aws']}"
        assert res["git"] == "feature/auth-v2", f"Expected feature/auth-v2, got {res['git']}"

        badge = detector.format_badge(res)
        expected_badge = "[ENV: my-cluster-prod (k8s) | prod-stage:us-west-2 (aws) | feature/auth-v2 (git)]"
        assert badge == expected_badge, f"Expected {expected_badge}, got {badge}"

        # 4. Test Git worktree (.git as file pointing to gitdir)
        worktree_dir = tmp_path / "worktree"
        worktree_dir.mkdir()
        wt_dot_git = worktree_dir / ".git"
        common_git = tmp_path / "main_repo_git"
        common_git.mkdir()
        (common_git / "HEAD").write_text("ref: refs/heads/worktree-branch\n", encoding="utf-8")
        wt_dot_git.write_text(f"gitdir: {common_git}\n", encoding="utf-8")

        res_wt = detector.detect(cwd=str(worktree_dir))
        assert res_wt["git"] == "worktree-branch", f"Expected worktree-branch, got {res_wt['git']}"

        # 5. Test Detached HEAD
        (common_git / "HEAD").write_text("8a3b5c7d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b\n", encoding="utf-8")
        # Force cache expire by waiting TTL or creating new detector
        detector_detached = ContextDetector(ttl=0.0)
        res_det = detector_detached.detect(cwd=str(worktree_dir))
        assert res_det["git"] == "detached:8a3b5c7", f"Expected detached:8a3b5c7, got {res_det['git']}"

        # 6. Test Empty/None Cases
        assert detector.format_badge({"k8s": None, "aws": None, "git": None}) is None
        assert detector.format_badge({}) is None

        # Clean env vars
        os.environ.pop("KUBECONFIG", None)
        os.environ.pop("AWS_CONFIG_FILE", None)
        os.environ.pop("AWS_PROFILE", None)

    print("All comprehensive suite unit tests passed successfully!")

if __name__ == "__main__":
    test_comprehensive_suite()
