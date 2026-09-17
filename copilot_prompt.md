# ShellGuard: Modular Architecture Copilot Specification & Submission Prompt
**Project:** ShellGuard — Zero-Latency Terminal Interceptor  
**Event:** YC Fall 2026 × Moss: The Zero Latency Builder Sprint  
**Track:** Track 04 — Local-First AI & The Small Cloud  
**Submission Format:** Modular Architecture Specification (Compliant with Architecture Copilot & Evaluator Standards)  

---

## 🧭 Master Architecture Summary

```
Project: ShellGuard (Zero-Latency Terminal Interceptor)
Core Moat: In-Process Moss Semantic Engine (< 4ms warm p50 retrieval, 65x faster than Cloud RAG)
Mandatory Stack:
  - Moss: Embedded in-process Rust/C runtime (inferedge-moss-core 0.23.1)
  - LiveKit: WebRTC real-time audio alert chimes (880Hz P0 / 440Hz P1) + Collaborative SRE War Rooms
  - Next.js: Next.js 14 App Router Local Web Cockpit (Radar feed, Latency gauge, Command simulator)
Security: OS-Level Credential Stores (Windows DPAPI, macOS Keychain, Linux Secret Service) + Configurable Fail Policy
Topology Graph: Structured C4 JSON schema (architecture_graph.json) with explicit ports (out-db) and labeled edges
Specification: IEEE 830 SRS standard with 24-requirement Bidirectional Traceability Matrix (PRD.md)
```

---

## 🧩 Modular Architecture Blocks

To iterate on specific system components without re-submitting monolithic context, invoke individual modules using the tag `[TARGET: Module <X>]`:

### Module A: Core In-Process Engine & 12-Factor Justification
```markdown
[MODULE: CORE-ENGINE-AND-12-FACTOR]
Components: daemon/engine.py, daemon/indexer.py, daemon/config.py
Key Capabilities:
  - In-process semantic similarity search via moss_core.LocalIndexManager (model: moss-minilm).
  - Multi-tier latency pipeline:
      * Deterministic high-pass bypass filter (< 0.01ms) for benign commands (ls, pwd, git status).
      * Multi-cloud context detector (< 0.3ms) for K8s clusters, AWS profiles, and Git branches.
      * Semantic vector retrieval against 29+ disaster post-mortems (3.7ms p50 warm).
  - 12-Factor App Compliance & Stateful Exception Justification:
      * Factor III: 100% environment-driven configuration via Pydantic BaseSettings (ShellGuardSettings).
      * Factor VI: In-process state exception justified by the physical impossibility of sub-10ms WAN vector RAG; in-memory index is an ephemeral cache reconstituted deterministically from immutable data/incidents/*.md in < 45ms.
      * Factor IX: Disposability: fast boot (< 500ms), crash-safe, zero persistent DB locks.
```

### Module B: OS Credential Store & Security Hardening
```markdown
[MODULE: OS-SECURITY-AND-CREDENTIAL-STORE]
Components: daemon/security.py, hooks/shellguard.ps1, hooks/shellguard.bash, hooks/shellguard.zsh
Key Capabilities:
  - OSCredentialStore: Eliminates plaintext ~/.shellguard/token files.
      * Windows: Native DPAPI (CryptProtectData) bound to current logon session (token.dpapi). Decrypted natively in PowerShell via [System.Security.Cryptography.ProtectedData] in < 0.1ms.
      * macOS / Linux: Native Keyring (macOS Keychain via Apple Security Framework; Linux Secret Service / KWallet via D-Bus).
      * Legacy Migration: Automatically migrates plaintext tokens, shredding and unlinking plain files.
  - Configurable Fail-Safe Security Policy (SHELLGUARD_FAIL_POLICY):
      * 'fail_open' (Default): Preserves developer terminal responsiveness if daemon is offline with audit warnings.
      * 'fail_closed': Enforces enterprise zero-trust; halts destructive commands if daemon is unreachable or killed.
  - OWASP API Hardening: Constant-time token verification, sliding-window rate limiter (300 req / 60s), null-byte rejection (\x00), and 4096-char payload ceiling.
```

