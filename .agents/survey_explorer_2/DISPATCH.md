## 2026-09-13T13:23:20Z

Explore the codebase to map technical requirements and architecture for:
R2: Sub-Millisecond Multi-Cloud Environment Context Detection (Kubernetes context, AWS profile/region, Git branch < 0.5ms/check, warm query < 10ms).
R3: Environment Badges & Decorated Interception Alerts across engine, shell hooks (`.zsh`, `.bash`, `.ps1`), CLI, and telemetry.
CLI command `shellguard learn <path-or-markdown>`.

Scope & Investigation Targets:
1. Examine `cli.py`, `daemon/engine.py`, shell hooks (`hooks/shellguard.zsh`, `hooks/shellguard.bash`, `hooks/shellguard.ps1`), and any telemetry or history logging modules.
2. Design the sub-millisecond context detector:
   - Reading active Kubernetes context from `~/.kube/config` or `$KUBECONFIG`
   - Reading active AWS profile/region from `$AWS_PROFILE` / `~/.aws/config` / env vars
   - Reading active Git branch from `.git/HEAD`
   - Techniques for ultra-fast parsing (< 0.5ms/check, avoiding heavy dependencies like full pyyaml or boto3 if they add overhead, or using optimized fast-path parsing/caching with mtime checks).
3. Design CLI command `shellguard learn <path-or-markdown>`: how it invokes the daemon API `POST /api/incidents` or direct local fallback.
4. Design environment badge decoration (e.g. `[ENV: prod-us-east-1 (k8s)]`) across engine interception alerts, shell hook outputs, CLI formatting, and telemetry records.
5. Identify all file paths, data structures, and CLI arguments affected.
