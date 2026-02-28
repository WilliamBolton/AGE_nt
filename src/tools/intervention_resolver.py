"""Resolve user query to canonical intervention name and file paths using data/interventions.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Project root when running from repo (e.g. src/agents/ or scripts/)
def _project_root() -> Path:
    for start in [Path(__file__).resolve(), Path.cwd()]:
        root = start
        for _ in range(6):
            if (root / "data" / "interventions.json").exists():
                return root
            root = root.parent
    return Path.cwd()


def load_interventions(interventions_path: Path | None = None) -> list[dict[str, Any]]:
    """Load interventions list from data/interventions.json."""
    path = interventions_path or _project_root() / "data" / "interventions.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("interventions", [])


def resolve_intervention_from_query(user_query: str, interventions_path: Path | None = None) -> str | None:
    """
    Extract intervention name from user_query by matching against data/interventions.json.
    Matches the "name" field or any entry in "aliases" (case-insensitive, word/substring).
    Returns the canonical "name" from the first matching intervention, or None.
    """
    if not (user_query or user_query.strip()):
        return None
    q = user_query.strip().lower()
    interventions = load_interventions(interventions_path)
    for entry in interventions:
        name = entry.get("name")
        if not name:
            continue
        if name.lower() in q or q in name.lower():
            return name
        aliases = entry.get("aliases") or []
        for a in aliases:
            if isinstance(a, str) and (a.lower() in q or q in a.lower()):
                return name
    return None


def find_document_path(intervention_name: str, data_dir: Path | None = None) -> Path | None:
    """
    Resolve intervention name to data/documents/{intervention}.json.
    Tries exact name, then lowercase, then case-insensitive match in directory listing.
    """
    root = data_dir or _project_root()
    docs_dir = root / "data" / "documents"
    if not docs_dir.exists():
        return None
    # Exact
    p = docs_dir / f"{intervention_name}.json"
    if p.exists():
        return p
    # Lowercase
    p = docs_dir / f"{intervention_name.lower()}.json"
    if p.exists():
        return p
    # List and match
    for f in docs_dir.glob("*.json"):
        if f.stem.lower() == intervention_name.lower():
            return f
    return None


def find_trends_path(intervention_name: str, data_dir: Path | None = None) -> Path | None:
    """Resolve intervention name to data/trends/{intervention}.json (same logic as documents)."""
    root = data_dir or _project_root()
    trends_dir = root / "data" / "trends"
    if not trends_dir.exists():
        return None
    p = trends_dir / f"{intervention_name}.json"
    if p.exists():
        return p
    p = trends_dir / f"{intervention_name.lower()}.json"
    if p.exists():
        return p
    for f in trends_dir.glob("*.json"):
        if f.stem.lower() == intervention_name.lower():
            return f
    return None
