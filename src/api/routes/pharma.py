"""Pharma and biotech profile endpoints + DD analysis.

Serves profiles from data/pharma_profiles/ and data/biotech_profiles/.
DD analysis endpoint runs the orchestrator or returns cached results.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException
from loguru import logger

from src.api.dependencies import get_storage
from src.config import PROJECT_ROOT, settings
from src.storage.manager import StorageManager

router = APIRouter(tags=["pharma"])

PHARMA_DIR = PROJECT_ROOT / "data" / "pharma_profiles"
BIOTECH_DIR = PROJECT_ROOT / "data" / "biotech_profiles"
DD_CACHE_DIR = PROJECT_ROOT / "data" / "analysis" / "pharma_dd"


def _slug(name: str) -> str:
    """Convert company name to filename slug."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _list_profiles(directory: Path) -> list[dict]:
    """List all profile JSONs in a directory."""
    if not directory.exists():
        return []
    profiles = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text())
            profiles.append({
                "slug": path.stem,
                "company": data.get("company", path.stem),
                "aging_relevance": data.get("aging_relevance", "unknown"),
                "aging_signal_strength": data.get("aging_signal_strength"),
                "stage": data.get("stage"),
            })
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to read profile {path}: {e}")
    return profiles


def _load_profile(directory: Path, company: str) -> dict:
    """Load a single profile by company name or slug."""
    # Try exact slug match first
    slug = _slug(company)
    path = directory / f"{slug}.json"
    if path.exists():
        return json.loads(path.read_text())

    # Try scanning all files for company name match
    if directory.exists():
        for p in directory.glob("*.json"):
            try:
                data = json.loads(p.read_text())
                if data.get("company", "").lower() == company.lower():
                    return data
            except (json.JSONDecodeError, OSError):
                continue

    raise HTTPException(
        status_code=404,
        detail=f"Profile not found for '{company}'. Available: {[p.stem for p in directory.glob('*.json')]}",
    )


# ── Pharma profiles ─────────────────────────────────────────────────────────

@router.get("/pharma/profiles")
async def list_pharma_profiles() -> dict:
    """List all pharma companies with profiles."""
    profiles = _list_profiles(PHARMA_DIR)
    return {"profiles": profiles, "count": len(profiles)}


@router.get("/pharma/profiles/{company}")
async def get_pharma_profile(company: str) -> dict:
    """Get a pharma company profile."""
    return _load_profile(PHARMA_DIR, company)


# ── Biotech profiles ────────────────────────────────────────────────────────

@router.get("/biotech/profiles")
async def list_biotech_profiles() -> dict:
    """List all biotech companies with profiles."""
    profiles = _list_profiles(BIOTECH_DIR)
    return {"profiles": profiles, "count": len(profiles)}


@router.get("/biotech/profiles/{company}")
async def get_biotech_profile(company: str) -> dict:
    """Get a biotech company profile."""
    return _load_profile(BIOTECH_DIR, company)


# ── Pharma DD analysis ──────────────────────────────────────────────────────

@router.post("/pharma/dd/{pharma_name}")
async def run_pharma_dd(
    pharma_name: str,
    x_gemini_key: str | None = Header(None),
    storage: StorageManager = Depends(get_storage),
) -> dict:
    """Run pharma due diligence analysis.

    Returns cached result if available. Otherwise runs the DD orchestrator
    which requires a Gemini API key for narrative generation.
    """
    slug = _slug(pharma_name)
    cache_path = DD_CACHE_DIR / f"{slug}.json"

    # Return cached if available
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    # Need Gemini key for fresh analysis — try header first, fall back to .env
    gemini_key = x_gemini_key or settings.gemini_api_key
    if not gemini_key:
        raise HTTPException(
            status_code=401,
            detail="Gemini API key required for fresh DD analysis. Set it in Settings or GEMINI_API_KEY in .env.",
        )

    # Run orchestrator
    try:
        from src.reasoning.pharma_dd import analyse_acquisition_landscape

        result = await analyse_acquisition_landscape(
            pharma_name=pharma_name,
            storage=storage,
            gemini_key=gemini_key,
        )
        result_dict = result.model_dump() if hasattr(result, "model_dump") else result
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail="Pharma DD orchestrator not yet implemented.",
        )
    except Exception as e:
        logger.error(f"Pharma DD failed for {pharma_name}: {e}")
        raise HTTPException(status_code=500, detail=f"DD analysis failed: {e}")

    # Cache the result
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(result_dict, indent=2, default=str))
    logger.info(f"Cached pharma DD: {cache_path}")

    return result_dict
