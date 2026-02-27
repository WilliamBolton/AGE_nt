"""Reasoning module endpoints — stubs with correct response shapes.

These return placeholder responses until reasoning modules are implemented.
Each returns the correct shape so frontends can build against these now.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from src.api.dependencies import get_storage
from src.storage.manager import StorageManager

router = APIRouter(prefix="/interventions", tags=["reasoning"])


@router.get("/{name}/evidence")
async def get_evidence_grade(
    name: str,
    storage: StorageManager = Depends(get_storage),
) -> dict:
    """Evidence grading: distribution of studies across evidence levels.

    TODO: Implement in src/reasoning/evidence_grader.py
    """
    interventions = await storage.get_interventions()
    if name.lower() not in interventions:
        raise HTTPException(status_code=404, detail=f"Intervention '{name}' not found")

    total = await storage.count_documents(name.lower())
    return {
        "intervention": name.lower(),
        "status": "stub",
        "message": "Evidence grading not yet implemented. Use /interventions/{name}/stats for basic counts.",
        "total_documents": total,
        "evidence_distribution": {},
        "composite_score": None,
        "confidence": None,
    }


@router.get("/{name}/trajectory")
async def get_trajectory(
    name: str,
    storage: StorageManager = Depends(get_storage),
) -> dict:
    """Trajectory scoring: research momentum over time.

    TODO: Implement in src/reasoning/trajectory.py
    """
    interventions = await storage.get_interventions()
    if name.lower() not in interventions:
        raise HTTPException(status_code=404, detail=f"Intervention '{name}' not found")

    return {
        "intervention": name.lower(),
        "status": "stub",
        "message": "Trajectory scoring not yet implemented. Use /interventions/{name}/timeline for raw temporal data.",
        "momentum_score": None,
        "phase": None,
        "trend_direction": None,
    }


@router.get("/{name}/gaps")
async def get_gaps(
    name: str,
    storage: StorageManager = Depends(get_storage),
) -> dict:
    """Gap analysis: missing evidence types.

    TODO: Implement in src/reasoning/gap_spotter.py
    """
    interventions = await storage.get_interventions()
    if name.lower() not in interventions:
        raise HTTPException(status_code=404, detail=f"Intervention '{name}' not found")

    return {
        "intervention": name.lower(),
        "status": "stub",
        "message": "Gap analysis not yet implemented.",
        "gaps": [],
        "completeness_score": None,
    }


@router.get("/{name}/hype")
async def get_hype_ratio(
    name: str,
    storage: StorageManager = Depends(get_storage),
) -> dict:
    """Hype ratio: evidence vs media/social buzz.

    TODO: Implement in src/reasoning/hype_ratio.py
    """
    interventions = await storage.get_interventions()
    if name.lower() not in interventions:
        raise HTTPException(status_code=404, detail=f"Intervention '{name}' not found")

    return {
        "intervention": name.lower(),
        "status": "stub",
        "message": "Hype ratio not yet implemented. Use /interventions/{name}/trends for raw Google Trends data.",
        "hype_ratio": None,
        "evidence_score": None,
        "media_score": None,
    }


@router.post("/{name}/report")
async def generate_report(
    name: str,
    storage: StorageManager = Depends(get_storage),
) -> dict:
    """Full reasoning pipeline: generate a comprehensive report.

    TODO: Implement in src/reasoning/report_generator.py
    """
    interventions = await storage.get_interventions()
    if name.lower() not in interventions:
        raise HTTPException(status_code=404, detail=f"Intervention '{name}' not found")

    total = await storage.count_documents(name.lower())
    return {
        "intervention": name.lower(),
        "status": "stub",
        "message": "Report generation not yet implemented.",
        "total_documents_analysed": total,
        "sections": {
            "evidence_grade": None,
            "trajectory": None,
            "gaps": None,
            "hype_ratio": None,
        },
        "overall_confidence": None,
        "summary": None,
    }


@router.post("/{name}/classify")
async def trigger_classification(
    name: str,
    storage: StorageManager = Depends(get_storage),
) -> dict:
    """Trigger LLM classification of unclassified documents.

    TODO: Implement in src/classify/llm_classifier.py
    """
    interventions = await storage.get_interventions()
    if name.lower() not in interventions:
        raise HTTPException(status_code=404, detail=f"Intervention '{name}' not found")

    total = await storage.count_documents(name.lower())
    return {
        "intervention": name.lower(),
        "status": "stub",
        "message": "LLM classification not yet implemented.",
        "total_documents": total,
        "classified": 0,
        "unclassified": total,
    }
