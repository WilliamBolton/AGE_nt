"""Full evidence report generator.

Assembles outputs from all available reasoning tools into a single
structured report for an intervention.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from loguru import logger

from src.storage.manager import StorageManager


def generate_full_report(intervention: str, storage: StorageManager) -> dict[str, Any]:
    """Generate a full evidence report by running all available tools.

    Discovers and runs each tool, assembles results into a single dict.
    Tolerates missing tools — includes whatever is available.

    Args:
        intervention: Canonical intervention name.
        storage: StorageManager instance.

    Returns:
        Dict with sections from each tool plus summary metadata.
    """
    name = intervention.lower()
    sections: dict[str, Any] = {}

    # Evidence grader
    try:
        from src.tools.evidence_grader import _deterministic_rubric_score
        docs = storage.get_documents(name)
        doc_dicts = [d.model_dump() if hasattr(d, "model_dump") else d for d in docs]
        sections["evidence_grade"] = _deterministic_rubric_score(fetched_documents=doc_dicts)
    except Exception as e:
        logger.debug(f"Evidence grader skipped: {e}")

    # Trajectory
    try:
        from src.tools.trajectory import score_trajectory
        result = score_trajectory(name, storage)
        sections["trajectory"] = result.model_dump() if hasattr(result, "model_dump") else result
    except Exception as e:
        logger.debug(f"Trajectory skipped: {e}")

    # Gap analysis
    try:
        from src.tools.gap_analysis import _deterministic_gap_analysis
        docs = storage.get_documents(name)
        doc_dicts = [d.model_dump() if hasattr(d, "model_dump") else d for d in docs]
        sections["gaps"] = _deterministic_gap_analysis(fetched_documents=doc_dicts)
    except Exception as e:
        logger.debug(f"Gap analysis skipped: {e}")

    # Hype ratio
    try:
        from src.tools.hype_ratio import _deterministic_hype_ratio
        docs = storage.get_documents(name)
        doc_dicts = [d.model_dump() if hasattr(d, "model_dump") else d for d in docs]
        sections["hype_ratio"] = _deterministic_hype_ratio(doc_dicts)
    except Exception as e:
        logger.debug(f"Hype ratio skipped: {e}")

    # Bryan Johnson
    try:
        from src.tools.bryan_johnson import get_bryan_johnson_take
        sections["bryan_johnson"] = get_bryan_johnson_take(name)
    except Exception as e:
        logger.debug(f"Bryan Johnson skipped: {e}")

    # Summary metadata
    doc_count = len(storage.get_documents(name))
    confidence = sections.get("evidence_grade", {}).get("confidence")
    momentum = sections.get("trajectory", {}).get("momentum_score")

    return {
        "intervention": name,
        "report_date": date.today().isoformat(),
        "total_documents": doc_count,
        "tools_run": list(sections.keys()),
        "tools_available": len(sections),
        "overall_confidence": confidence,
        "momentum_score": momentum,
        "sections": sections,
    }
