"""Bryan Johnson stance lookup tool.

Loads data from data/bryan_johnson.json and returns his stance,
quotes, and protocol status for a given intervention.
"""

from __future__ import annotations

import json
from typing import Any

from src.config import PROJECT_ROOT

_DATA: dict | None = None


def _load_data() -> dict:
    global _DATA
    if _DATA is None:
        path = PROJECT_ROOT / "data" / "bryan_johnson.json"
        if path.exists():
            _DATA = json.loads(path.read_text())
        else:
            _DATA = {"interventions": {}}
    return _DATA


def get_bryan_johnson_take(intervention: str) -> dict[str, Any]:
    """Get Bryan Johnson's take on an aging intervention.

    Returns his stance, quotes with sources, and protocol status.
    Does not require StorageManager — reads from static JSON.

    Args:
        intervention: Name of the intervention (e.g. 'rapamycin')

    Returns:
        Dict with intervention, bryan_johnson data, and source info.
    """
    data = _load_data()
    interventions_data = data.get("interventions", {})
    name = intervention.lower().strip()

    # Direct match
    if name in interventions_data:
        return {
            "intervention": name,
            "bryan_johnson": interventions_data[name],
            "source": "Blueprint protocol — synthesised from public posts and podcasts",
        }

    # Fuzzy substring match
    for key, entry in interventions_data.items():
        if name in key or key in name:
            return {
                "intervention": name,
                "matched_as": key,
                "bryan_johnson": entry,
                "source": "Blueprint protocol — synthesised from public posts and podcasts",
            }

    # Not found
    return {
        "intervention": name,
        "bryan_johnson": None,
        "message": f"No Bryan Johnson take found for '{name}'.",
        "available_interventions": sorted(interventions_data.keys()),
    }
