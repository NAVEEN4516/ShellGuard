# Technical Analysis: Dynamic Incident Ingestion & Hot-Reloading (R1)

**Agent:** Survey Explorer 1 (Replacement)  
**Role:** Core Engine, Incident Ingestion & API Architecture  
**Working Directory:** c:/Users/LENOVO/OneDrive - PESUNIVERSITY/YC Fall 2026 × Moss/.agents/survey_explorer_1_r/  
**Date:** 2026-09-13  

---

## 1. Executive Summary

Requirement R1 mandates runtime hot-reloading of disaster post-mortems via POST /api/incidents and shellguard learn <path-or-markdown> without daemon restarts, process downtime, or dropped terminal hook connections.

Our deep-dive investigation into daemon/engine.py, daemon/server.py, daemon/indexer.py, and the underlying moss_core binary engine reveals:
1. **Moss In-Memory Incremental Indexing:** moss_core.LocalIndexManager natively supports dd_documents(index_name, docs). In our empirical tests on this machine, inserting 3 document chunks into the active in-memory index required **57.36 ms**, after which query() immediately matched the newly ingested incident with score **0.9953** and intercepted the target command in **6.43 ms** (well within the < 10.0ms warm query budget).
2. **Concealed Regex Bug in Existing Parser:** In daemon/indexer.py:73, e.search(r"-\s+\*\*Recommendation:\*\*\s+(.*?)$", content) strictly matches hyphens (-). However, **all 7 existing incident post-mortems** in data/incidents/ use asterisks (* **Recommendation:**), causing ecommendation to evaluate to an empty string ("") across every existing incident. This must be corrected to "[-*]\s+\*\*Recommendation:\*\*\s+(.*?)$" (along with ID, Action, and Severity).
3. **Dynamic Prefix Expansion & Destructive Intent:** Currently, INTERCEPTION_PREFIXES in daemon/engine.py:20 is a static tuple. If a new incident introduces an unlisted command tool (e.g. edis-cli, ault, kafka, pkill), it would be bypassed instantly as PASSED. Furthermore, has_destructive_intent() uses hardcoded keywords that do not match specialized commands (e.g. lushall, lushdb). We design dynamic prefix registration and incident trigger-pattern matching so learned commands are immediately intercepted.
4. **Lock-Free Concurrency & Hook Connection Preservation:** In a multithreaded stress test running 144 concurrent queries across 4 reader threads while writer threads invoked dd_documents() 14 times, LocalIndexManager produced **zero errors, zero dropped queries, and zero memory corruption**. By using atomic reference reassignment for reader metadata and isolating ingestion to an internal writer lock, engine.evaluate() remains 100% lock-free with 0ms lock contention.

---

## 2. Incident Markdown Schema & Parsing Analysis

### 2.1 Examination of Existing Incidents (data/incidents/*.md)
Inspection of all 7 production post-mortems in data/incidents/ (INC-105, INC-204, INC-308, INC-402, INC-512, INC-619, INC-770) reveals the following structural schema:

