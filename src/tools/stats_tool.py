"""Summary statistics and document search tools.

Centralises the stats/list/search helpers that were previously inlined
in the chat and agent_chat execute functions. get_stats() follows the
standard discover_tools() signature; the async helpers are used directly
by the execute dispatchers.
"""

from __future__ import annotations

from src.stats.summary import generate_summary
from src.storage.manager import StorageManager


def get_stats(intervention: str, storage: StorageManager) -> dict:
    """Get summary statistics for an intervention.

    Follows the discover_tools() convention: (intervention, storage) -> dict.
    Wraps generate_summary() which reads from data/documents/ and writes
    to data/summary/.
    """
    return generate_summary(intervention.lower())


async def list_all_interventions(storage: StorageManager) -> dict:
    """List all interventions with document counts."""
    interventions = await storage.get_interventions()
    result = []
    for name in interventions:
        count = await storage.count_documents(name)
        result.append({"name": name, "document_count": count})
    return {"interventions": result, "total": len(result)}


async def search_all_documents(
    query: str,
    storage: StorageManager,
    intervention: str | None = None,
    limit: int = 20,
) -> dict:
    """Search documents by text query across one or all interventions."""
    if intervention:
        docs = storage.get_documents(intervention.lower())
    else:
        docs = []
        all_interventions = await storage.get_interventions()
        for name in all_interventions:
            docs.extend(storage.get_documents(name))

    matches = []
    query_lower = query.lower()
    for doc in docs:
        text = f"{doc.title} {doc.abstract}".lower()
        if query_lower in text:
            matches.append({
                "title": doc.title,
                "source_type": doc.source_type.value,
                "intervention": doc.intervention,
                "date_published": doc.date_published.isoformat(),
            })
            if len(matches) >= limit:
                break
    return {"query": query, "results": matches, "count": len(matches)}
