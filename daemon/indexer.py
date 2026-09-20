"""
ShellGuard Indexer
Parses incident post-mortems and security policies, indexing them into Moss's local in-memory runtime.
"""

import os
import re
import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Union

try:
    import moss_core
except Exception as _moss_err:
    logger.warning(f"Native moss_core unavailable ({_moss_err}), using in-process lexical shim.")

    class DocumentInfo:
        def __init__(self, id: str, text: str, payload: str = ""):
            self.id = id
            self.text = text
            self.payload = payload

    class QueryResult:
        def __init__(self, doc_id: str, score: float, payload: str = ""):
            self.id = doc_id
            self.score = score
            self.payload = payload

    class LocalIndexManager:
        def __init__(self):
            self._indices: Dict[str, List[DocumentInfo]] = {}

        def has_index(self, name: str) -> bool:
            return name in self._indices

        def delete_index(self, name: str):
            self._indices.pop(name, None)

        def create_index(self, name: str, docs: List[DocumentInfo], model_id: str):
            self._indices[name] = list(docs)

        def add_documents(self, name: str, docs: List[DocumentInfo]):
            if name not in self._indices:
                self._indices[name] = []
            self._indices[name].extend(docs)

        def query(self, name: str, query_text: str, top_k: int = 3) -> List[QueryResult]:
            if name not in self._indices:
                return []
            docs = self._indices[name]
            q_words = set(re.findall(r"\w+", query_text.lower()))
            if not q_words:
                return []
            scored = []
            for d in docs:
                d_words = set(re.findall(r"\w+", d.text.lower()))
                overlap = len(q_words & d_words)
                total = len(q_words | d_words) or 1
                jaccard = overlap / total
                score = min(0.99, max(0.1, jaccard * 1.5))
                scored.append(QueryResult(d.id, score, d.payload))
            scored.sort(key=lambda x: x.score, reverse=True)
            return scored[:top_k]

    class _MossCoreShim:
        DocumentInfo = DocumentInfo
        LocalIndexManager = LocalIndexManager

    moss_core = _MossCoreShim()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("shellguard.indexer")

INCIDENTS_DIR = Path(__file__).resolve().parent.parent / "data" / "incidents"
INDEX_NAME = "shellguard_incidents"
MODEL_ID = "moss-minilm"


def parse_incident_markdown(file_or_content: Union[Path, str]) -> Dict[str, Any]:
    """Parse a post-mortem markdown file or raw content string into structured metadata."""
    file_name = "raw_incident.md"
    if isinstance(file_or_content, Path) or (isinstance(file_or_content, str) and os.path.exists(file_or_content)):
        p = Path(file_or_content)
        file_name = p.name
        content = p.read_text(encoding="utf-8")
    else:
        content = str(file_or_content)
    
    # Extract title
    title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else "Custom Incident"
    
    # Extract ID
    id_match = re.search(r"-\s+\*\*Incident ID:\*\*\s+([A-Z0-9\-]+)", content)
    if not id_match:
        id_match = re.search(r"\*\s+\*\*Incident ID:\*\*\s+([A-Z0-9\-]+)", content)
    incident_id = id_match.group(1).strip() if id_match else (Path(file_name).stem if file_name != "raw_incident.md" else "INC-CUSTOM")
    
    # Extract Severity
    sev_match = re.search(r"[-*]\s+\*\*Severity:\*\*\s+([A-Z0-9]+)", content)
    severity = sev_match.group(1).strip() if sev_match else "P1"
    
    # Extract Triggering Command Pattern
    cmd_block = ""
    cmd_match = re.search(r"##\s+\d*\.?\s*Triggering Command Pattern.*?```(?:bash|sh)?\r?\n(.*?)```", content, re.DOTALL | re.IGNORECASE)
    if cmd_match:
        cmd_block = cmd_match.group(1).strip()

    # Extract Root Cause
    rc_match = re.search(r"##\s+\d*\.?\s*Root Cause\s+(.*?)(?=\r?\n##|\Z)", content, re.DOTALL | re.IGNORECASE)
    root_cause = rc_match.group(1).strip() if rc_match else ""

    # Extract Blast Radius
    blast_match = re.search(r"##\s+\d*\.?\s*Blast Radius\s+(.*?)(?=\r?\n##|\Z)", content, re.DOTALL | re.IGNORECASE)
    blast_radius = blast_match.group(1).strip() if blast_match else ""

    # Extract Safe Alternative
    safe_block = ""
    safe_match = re.search(r"##\s+\d*\.?\s*Mandatory Safe Alternative\s+(.*?)(?=\r?\n##|\Z)", content, re.DOTALL | re.IGNORECASE)
    if safe_match:
        safe_block = safe_match.group(1).strip()

    # Extract executable command blocks separately from prose notes
    safe_cmds = []
    for code_match in re.finditer(r"```([a-zA-Z0-9_-]*)\r?\n(.*?)\r?\n```", safe_block, re.DOTALL):
        lang = code_match.group(1).lower()
        if not lang or lang in ("bash", "sh", "zsh", "shell"):
            for line in code_match.group(2).splitlines():
                clean_l = line.strip()
                if clean_l and not clean_l.startswith("#"):
                    safe_cmds.append(clean_l)
    safe_cmd = "\n".join(safe_cmds) if safe_cmds else ""
    safe_notes = re.sub(r"```[a-zA-Z0-9_-]*\r?\n.*?\r?\n```", "", safe_block, flags=re.DOTALL).strip()

    # Extract Interception Rule & Recommendation (supports both hyphen and asterisk)
    rec_block = ""
    rec_match = re.search(r"[-*]\s+\*\*Recommendation:\*\*\s+(.*?)$", content, re.MULTILINE)
    if rec_match:
        rec_block = rec_match.group(1).strip()

    action_match = re.search(r"[-*]\s+\*\*Action:\*\*\s+([A-Z_]+)", content)
    action = action_match.group(1).strip() if action_match else "HARD_BLOCK"

    # Build dense searchable semantic text for Moss embedding
    semantic_text = f"{title}. Dangerous command pattern: {cmd_block}. Action: {action}. Root cause: {root_cause}"

    return {
        "id": incident_id,
        "title": title,
        "severity": severity,
        "commands": [c.strip() for c in cmd_block.splitlines() if c.strip()],
        "semantic_text": semantic_text,
        "safe_alternative": safe_block,
        "safe_alternative_cmd": safe_cmd,
        "safe_alternative_notes": safe_notes,
        "recommendation": rec_block,
        "action": action,
        "root_cause": root_cause,
        "blast_radius": blast_radius,
        "file_name": file_name,
    }


