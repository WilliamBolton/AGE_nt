"""Unified storage manager — facade over JSON + SQLite.

All reasoning modules and API routes use this. Nothing else touches
files or the database directly.
"""

from __future__ import annotations

from loguru import logger

from src.schema.document import Document
from src.storage.json_store import JsonStore
from src.storage.sqlite_store import SQLiteStore


class StorageManager:
    def __init__(
        self,
        json_store: JsonStore | None = None,
        sqlite_store: SQLiteStore | None = None,
    ):
        self.json = json_store or JsonStore()
        self.sqlite = sqlite_store or SQLiteStore()

    async def initialize(self) -> None:
        """Initialize both stores."""
        await self.sqlite.initialize()
        logger.info("Storage manager initialized")

    async def close(self) -> None:
        await self.sqlite.close()

    async def save_documents(
        self,
        intervention: str,
        docs: list[Document],
        aliases: list[str] | None = None,
        category: str | None = None,
        subcategory: str | None = None,
    ) -> int:
        """Append new documents to both stores. Returns count of new docs added."""
        if not docs:
            return 0
        # JSON store handles dedup internally via append_documents
        added = self.json.append_documents(
            intervention, docs, aliases, category=category, subcategory=subcategory,
        )
        # SQLite: insert all (INSERT OR REPLACE handles dedup by id)
        await self.sqlite.insert_documents(docs, category=category, subcategory=subcategory)
        # Create/update classifications skeleton for new docs
        all_docs = self.json.load_documents(intervention)
        self.json.save_classifications_skeleton(intervention, [d.id for d in all_docs])
        logger.info(f"Stored {added} new documents for '{intervention}'")
        return added

    def get_documents(self, intervention: str) -> list[Document]:
        """Load all documents for an intervention from JSON store."""
        return self.json.load_documents(intervention)

    async def query_documents(
        self,
        intervention: str | None = None,
        source_type: str | None = None,
        evidence_levels: list[int] | None = None,
        organism: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """Filtered query via SQLite. Returns raw dicts."""
        return await self.sqlite.query_documents(
            intervention=intervention,
            source_type=source_type,
            evidence_levels=evidence_levels,
            organism=organism,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )

    def document_exists(self, intervention: str, source_url: str) -> bool:
        """Fast dedup check via JSON store."""
        return self.json.document_exists(intervention, source_url)

    async def get_interventions(self) -> list[str]:
        return self.json.list_interventions()

    async def count_documents(self, intervention: str | None = None) -> int:
        if intervention:
            return self.json.count_documents(intervention)
        return await self.sqlite.count_documents()

    async def get_timeline(self, intervention: str) -> dict:
        return await self.sqlite.get_timeline(intervention)

    async def update_classifications(self, doc_id: str, classifications: dict) -> None:
        await self.sqlite.update_classifications(doc_id, classifications)
