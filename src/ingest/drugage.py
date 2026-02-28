"""DrugAge database ingest agent.

Reads the DrugAge CSV (manually placed at data/drugage/drugage.csv)
and creates DrugAgeDocument records for matching interventions.

This is pre-structured Level 4 (animal) evidence. The lifespan_change_percent
field is quantitative data that reasoning modules can use directly.
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from loguru import logger

from src.config import settings
from src.ingest.base import BaseIngestAgent
from src.ingest.query_expander import QueryExpansion
from src.schema.document import Document, DrugAgeDocument

DRUGAGE_CSV_PATH = Path(settings.documents_dir).parent / "drugage" / "drugage.csv"


class DrugAgeAgent(BaseIngestAgent):
    @property
    def source_name(self) -> str:
        return "DrugAge"

    async def ingest(
        self,
        intervention: str,
        aliases: list[str] | None = None,
        query_expansion: QueryExpansion | None = None,
        max_results: int = 200,
    ) -> list[Document]:
        csv_path = DRUGAGE_CSV_PATH
        if not csv_path.exists():
            logger.warning(f"DrugAge CSV not found at {csv_path} — skipping")
            return []

        # Build set of terms to match (case-insensitive)
        match_terms = self._all_terms(intervention, aliases, query_expansion)
        match_terms_lower = {t.lower() for t in match_terms}

        logger.info(f"DrugAge: searching CSV for {match_terms_lower}")

        docs: list[Document] = []
        try:
            with open(csv_path, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    compound = (row.get("compound_name") or "").strip()
                    if not compound:
                        continue

                    # Match compound name against intervention terms
                    if compound.lower() not in match_terms_lower:
                        continue

                    if len(docs) >= max_results:
                        break

                    try:
                        doc = self._row_to_document(row, intervention, aliases)
                        if doc and not self.storage.document_exists(intervention, doc.source_url):
                            docs.append(doc)
                    except Exception as e:
                        logger.warning(f"Failed to parse DrugAge row: {e}")

        except Exception as e:
            logger.error(f"Failed to read DrugAge CSV: {e}")
            return []

        logger.info(f"DrugAge: {len(docs)} new documents for '{intervention}'")
        return docs

    @staticmethod
    def _row_to_document(
        row: dict,
        intervention: str,
        aliases: list[str] | None,
    ) -> DrugAgeDocument | None:
        """Convert a CSV row to a DrugAgeDocument."""
        compound = row.get("compound_name", "").strip()
        species = row.get("species", "").strip()
        strain = row.get("strain", "").strip() or None
        dosage = row.get("dosage", "").strip() or None
        dosage_unit = row.get("dosage_unit", "").strip() or None
        gender = row.get("gender", "").strip() or None
        significance = row.get("significance", "").strip() or None
        reference_pmid = row.get("pubmed_id", "").strip() or None

        # Parse lifespan change
        lifespan_str = row.get("avg_lifespan_change_percent", "").strip()
        lifespan_change: float | None = None
        if lifespan_str:
            try:
                lifespan_change = float(lifespan_str)
            except ValueError:
                pass

        # Build a descriptive title
        change_str = f"{lifespan_change:+.1f}%" if lifespan_change is not None else "unknown"
        title = f"DrugAge: {compound} in {species}"
        if strain:
            title += f" ({strain})"
        title += f" — {change_str} lifespan change"

        # Build abstract from structured data
        abstract_parts = [f"{compound} administered"]
        if dosage and dosage_unit:
            abstract_parts.append(f"at {dosage} {dosage_unit}")
        abstract_parts.append(f"to {species}")
        if strain:
            abstract_parts.append(f"({strain})")
        if gender:
            abstract_parts.append(f", {gender}")
        abstract_parts.append(".")
        if lifespan_change is not None:
            abstract_parts.append(f" Lifespan change: {lifespan_change:+.1f}%.")
        if significance:
            abstract_parts.append(f" Significance: {significance}.")
        if reference_pmid:
            abstract_parts.append(f" Reference: PMID {reference_pmid}.")
        abstract = " ".join(abstract_parts)

        # Source URL — link to DrugAge or PubMed reference
        if reference_pmid:
            source_url = f"https://pubmed.ncbi.nlm.nih.gov/{reference_pmid}/?drugage={compound}&species={species}"
        else:
            source_url = f"https://genomics.senescence.info/drugs/drug_details.php?compound={compound}&species={species}"

        # Add strain and dosage to make URL unique per row
        if strain:
            source_url += f"&strain={strain}"
        if dosage:
            source_url += f"&dosage={dosage}"

        # Date — try to infer from reference, default to a reasonable date
        pub_date = date(2020, 1, 1)  # DrugAge entries don't have a date field

        return DrugAgeDocument(
            intervention=intervention.lower(),
            intervention_aliases=aliases or [],
            title=title,
            abstract=abstract,
            source_url=source_url,
            date_published=pub_date,
            species=species,
            strain=strain,
            dosage=dosage,
            dosage_unit=dosage_unit,
            gender=gender,
            lifespan_change_percent=lifespan_change,
            significance=significance,
            reference_pmid=reference_pmid,
        )
