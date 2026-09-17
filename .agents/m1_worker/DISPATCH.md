## 2026-09-13T13:49:54Z
You are Milestone 1 Worker. Your working directory is:
c:/Users/LENOVO/OneDrive - PESUNIVERSITY/YC Fall 2026 × Moss/.agents/m1_worker

You MUST read ORIGINAL_REQUEST.md before starting work:
c:/Users/LENOVO/OneDrive - PESUNIVERSITY/YC Fall 2026 × Moss/.agents/ORIGINAL_REQUEST.md

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Write ownership:
You EXCLUSIVELY own and may write to: `daemon/context.py`.
Do NOT modify any other existing source or test files.

Read the specifications and blueprints produced by the 3 M1 Explorers:
- c:/Users/LENOVO/OneDrive - PESUNIVERSITY/YC Fall 2026 × Moss/PROJECT.md
- c:/Users/LENOVO/OneDrive - PESUNIVERSITY/YC Fall 2026 × Moss/.agents/m1_explorer_1/analysis.md
- c:/Users/LENOVO/OneDrive - PESUNIVERSITY/YC Fall 2026 × Moss/.agents/m1_explorer_2/analysis.md
- c:/Users/LENOVO/OneDrive - PESUNIVERSITY/YC Fall 2026 × Moss/.agents/m1_explorer_3/analysis.md

Mission:
Implement the complete, production-ready `daemon/context.py` providing:
1. `ContextDetector` class with:
   - `detect(cwd: Optional[str] = None) -> Dict[str, Optional[str]]` returning `{"k8s": str|None, "aws": str|None, "git": str|None}`
   - `format_badge(env: Dict[str, Optional[str]]) -> Optional[str]` formatting e.g. `[ENV: prod-us-east-1 (k8s)]` (or whatever components are active)
2. Pure standard library only (strictly zero pyyaml, zero boto3, zero subprocess calls).
3. Pure Python K8s parser:
   - Check `$KUBECONFIG` (split with `os.pathsep` on Windows/POSIX); fallback to `~/.kube/config`.
   - Streaming regex line parser matching `current-context:\s*(.+)` handling quotes, whitespace, and stripping comments.
4. Pure Python AWS parser:
   - Env vars `$AWS_PROFILE`, `$AWS_REGION`, `$AWS_DEFAULT_REGION`.
   - INI parser using `configparser.ConfigParser(default_section=None, inline_comment_prefixes=('#', ';'))` for `~/.aws/config` and `~/.aws/credentials`.
5. Pure Python Git parser:
   - Traverses upwards from `cwd` (up to 5 levels) looking for `.git`.
   - Handles standard `.git/HEAD` (`ref: refs/heads/(.*)`), detached HEAD commits, and linked worktrees / submodules (`gitdir: <path>`).
6. High-performance TTL-mtime caching:
   - 0.5s TTL window before re-checking `st_mtime`.
   - Validates that warm detection completes in < 0.02ms and cold detection in < 0.5ms.
7. Verification:
   - Run unit tests and microbenchmark on `daemon/context.py` using python to verify correctness and latency.
   - Run `.venv\Scripts\pytest.exe -v` to ensure all 54 existing regression tests continue to pass.

Output:
- Write `changes.md` and `handoff.md` to `c:/Users/LENOVO/OneDrive - PESUNIVERSITY/YC Fall 2026 × Moss/.agents/m1_worker/`.
- Send a message back to the orchestrator upon completion.