def create_incident_chunks(inc: Dict[str, Any]) -> List[moss_core.DocumentInfo]:
    """Generate granular command chunks and summary chunk for an incident."""
    docs = []
    for idx, cmd in enumerate(inc["commands"]):
        chunk_id = f"{inc['id']}_cmd_{idx}"
        chunk_text = f"Command: {cmd}. Severity: {inc['severity']}. Incident: {inc['title']}"
        payload_json = json.dumps({
            "incident_id": inc["id"],
            "title": inc["title"],
            "severity": inc["severity"],
            "matched_pattern": cmd,
            "action": inc["action"],
            "recommendation": inc["recommendation"],
            "safe_alternative": inc["safe_alternative"],
            "safe_alternative_cmd": inc.get("safe_alternative_cmd", ""),
            "safe_alternative_notes": inc.get("safe_alternative_notes", ""),
            "blast_radius": inc["blast_radius"],
        })
        docs.append(moss_core.DocumentInfo(id=chunk_id, text=chunk_text, payload=payload_json))

    summary_id = f"{inc['id']}_summary"
    docs.append(moss_core.DocumentInfo(
        id=summary_id,
        text=inc["semantic_text"],
        payload=json.dumps({
            "incident_id": inc["id"],
            "title": inc["title"],
            "severity": inc["severity"],
            "matched_pattern": inc["title"],
            "action": inc["action"],
            "recommendation": inc["recommendation"],
            "safe_alternative": inc["safe_alternative"],
            "safe_alternative_cmd": inc.get("safe_alternative_cmd", ""),
            "safe_alternative_notes": inc.get("safe_alternative_notes", ""),
            "blast_radius": inc["blast_radius"],
        })
    ))
    return docs


def load_all_incidents(incidents_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Load all incident documents from directory."""
    target_dir = incidents_dir or INCIDENTS_DIR
    if not target_dir.exists():
        logger.warning(f"Incidents directory {target_dir} does not exist.")
        return []

    incidents = []
    for md_file in sorted(target_dir.glob("*.md")):
        try:
            doc_data = parse_incident_markdown(md_file)
            incidents.append(doc_data)
        except Exception as e:
            logger.error(f"Failed to parse {md_file}: {e}")
    return incidents


def build_index(index_manager: moss_core.LocalIndexManager, incidents: List[Dict[str, Any]]) -> int:
    """Build or rebuild local in-memory Moss index."""
    if not incidents:
        logger.warning("No incidents to index.")
        return 0

    if index_manager.has_index(INDEX_NAME):
        logger.info(f"Removing existing index: {INDEX_NAME}")
        index_manager.delete_index(INDEX_NAME)

    docs = []
    for inc in incidents:
        docs.extend(create_incident_chunks(inc))

    logger.info(f"Indexing {len(docs)} document chunks into Moss '{INDEX_NAME}' with model '{MODEL_ID}'...")
    index_manager.create_index(INDEX_NAME, docs, MODEL_ID)
    logger.info(f"Successfully indexed {len(docs)} documents into in-memory Moss runtime.")
    return len(docs)