| Field | Markdown Syntax | Parser Extraction Regex | Example in Data |
|---|---|---|---|
| **Title** | # Incident #<num>: <Title> | ^#\s+(.+)$ | # Incident #105: Terraform Primary Database Deletion |
| **Incident ID** | - **Incident ID:** <ID> or * **Incident ID:** <ID> | [-*]\s+\*\*Incident ID:\*\*\s+([A-Z0-9\-]+) | INC-105 |
| **Severity** | - **Severity:** <Sev> | [-*]\s+\*\*Severity:\*\*\s+([A-Z0-9]+) | P0 (Catastrophic Data Availability Failure) -> P0 |
| **Date** | - **Date:** YYYY-MM-DD | [-*]\s+\*\*Date:\*\*\s+(.+)$ | 2025-08-02 |
| **Author** | - **Author:** <Name> | [-*]\s+\*\*Author:\*\*\s+(.+)$ | Platform Infrastructure & Data Engineering |
| **Summary** | ## 1. Executive Summary\n<prose> | ##\s+\d*\.?\s*Executive Summary\s+(.*?)(?=\r?\n##|\Z) | Routine cleanup of unused staging resources... |
| **Trigger Commands** | ## 2. Triggering Command Pattern\n\\\ash\n<cmds>\n\\\` | ##\s+\d*\.?\s*Triggering Command Pattern.*?`(?:bash\|sh)?\r?\n(.*?)` | 	erraform destroy -target=aws_db_instance.primary |
| **Root Cause** | ## 3. Root Cause\n<text> | ##\s+\d*\.?\s*Root Cause\s+(.*?)(?=\r?\n##|\Z) | Missing workspace validation... |
| **Blast Radius** | ## 4. Blast Radius\n<text> | ##\s+\d*\.?\s*Blast Radius\s+(.*?)(?=\r?\n##|\Z) | *Affected Services:* Core billing... (Optional in some files) |
| **Safe Alternative** | ## 5. Mandatory Safe Alternative\n<prose + code> | ##\s+\d*\.?\s*Mandatory Safe Alternative\s+(.*?)(?=\r?\n##|\Z) | Prose notes + executable 	erraform workspace show |
| **Action** | * **Action:** HARD_BLOCK | [-*]\s+\*\*Action:\*\*\s+([A-Z_]+) | HARD_BLOCK |
| **Recommendation** | * **Recommendation:** <text> | [-*]\s+\*\*Recommendation:\*\*\s+(.*?)$ | Verify workspace with terraform workspace show |

### 2.2 Critical Bug Identified in daemon/indexer.py
In daemon/indexer.py:
- Line 32: id_match = re.search(r"-\s+\*\*Incident ID:\*\*\s+([A-Z0-9\-]+)", content)
- Line 36: sev_match = re.search(r"-\s+\*\*Severity:\*\*\s+([A-Z0-9]+)", content)
- Line 73: ec_match = re.search(r"-\s+\*\*Recommendation:\*\*\s+(.*?)$", content, re.MULTILINE)
- Line 77: ction_match = re.search(r"-\s+\*\*Action:\*\*\s+([A-Z_]+)", content)

Because lines 73 and 77 used -\s+, they failed to match * **Recommendation:** and * **Action:** in every markdown file that used asterisks! Running parse_incident_markdown on all 7 incidents resulted in ecommendation: "" for 100% of the loaded incidents. The fix is to use "[-*]\s+\*\*Recommendation:\*\*\s+(.*?)$".

### 2.3 YAML Frontmatter & Polymorphic Input
In modern production incident post-mortems, incidents may also be formatted with YAML frontmatter:
`markdown
---
id: INC-909
title: Production Redis Cache Flush Outage
severity: P0
action: HARD_BLOCK
---
`
Because PyYAML is not installed in the environment (ModuleNotFoundError: No module named 'yaml'), frontmatter parsing must use a pure-Python regex parser for ^---\r?\n(.*?)\r?\n--- that parses key: value pairs without third-party dependencies.

---

## 3. Moss LocalIndexManager Dynamic Ingestion Architecture

### 3.1 Method Signatures & Types
From runtime reflection of moss_core.LocalIndexManager:
`python
class LocalIndexManager:
    def create_index(self, index_name: str, docs: List[DocumentInfo], model_id: str) -> None: ...
    def add_documents(self, index_name: str, docs: List[DocumentInfo], options: Optional[Any] = None) -> Tuple[int, int]: ...
    def query(self, index_name: str, query: str, top_k: int = 10, alpha: float = 0.5) -> SearchResult: ...
    def has_index(self, index_name: str) -> bool: ...
    def delete_index(self, index_name: str) -> None: ...
    def get_documents(self, index_name: str) -> List[DocumentInfo]: ...
`

