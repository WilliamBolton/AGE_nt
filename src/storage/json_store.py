"""JSON file storage — one file per intervention.

Primary human-readable store. Each intervention gets its own JSON file
in data/documents/{intervention}.json with the full typed document list.
Classification fields are stored separately in data/classifications/.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from loguru import logger

from src.config import settings
from src.schema.document import Document, DocumentListAdapter


class JsonStore:
    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or settings.documents_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.classifications_dir = self.base_dir.parent / "classifications"
        self.classifications_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, intervention: str) -> Path:
        return self.base_dir / f"{intervention.lower()}.json"

    def load_documents(self, intervention: str) -> list[Document]:
        """Load all documents for an intervention. Returns empty list if no file."""
        path = self._path(intervention)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text())
            return DocumentListAdapter.validate_python(data.get("documents", []))
        except Exception as e:
            logger.error(f"Failed to load {path}: {e}")
            return []

    def save_documents(
        self,
        intervention: str,
        docs: list[Document],
        aliases: list[str] | None = None,
    ) -> None:
        """Write full document list for an intervention (overwrites)."""
        path = self._path(intervention)
        envelope = {
            "intervention": intervention,
            "aliases": aliases or [],
            "last_updated": date.today().isoformat(),
            "document_count": len(docs),
            "documents": json.loads(DocumentListAdapter.dump_json(docs)),
        }
        path.write_text(json.dumps(envelope, indent=2, default=str))
        logger.info(f"Saved {len(docs)} documents to {path}")

    def append_documents(
        self,
        intervention: str,
        new_docs: list[Document],
        aliases: list[str] | None = None,
    ) -> int:
        """Append new documents, deduplicating by source_url. Returns count of new docs added."""
        existing = self.load_documents(intervention)
        existing_urls = {d.source_url for d in existing}
        added = [d for d in new_docs if d.source_url not in existing_urls]
        if not added:
            logger.info(f"No new documents to add for '{intervention}'")
            return 0
        all_docs = existing + added
        self.save_documents(intervention, all_docs, aliases)
        return len(added)

    def document_exists(self, intervention: str, source_url: str) -> bool:
        """Check if a document with this source_url already exists."""
        docs = self.load_documents(intervention)
        return any(d.source_url == source_url for d in docs)

    def list_interventions(self) -> list[str]:
        """List all interventions that have stored documents."""
        return [p.stem for p in self.base_dir.glob("*.json")]

    def count_documents(self, intervention: str) -> int:
        """Count documents for an intervention."""
        return len(self.load_documents(intervention))

    # ── Classifications (separate file per intervention) ─────────────────────

    def _classifications_path(self, intervention: str) -> Path:
        return self.classifications_dir / f"{intervention.lower()}.json"

    def save_classifications_skeleton(self, intervention: str, doc_ids: list[str]) -> None:
        """Create or update classifications skeleton with all document IDs.

        Preserves existing classification data for already-classified docs.
        Adds empty entries for new doc IDs.
        """
        path = self._classifications_path(intervention)
        if path.exists():
            try:
                existing = json.loads(path.read_text())
                existing_docs = existing.get("documents", {})
            except Exception:
                existing_docs = {}
        else:
            existing_docs = {}

        # Merge: keep existing classifications, add empty entries for new docs
        for doc_id in doc_ids:
            if doc_id not in existing_docs:
                existing_docs[doc_id] = {}

        skeleton = {
            "intervention": intervention,
            "model_version": None,
            "classified_at": None,
            "documents": existing_docs,
        }
        path.write_text(json.dumps(skeleton, indent=2))
        logger.info(f"Classifications skeleton: {len(existing_docs)} entries in {path}")

    def load_classifications(self, intervention: str) -> dict:
        """Load classifications for an intervention."""
        path = self._classifications_path(intervention)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text())
        except Exception as e:
            logger.error(f"Failed to load classifications from {path}: {e}")
            return {}

    def save_classifications(self, intervention: str, data: dict) -> None:
        """Write full classifications data for an intervention."""
        path = self._classifications_path(intervention)
        path.write_text(json.dumps(data, indent=2, default=str))
        logger.info(f"Saved classifications to {path}")
