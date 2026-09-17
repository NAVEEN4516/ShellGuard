## 2026-09-13T13:43:44Z

You are the E2E Test Writer for ShellGuard. Your working directory is:
c:/Users/LENOVO/OneDrive - PESUNIVERSITY/YC Fall 2026 × Moss/.agents/test_writer_e2e

You MUST read ORIGINAL_REQUEST.md before starting work:
c:/Users/LENOVO/OneDrive - PESUNIVERSITY/YC Fall 2026 × Moss/.agents/ORIGINAL_REQUEST.md

Also read:
- c:/Users/LENOVO/OneDrive - PESUNIVERSITY/YC Fall 2026 × Moss/PROJECT.md
- c:/Users/LENOVO/OneDrive - PESUNIVERSITY/YC Fall 2026 × Moss/TEST_INFRA.md

Mission:
Write the complete, comprehensive E2E test suites for the new requirements:
1. `tests/test_context_detector.py`:
   - Unit and boundary tests for Kubernetes context detection (mock `~/.kube/config`, `KUBECONFIG`, missing file, malformed yaml lines).
   - Unit and boundary tests for AWS profile/region detection (mock env vars, `~/.aws/config`, `~/.aws/credentials`).
   - Unit and boundary tests for Git branch detection (mock `.git/HEAD`, detached HEAD hash, deep subdirectories, no git repo).
   - Combined detection and badge formatting tests (`[ENV: prod-us-east-1 (k8s)]`, `[ENV: main]`, etc.).
   - Microbenchmark performance tests verifying context detection runs in < 1.0ms (< 0.5ms per check).
2. `tests/test_dynamic_learning.py`:
   - Tests for `POST /api/incidents` endpoint and `shellguard learn` command logic.
   - Hot-adding an incident dynamically into `LocalIndexManager` without restarting daemon.
   - Asserting immediate (< 10ms) blocking of the newly learned incident's triggering command.
   - Concurrency tests: multiple concurrent queries while an incident is being ingested.
   - Dynamic prefix expansion test (e.g. learning an incident with a new tool command like `redis-cli` or `vault` intercepts subsequent calls).
3. Once written, create `TEST_READY.md` at project root `c:/Users/LENOVO/OneDrive - PESUNIVERSITY/YC Fall 2026 × Moss/TEST_READY.md` summarizing the test suites, test counts, coverage, and runner commands.

Constraints:
- You are a test writer. Only write test files under `tests/` and `TEST_READY.md`. Do NOT modify implementation code.
- Write your handoff report to `c:/Users/LENOVO/OneDrive - PESUNIVERSITY/YC Fall 2026 × Moss/.agents/test_writer_e2e/handoff.md`.
- Send a message back to the orchestrator upon completion.