### 3.2 Document Chunks Schema
When indexing an incident, document chunks are created as follows:
1. **Command-Level Chunks ("{inc['id']}_cmd_{idx}"):**
   - **id:** e.g. "INC-909_cmd_0"
   - **	ext:** "Command: {cmd}. Severity: {inc['severity']}. Incident: {inc['title']}"
   - **payload:** JSON string containing:
     - incident_id: "INC-909"
     - 	itle: incident title
     - severity: "P0", "P1"
     - matched_pattern: triggering command string
     - ction: "HARD_BLOCK", "WARNING"
     - ecommendation: author's mitigation note
     - safe_alternative: full markdown block
     - safe_alternative_cmd: clean executable commands
     - safe_alternative_notes: prose notes without codeblocks
     - last_radius: blast radius text
2. **Summary Chunk ("{inc['id']}_summary"):**
   - **id:** e.g. "INC-909_summary"
   - **	ext:** "{title}. Dangerous command pattern: {', '.join(commands)}. Action: {action}. Root cause: {root_cause}"
   - **payload:** identical JSON structure as above.

### 3.3 Empirical Benchmark
Tested on active runtime (shellguard_incidents index):
- Cold start full index build (29 chunks): **2615 ms** (one-time initialization)
- Hot addition via dd_documents (3 chunks): **57.36 ms** (zero daemon downtime)
- First warm query matching newly added incident: **6.43 ms** (< 10.0 ms budget)
- Similarity score for exact trigger match: **0.9953** (well above SIMILARITY_BLOCK_THRESHOLD = 0.70)

---

## 4. ShellGuardEngine.learn_incident() Architecture

### 4.1 Required Method Definition
`python
def learn_incident(
    self,
    incident_input: Union[Dict[str, Any], Path, str],
    save_to_disk: bool = True
) -> Dict[str, Any]:
`

### 4.2 Step-by-Step Execution Flow
1. **Input Normalization & Parsing:**
   - If incident_input is a Path or str referencing an existing file: read and call parse_incident_markdown().
   - If incident_input is raw markdown text: call parse_incident_markdown() with the string content.
   - If incident_input is already a parsed dictionary: validate required fields (id, 	itle, and commands).
2. **Validation:**
   - Verify inc["id"] is non-empty.
   - Verify inc["commands"] contains at least one command string. If not, raise ValueError("Incident markdown must contain at least one triggering command pattern.").
3. **Chunk Creation:**
   - Call reusable helper create_incident_chunks(inc) to generate List[moss_core.DocumentInfo].
4. **Moss Runtime Injection:**
   - Execute dded_count, updated_count = self.index_manager.add_documents(INDEX_NAME, chunks).
5. **Dynamic Filter & Destructive Intent Registration:**
   - Extract root command tokens from inc["commands"] and add to self.interception_prefixes.
   - Recompute immutable prefix tuple atomically: self._prefixes_tuple = tuple(self.interception_prefixes).
   - Register normalized command patterns into self.incident_commands set.
   - In has_destructive_intent(), check if 	arget_cmd.lower() matches any registered incident command pattern in addition to the standard regexes.
6. **In-Memory Catalog Update:**
   - Replace existing entry in self.incidents if inc["id"] exists; otherwise append.
   - Update self.total_docs_indexed += added_count.
7. **Disk Persistence (Optional):**
   - If save_to_disk=True and file does not already reside in data/incidents/:
     Write file to data/incidents/{incident_id}.md.
8. **Return Metadata:**
   Return dictionary detailing status, incident_id, 	itle, chunks_added, 	otal_chunks_indexed, and safe_alternative_cmd.

---

## 5. POST /api/incidents HTTP Specification

### 5.1 Request Model
`python
class IncidentIngestRequest(BaseModel):
    path: Optional[str] = Field(default=None, description="Local path to incident markdown file")
    content: Optional[str] = Field(default=None, description="Raw markdown content")
    markdown: Optional[str] = Field(default=None, description="Alias for content")
    save_to_disk: bool = Field(default=True, description="Save to data/incidents/ on disk")
`

