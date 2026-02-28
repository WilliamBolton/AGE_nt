"""
Tools for the Judge agent: bundle Researcher Classifier, Gap Analyst, and Social Media Expert
outputs into a single evaluation package for critical quality assessment.
"""

from __future__ import annotations

import json
from typing import Any


def prepare_evaluation_package(
    researcher_classifier_output: dict[str, Any] | str,
    gap_analyst_output: dict[str, Any] | str,
    social_media_expert_output: dict[str, Any] | str,
) -> str:
    """
    Format the three agent outputs into one structured text block for the Judge LLM.
    The Judge must use ONLY this information to produce a critical quality report.
    """
    def _to_text(x: dict[str, Any] | str) -> str:
        if isinstance(x, str):
            return x
        try:
            return json.dumps(x, indent=2, ensure_ascii=False)
        except Exception:
            return str(x)

    sections = [
        "=== RESEARCHER CLASSIFIER OUTPUT ===\n" + _to_text(researcher_classifier_output),
        "=== GAP ANALYST OUTPUT ===\n" + _to_text(gap_analyst_output),
        "=== SOCIAL MEDIA EXPERT OUTPUT ===\n" + _to_text(social_media_expert_output),
    ]
    return "\n\n".join(sections)
