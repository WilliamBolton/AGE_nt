"""Stub and lightweight implementations for reasoning/classify until full modules exist.

These adapters let the LangGraph pipeline run end-to-end. Replace with
src.reasoning.* and src.classify.llm_classifier when available.
"""

from __future__ import annotations

from collections import Counter

from src.schema.document import Document, SourceType


# ── Evidence grading (stub) ───────────────────────────────────────────────────

def evidence_grade_stub(documents: list[Document]) -> dict:
    """Compute a simple evidence summary without LLM classification.

    Uses source_type and publication_types as proxies for evidence level
    until full classification is available.
    """
    if not documents:
        return {
            "total": 0,
            "by_source": {},
            "by_level_proxy": {},
            "confidence_score": 0.0,
            "reasoning": "No documents to grade.",
        }

    by_source = Counter(d.source_type.value for d in documents)
    level_proxy: Counter[int] = Counter()

    for d in documents:
        # Clinical trials → level 2 (RCT) or 3 (observational) proxy
        if d.source_type == SourceType.CLINICAL_TRIALS:
            level_proxy[2] += 1
        elif d.source_type == SourceType.PUBMED:
            # Use publication_types if available (PubMedDocument)
            pub_types = getattr(d, "publication_types", []) or []
            pub_lower = [p.lower() for p in pub_types]
            if any(x in pub_lower for x in ("meta-analysis", "systematic review")):
                level_proxy[1] += 1
            elif any(x in pub_lower for x in ("randomized controlled trial", "clinical trial")):
                level_proxy[2] += 1
            elif any(x in pub_lower for x in ("observational", "cohort", "comparative")):
                level_proxy[3] += 1
            elif "review" in pub_lower or "journal article" in pub_lower:
                level_proxy[3] += 1
            else:
                level_proxy[4] += 1  # Default to animal/preclinical proxy
        else:
            level_proxy[4] += 1  # Other sources as lower level proxy

    # Simple confidence: weight by level (1=highest), normalize to 0–100
    weights = {1: 6, 2: 5, 3: 4, 4: 3, 5: 2, 6: 1}
    total_weight = sum(level_proxy.get(l, 0) * weights.get(l, 1) for l in range(1, 7))
    max_weight = len(documents) * 6
    confidence = (total_weight / max_weight * 100.0) if max_weight else 0.0
    confidence = min(100.0, round(confidence, 1))

    return {
        "total": len(documents),
        "by_source": dict(by_source),
        "by_level_proxy": dict(level_proxy),
        "confidence_score": confidence,
        "reasoning": (
            f"Graded {len(documents)} documents from {len(by_source)} sources. "
            "Evidence level is inferred from source type and publication type until "
            "full LLM classification is available."
        ),
    }


# ── Trajectory (stub) ─────────────────────────────────────────────────────────

def trajectory_stub(documents: list[Document], timeline: dict | None) -> dict:
    """Summarise temporal distribution of evidence. Stub until reasoning.trajectory exists."""
    if not documents:
        return {
            "phase": "unknown",
            "reasoning": "No documents.",
        }

    years = [d.date_published.year for d in documents if d.date_published]
    if not years:
        return {"phase": "unknown", "reasoning": "No publication dates."}

    min_y, max_y = min(years), max(years)
    recent = [y for y in years if y >= max_y - 2]
    older = [y for y in years if y < max_y - 2]
    recent_rate = len(recent) / 2.0 if recent else 0
    older_rate = len(older) / max(1, (max_y - min_y)) if older else 0
    accelerating = recent_rate >= older_rate * 0.8

    return {
        "phase": "accelerating" if accelerating else "stable",
        "year_range": f"{min_y}–{max_y}",
        "recent_publications": len(recent),
        "reasoning": (
            f"Publication span {min_y}–{max_y}; {len(recent)} in last 2 years. "
            "Full trajectory scoring will use get_timeline() when reasoning.trajectory is implemented."
        ),
    }


# ── Gap spotting (stub) ───────────────────────────────────────────────────────

def gaps_stub(documents: list[Document], evidence_summary: dict) -> dict:
    """Identify evidence gaps. Stub until reasoning.gap_spotter exists."""
    gaps = []
    by_source = evidence_summary.get("by_source") or {}
    by_level = evidence_summary.get("by_level_proxy") or {}

    if not documents:
        return {"missing": ["No evidence retrieved"], "warnings": []}

    if not by_source.get("pubmed") and not by_source.get("clinicaltrials"):
        gaps.append("No peer-reviewed literature or clinical trials in this run.")

    if not by_level.get(1) and not by_level.get(2):
        gaps.append("No systematic reviews or RCTs identified (classification may be pending).")

    if not by_source.get("clinicaltrials"):
        gaps.append("No clinical trial registrations found.")

    return {
        "missing": gaps or ["None identified with current stub"],
        "warnings": ["Evidence levels are inferred; run full classification for accurate grading."],
    }