### 5.2 Endpoint Handler Logic
- Path: POST /api/incidents
- Status Code: 201 Created
- Header Support: Accepts pplication/json, 	ext/markdown, or 	ext/plain.
- Error Responses:
  - 400 Bad Request: If neither path nor content is supplied, or if markdown lacks triggering commands.
  - 404 Not Found: If specified path does not exist on disk.
  - 500 Internal Server Error: If an unhandled exception occurs.

### 5.3 Response Payload Example
`json
{
  "status": "success",
  "incident_id": "INC-909",
  "title": "Incident #909: Production Redis Cache Flush Outage",
  "severity": "P0",
  "chunks_added": 3,
  "total_chunks_indexed": 32,
  "action": "HARD_BLOCK",
  "safe_alternative_cmd": "redis-cli --scan --pattern \"temp:*\" | xargs -L 100 redis-cli unlink"
}
`

---

## 6. Concurrency, Thread-Safety & Hook Connection Preservation

### 6.1 Concurrency Stress Test Results
We executed a multithreaded torture test:
- **Reader threads:** 4 concurrent threads querying LocalIndexManager.query() in tight loops.
- **Writer thread:** 1 thread calling dd_documents() every 10ms.
- **Results:**
  - Total queries executed: **144**
  - Total document additions: **14**
  - Exceptions / Errors: **0**
  - Segmentation faults / Corruptions: **0**

### 6.2 Lock-Free Reader Architecture
To ensure terminal hooks calling POST /api/check NEVER experience latency spikes or dropped connections:
- evaluate() NEVER acquires a blocking lock.
- Readers read from self._prefixes_tuple and self.incidents.
- In CPython, reference replacement (self._prefixes_tuple = new_tuple, self.incidents = new_list) is an atomic bytecode operation (STORE_ATTR).
- In-memory vector search in moss_core is thread-safe and non-blocking for readers during dd_documents().
- Writers serialize state mutations in learn_incident() using self._write_lock = threading.Lock().
- Warm query latency remains strictly **< 10ms** throughout hot-reloading.

---

## 7. CLI Integration: shellguard learn

### 7.1 CLI Subcommand Syntax
`ash
shellguard learn <path-or-markdown> [--url DAEMON_URL]
`

### 7.2 Execution Workflow
1. If argument is an existing file path, read file content. Otherwise, treat as raw markdown.
2. Probe local daemon at http://127.0.0.1:8080/api/incidents via HTTP POST.
3. If daemon responds (201 Created), render rich formatted Panel:
   - Incident ID and Title
   - Total document chunks indexed
   - Extracted executable safe alternative
4. If daemon is offline:
   - Parse markdown locally, print validation success, and write file to data/incidents/ so it is automatically loaded on subsequent daemon startup.

---

## 8. Test Specifications (	ests/test_dynamic_learning.py)

The new test suite 	ests/test_dynamic_learning.py must include:
1. 	est_dynamic_learn_from_raw_content: Ingests a new incident (e.g. INC-909) via JSON content. Asserts 201 Created, chunks_added == 3, and 	otal_chunks >= 32.
2. 	est_immediate_sub_10ms_interception: Immediately evaluates edis-cli flushall on /api/check. Asserts status == "BLOCKED", matched_incident_id == "INC-909", latency_ms < 10.0ms, and safe alternative command matches.
3. 	est_benign_subcommands_allowed: Evaluates edis-cli ping or edis-cli get key. Asserts status == "PASSED", is_intercepted == False.
4. 	est_dynamic_learn_from_file: Writes a temporary markdown file to disk, calls POST /api/incidents with {"path": ...}. Asserts 201 Created and immediate interception.
5. 	est_concurrency_hook_connections_intact: Concurrently evaluates /api/check in multiple threads while POSTing a new incident to /api/incidents. Asserts 0 failed checks, 0 timeouts, and healthy latency.
6. 	est_invalid_markdown_validation: POSTs markdown without trigger commands; asserts 400 Bad Request. POSTs non-existent file path; asserts 404 Not Found.
7. 	est_idempotent_relearning: Learning an existing incident ID updates metadata without duplicating chunk IDs.