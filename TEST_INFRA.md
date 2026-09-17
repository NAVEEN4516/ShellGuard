# E2E Test Infra: ShellGuard Dynamic Incident Learning and Multi-Cloud Context Awareness

## Test Philosophy
- Opaque-box, requirement-driven. No dependency on implementation internals.
- Methodology: Category-Partition + Boundary Value Analysis (BVA) + Pairwise Combinatorial Testing + Real-World Workload Testing.
- Strict performance guardrails:
  - Context detection latency < 0.5ms per check (< 1.0ms total)
  - Warm query end-to-end latency p50 < 10.0ms
  - Hot incident ingestion without daemon restart or dropped hook connections
  - Zero regressions on existing 54 test cases

## Feature Inventory & Test Matrix
| # | Feature | Source | Tier 1 (Feature) | Tier 2 (BVA/Edge) | Tier 3 (Pairwise) | Tier 4 (Workload) |
|---|---------|--------|:----------------:|:-----------------:|:-----------------:|:-----------------:|
| F1 | Sub-ms Context Detector | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ | ✓ |
| F2 | Engine Context & Badging | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ | ✓ |
| F3 | Incident Parser Regex Fix | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ | ✓ |
| F4 | Dynamic Hot-Reloading & Prefixes | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ | ✓ |
| F5 | API Ingestion & Events Stream | ORIGINAL_REQUEST §R1, R3 | 5 | 5 | ✓ | ✓ |
| F6 | Shell Hooks & CLI Learn | ORIGINAL_REQUEST §R1, R3 | 5 | 5 | ✓ | ✓ |
| F7 | Web Cockpit Dynamic Sync | ORIGINAL_REQUEST §R3, AC | 5 | 5 | ✓ | ✓ |

## Test Architecture
- Test Runner: pytest via `.venv/Scripts/pytest.exe -v`
- Test Suites:
  - `tests/test_context_detector.py`: Unit, edge-case, and microbenchmark tests for K8s, AWS, and Git context parsing.
  - `tests/test_dynamic_learning.py`: Tests for `POST /api/incidents`, `shellguard learn`, dynamic index updates, immediate blocking (<10ms), and concurrent queries without connection drops.
  - `tests/test_engine.py`, `tests/test_safety_matrix.py`, `tests/test_api.py`: Existing 54 regression tests.
  - `tests/test_e2e_benchmark.py`: End-to-end latency and badge verification under load.

## Real-World Application Scenarios (Tier 4)
| # | Scenario | Features Exercised | Complexity |
|---|----------|--------------------|------------|
| 1 | SRE ingests a new post-mortem markdown on production outage (`k8s delete ns`); CLI and terminal hooks immediately block the triggering command with badge `[ENV: prod-k8s]` without daemon restart. | F1, F2, F3, F4, F5, F6 | High |
| 2 | Developer switches Git branches and AWS profiles while working in terminal; `shellguard check` dynamically shifts environment badge from `[ENV: feature-branch]` to `[ENV: prod-us-east-1]` with zero latency penalty (< 0.5ms). | F1, F2, F6 | Medium |
| 3 | Operator loads an incident containing a brand new root command prefix (e.g. `vault kv delete`); engine dynamically expands `interception_prefixes` so subsequent commands are intercepted rather than bypassed. | F3, F4, F5 | High |
| 4 | High-concurrency scenario: 100 simultaneous terminal hook checks occur while a new incident is posted to `/api/incidents`; all 100 checks succeed with 0 timeouts and 0 dropped connections. | F4, F5 | High |
| 5 | Web Cockpit live radar and incident explorer dynamically receive SSE updates upon ingestion of an incident and render real-time telemetry with environment badges. | F2, F5, F7 | Medium |

## Coverage Thresholds
- Tier 1: ≥35 test cases across 7 features
- Tier 2: ≥35 boundary/corner test cases
- Tier 3: Pairwise cross-feature interaction cases
- Tier 4: ≥5 realistic end-to-end application scenarios
- Tier 5: Adversarial coverage hardening via Challenger
- Total Target: All new tests passing + all 54 existing tests passing + warm query p50 < 10.0ms.
