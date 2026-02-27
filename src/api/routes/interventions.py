"""Data endpoints for interventions and documents.

Full implementation: list interventions, query documents, stats,
timeline, trends, and text search.
"""

from __future__ import annotations

import json
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.dependencies import get_storage
from src.ingest.google_trends import load_trends
from src.storage.manager import StorageManager

router = APIRouter(prefix="/interventions", tags=["interventions"])


@router.get("")
async def list_interventions(
    storage: StorageManager = Depends(get_storage),
) -> dict:
    """List all interventions that have stored documents."""
    interventions = await storage.get_interventions()
    result = []
    for name in interventions:
        count = await storage.count_documents(name)
        result.append({"name": name, "document_count": count})
    return {"interventions": result, "total": len(result)}


@router.get("/{name}/documents")
async def get_documents(
    name: str,
    source_type: str | None = Query(None, description="Filter by source type (e.g. pubmed, clinicaltrials)"),
    evidence_level: str | None = Query(None, description="Comma-separated evidence levels (e.g. 1,2,3)"),
    organism: str | None = Query(None, description="Filter by organism (e.g. human, mouse)"),
    date_from: str | None = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: str | None = Query(None, description="End date (YYYY-MM-DD)"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    storage: StorageManager = Depends(get_storage),
) -> dict:
    """Get documents for an intervention with optional filters."""
    # Validate intervention exists
    interventions = await storage.get_interventions()
    if name.lower() not in interventions:
        raise HTTPException(status_code=404, detail=f"Intervention '{name}' not found")

    # Parse evidence levels
    evidence_levels = None
    if evidence_level:
        try:
            evidence_levels = [int(x.strip()) for x in evidence_level.split(",")]
        except ValueError:
            raise HTTPException(status_code=400, detail="evidence_level must be comma-separated integers")

    rows = await storage.query_documents(
        intervention=name.lower(),
        source_type=source_type,
        evidence_levels=evidence_levels,
        organism=organism,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )

    # Parse JSON fields back
    for row in rows:
        for key in ("source_metadata", "key_findings", "hallmarks_addressed", "endpoints", "raw_response"):
            if key in row and isinstance(row[key], str):
                try:
                    row[key] = json.loads(row[key])
                except (json.JSONDecodeError, TypeError):
                    pass

    total = await storage.count_documents(name.lower())
    return {
        "intervention": name.lower(),
        "documents": rows,
        "returned": len(rows),
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{name}/stats")
async def get_stats(
    name: str,
    storage: StorageManager = Depends(get_storage),
) -> dict:
    """Get aggregate statistics for an intervention."""
    interventions = await storage.get_interventions()
    if name.lower() not in interventions:
        raise HTTPException(status_code=404, detail=f"Intervention '{name}' not found")

    docs = storage.get_documents(name.lower())
    total = len(docs)

    # Count by source type
    source_counts: Counter = Counter()
    for doc in docs:
        source_counts[doc.source_type.value] += 1

    # Date range
    dates = [doc.date_published for doc in docs]
    earliest = min(dates).isoformat() if dates else None
    latest = max(dates).isoformat() if dates else None

    return {
        "intervention": name.lower(),
        "total_documents": total,
        "by_source_type": dict(source_counts.most_common()),
        "date_range": {"earliest": earliest, "latest": latest},
    }


@router.get("/{name}/timeline")
async def get_timeline(
    name: str,
    storage: StorageManager = Depends(get_storage),
) -> dict:
    """Temporal aggregation: documents per year, grouped by source type and evidence level."""
    interventions = await storage.get_interventions()
    if name.lower() not in interventions:
        raise HTTPException(status_code=404, detail=f"Intervention '{name}' not found")

    # Evidence level timeline from SQLite
    timeline = await storage.get_timeline(name.lower())

    # Also build a source-type timeline from the JSON docs
    docs = storage.get_documents(name.lower())
    source_timeline: dict[str, dict[str, int]] = {}
    for doc in docs:
        year = str(doc.date_published.year)
        if year not in source_timeline:
            source_timeline[year] = {}
        st = doc.source_type.value
        source_timeline[year][st] = source_timeline[year].get(st, 0) + 1

    return {
        "intervention": name.lower(),
        "by_evidence_level": timeline,
        "by_source_type": source_timeline,
    }


@router.get("/{name}/trends")
async def get_trends(
    name: str,
) -> dict:
    """Get Google Trends interest-over-time data for an intervention."""
    trends = load_trends(name.lower())
    if not trends:
        raise HTTPException(status_code=404, detail=f"No trends data for '{name}'")

    return {
        "intervention": name.lower(),
        "fetched_at": trends.fetched_at.isoformat(),
        "timeframe": trends.timeframe,
        "peak_interest": trends.peak_interest,
        "peak_date": trends.peak_date,
        "current_interest": trends.current_interest,
        "data_points": trends.data_points,
        "related_queries": trends.related_queries,
    }


@router.post("/search")
async def search_documents(
    query: str = Query(..., description="Search text"),
    intervention: str | None = Query(None, description="Limit to specific intervention"),
    source_type: str | None = Query(None, description="Filter by source type"),
    limit: int = Query(50, ge=1, le=500),
    storage: StorageManager = Depends(get_storage),
) -> dict:
    """Text search across document titles and abstracts.

    Simple LIKE-based search (no semantic/vector search yet).
    """
    query_lower = query.lower()

    if intervention:
        interventions = await storage.get_interventions()
        if intervention.lower() not in interventions:
            raise HTTPException(status_code=404, detail=f"Intervention '{intervention}' not found")
        docs = storage.get_documents(intervention.lower())
    else:
        # Search all interventions
        all_interventions = await storage.get_interventions()
        docs = []
        for name in all_interventions:
            docs.extend(storage.get_documents(name))

    # Filter by source type
    if source_type:
        docs = [d for d in docs if d.source_type.value == source_type]

    # Simple text search: title + abstract
    matches = []
    for doc in docs:
        text = f"{doc.title} {doc.abstract}".lower()
        if query_lower in text:
            matches.append({
                "id": doc.id,
                "source_type": doc.source_type.value,
                "intervention": doc.intervention,
                "title": doc.title,
                "abstract": doc.abstract[:300] + "..." if len(doc.abstract) > 300 else doc.abstract,
                "source_url": doc.source_url,
                "date_published": doc.date_published.isoformat(),
            })
            if len(matches) >= limit:
                break

    return {
        "query": query,
        "results": matches,
        "returned": len(matches),
    }
