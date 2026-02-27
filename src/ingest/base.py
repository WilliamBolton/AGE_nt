"""Abstract base class for all ingest agents.

Ingest agents are fast and dumb — they hit APIs, parse responses into typed
Pydantic models, and store. No LLM calls at ingest time.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from loguru import logger

from src.ingest.query_expander import QueryExpansion
from src.schema.document import Document
from src.storage.manager import StorageManager


class BaseIngestAgent(ABC):
    """Abstract base class for source-specific ingest agents."""

    def __init__(self, storage: StorageManager):
        self.storage = storage

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Human-readable source name for logging."""
        ...

    @abstractmethod
    async def ingest(
        self,
        intervention: str,
        aliases: list[str] | None = None,
        query_expansion: QueryExpansion | None = None,
        max_results: int = 50,
    ) -> list[Document]:
        """Ingest documents for a given intervention.

        Steps:
        1. Build query from expansion or aliases
        2. Query the external source API
        3. Parse responses into typed Document models
        4. Check for duplicates
        5. Return list of new documents (caller handles storage)
        """
        ...

    def _get_query(
        self,
        query_key: str,
        intervention: str,
        aliases: list[str] | None,
        query_expansion: QueryExpansion | None,
    ) -> str:
        """Get the appropriate query string for this source.

        Uses query_expansion.queries[query_key] if available,
        otherwise falls back to building from intervention + aliases.
        """
        if query_expansion and query_key in query_expansion.queries:
            return query_expansion.queries[query_key]

        # Fallback
        terms = [intervention] + (aliases or [])
        if query_key == "pubmed":
            joined = " OR ".join(f'"{t}"' for t in terms)
            return f"({joined}) AND (aging OR ageing OR lifespan OR longevity OR senescence)"
        elif query_key == "clinical_trials":
            return " OR ".join(terms)
        elif query_key == "general":
            return f"{intervention} aging longevity research evidence"
        elif query_key == "preprint":
            return f"{intervention} aging longevity"
        else:
            return intervention

    def _all_terms(
        self,
        intervention: str,
        aliases: list[str] | None,
        query_expansion: QueryExpansion | None,
    ) -> list[str]:
        """Get all search terms (primary + synonyms + aliases)."""
        terms = {intervention.lower()}
        if aliases:
            terms.update(a.lower() for a in aliases)
        if query_expansion:
            terms.update(s.lower() for s in query_expansion.synonyms)
            terms.update(a.lower() for a in query_expansion.analogs)
        return list(terms)