### Module C: Mandatory Stack: LiveKit & Next.js Cockpit
```markdown
[MODULE: LIVEKIT-AND-NEXTJS-STACK]
Components: daemon/livekit_bridge.py, dashboard/ (Next.js 14 App Router)
Key Capabilities:
  - LiveKit WebRTC Real-Time Bridge:
      * Generates cryptographically valid HS256 JWT Access Tokens with roomJoin, canPublish, and canSubscribe grants.
      * Dispatches emergency audio chime payloads (880Hz P0 / 440Hz P1) synthesized via Web Audio API.
      * Provisions collaborative SRE War Rooms (shellguard-warroom-<incident_id>) for incident retrospectives.
  - Next.js Local Web Cockpit:
      * Live Command Radar Feed with similarity chips, severity badges, and copyable safe commands.
      * Zero-Latency Simulator with dangerous and safe command presets.
      * Latency Gauge Speedometer displaying Moss 65x speedup over Cloud Vector DBs.
      * Dual Deployment: Standalone dev (npm run dev :3000) or static export (dashboard/out/) served directly by the FastAPI daemon at http://127.0.0.1:8080/.
```

### Module D: Structured Topology Graph & Port Definitions
```markdown
[MODULE: TOPOLOGY-GRAPH-AND-PORTS]
File: architecture_graph.json & ARCHITECTURE.md
Key Capabilities:
  - Node 'shellguard-daemon' explicitly declares all ports:
      * 'in-http': Local REST & SSE API Port (8080)
      * 'in-shell': Hook Interception IPC Loopback Port
      * 'out-db': Incident DB & Storage Port (data/incidents/ and ~/.shellguard/)
      * 'out-webrtc': LiveKit WebRTC Audio & War Room Egress
      * 'out-trace': OpenTelemetry OTLP Collector (4318)
  - Edge 'b619cd0e-bc97-4572-adf3-87d3c8d74917':
      * Source: shellguard-daemon:out-db
      * Target: local-configs:in-fs
      * Label: "Reads/Writes local incident post-mortems and configuration"
      * Description: Loads post-mortems from data/incidents/, synchronizes dynamic incidents, and queries OS credential store.
```

### Module E: IEEE 830 Requirements Traceability Matrix
```markdown
[MODULE: IEEE-830-SRS-AND-RTM]
File: PRD.md
Key Capabilities:
  - 24 uniquely identified requirements:
      * Functional: REQ-F-001 to REQ-F-008 (Moss core, bypass, safe alt, dynamic learning, context, Next.js, LiveKit, CRISPE).
      * Interfaces: REQ-INT-001 to REQ-INT-004 (Moss C-bindings, Next.js REST, LiveKit JWT, Shell hooks).
      * Non-Functional: REQ-NF-001 to REQ-NF-005 (Sub-10ms SLA, sub-1ms bypass, air-gapped zero hops, footprint, OpenTelemetry).
      * Security: REQ-SEC-001 to REQ-SEC-006 (Token auth, rate limiting, sanitization, OS DPAPI store, fail policy, 12-Factor config).
  - Bidirectional RTM mapping every requirement to its architecture component, source implementation file, and pytest verification case.
```

---

## 🛠️ Modular Iteration Guide for Reviewers & Engineers

When requesting modifications or enhancements to ShellGuard, follow this pattern:

```markdown
Target: [Select one: Module A | Module B | Module C | Module D | Module E]
Instruction: [Specify exact enhancement, e.g. "Add biometric TouchID / Windows Hello prompt to Module B"]
Constraint: [Specify latency or security constraint, e.g. "Maintain < 10ms warm retrieval budget"]
```
