"""
ShellGuard Indexer
Parses incident post-mortems and security policies, indexing them into Moss's local in-memory runtime.
"""

import os
import re
import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional

import moss_core

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("shellguard.indexer")

INCIDENTS_DIR = Path(__file__).resolve().parent.parent / "data" / "incidents"
INDEX_NAME = "shellguard_incidents"
MODEL_ID = "moss-minilm"


def parse_incident_markdown(file_path: Path) -> Dict[str, Any]:
    """Parse a post-mortem markdown file into structured metadata."""
    content = file_path.read_text(encoding="utf-8")
    
    # Extract title
    title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else file_path.stem
    
    # Extract ID
    id_match = re.search(r"-\s+\*\*Incident ID:\*\*\s+([A-Z0-9\-]+)", content)
    incident_id = id_match.group(1).strip() if id_match else file_path.stem
    
    # Extract Severity
    sev_match = re.search(r"-\s+\*\*Severity:\*\*\s+([A-Z0-9]+)", content)
    severity = sev_match.group(1).strip() if sev_match else "P1"
    
    # Extract Triggering Command Pattern
    cmd_block = ""
    cmd_match = re.search(r"## 2\.\s+Triggering Command Pattern\s+```(?:bash|sh)?\n(.*?)```", content, re.DOTALL)
    if cmd_match:
        cmd_block = cmd_match.group(1).strip()
    
    # Extract Safe Alternative
    safe_block = ""
    safe_match = re.search(r"## 5\.\s+Mandatory Safe Alternative\s+(.*?)(?=## 6|\Z)", content, re.DOTALL)
    if safe_match:
        safe_block = safe_match.group(1).strip()

    # Extract Interception Rule & Recommendation
    rec_block = ""
    rec_match = re.search(r"-\s+\*\*Recommendation:\*\*\s+(.*?)$", content, re.MULTILINE)
    if rec_match:
        rec_block = rec_match.group(1).strip()

    action_match = re.search(r"-\s+\*\*Action:\*\*\s+([A-Z_]+)", content)
    action = action_match.group(1).strip() if action_match else "HARD_BLOCK"

    # Extract Root Cause
    rc_match = re.search(r"## 3\.\s+Root Cause\s+(.*?)(?=## 4|\Z)", content, re.DOTALL)
    root_cause = rc_match.group(1).strip() if rc_match else ""

    # Extract Blast Radius
    blast_match = re.search(r"## 4\.\s+Blast Radius\s+(.*?)(?=## 5|\Z)", content, re.DOTALL)
    blast_radius = blast_match.group(1).strip() if blast_match else ""

    # Build dense searchable semantic text for Moss embedding
    semantic_text = f"{title}. Dangerous command pattern: {cmd_block}. Action: {action}. Root cause: {root_cause}"

    return {
        "id": incident_id,
        "title": title,
        "severity": severity,
        "commands": [c.strip() for c in cmd_block.splitlines() if c.strip()],
        "semantic_text": semantic_text,
        "safe_alternative": safe_block,
        "recommendation": rec_block,
        "action": action,
        "root_cause": root_cause,
        "blast_radius": blast_radius,
        "file_name": file_path.name,
    }


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
        # Include individual commands as distinct chunks to maximize recall
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
                "blast_radius": inc["blast_radius"],
            })
            docs.append(moss_core.DocumentInfo(id=chunk_id, text=chunk_text, payload=payload_json))

        # Also index general incident summary
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
                "blast_radius": inc["blast_radius"],
            })
        ))

    logger.info(f"Indexing {len(docs)} document chunks into Moss '{INDEX_NAME}' with model '{MODEL_ID}'...")
    index_manager.create_index(INDEX_NAME, docs, MODEL_ID)
    logger.info(f"Successfully indexed {len(docs)} documents into in-memory Moss runtime.")
    return len(docs)
