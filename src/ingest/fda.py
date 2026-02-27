"""FDA / DailyMed ingest agent — regulatory approval data.

Fetches structured product labels (SPLs) from DailyMed and drug label data
from openFDA. Only returns results for FDA-approved drugs — will be empty for
things like "epigenetic reprogramming" and that's fine.

Value: "Rapamycin is already FDA-approved (for transplant rejection), meaning
the safety profile is well-characterized and the regulatory pathway for aging
indications is shorter than for a novel compound."
"""

from __future__ import annotations

from datetime import date

import httpx
from loguru import logger

from src.ingest.base import BaseIngestAgent
from src.ingest.query_expander import QueryExpansion
from src.schema.document import Document, RegulatoryDocument

DAILYMED_SEARCH = "https://dailymed.nlm.nih.gov/dailymed/services/v2/spls.json"
DAILYMED_SPL = "https://dailymed.nlm.nih.gov/dailymed/services/v2/spls/{setid}.json"
OPENFDA_LABEL = "https://api.fda.gov/drug/label.json"


class FDAAgent(BaseIngestAgent):
    @property
    def source_name(self) -> str:
        return "FDA / DailyMed"

    async def ingest(
        self,
        intervention: str,
        aliases: list[str] | None = None,
        query_expansion: QueryExpansion | None = None,
        max_results: int = 10,
    ) -> list[Document]:
        terms = self._all_terms(intervention, aliases, query_expansion)

        docs: list[Document] = []

        # Try DailyMed first
        dailymed_docs = await self._search_dailymed(intervention, aliases, terms)
        docs.extend(dailymed_docs)

        # Supplement with openFDA
        openfda_docs = await self._search_openfda(intervention, aliases, terms)
        # Dedup against DailyMed results by title similarity
        existing_titles = {d.title.lower() for d in docs}
        for d in openfda_docs:
            if d.title.lower() not in existing_titles:
                docs.append(d)

        logger.info(f"FDA/DailyMed: {len(docs)} new documents for '{intervention}'")
        return docs[:max_results]

    async def _search_dailymed(
        self,
        intervention: str,
        aliases: list[str] | None,
        terms: list[str],
    ) -> list[Document]:
        """Search DailyMed for structured product labels."""
        docs: list[Document] = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            for term in terms[:5]:  # Try top 5 terms
                try:
                    resp = await client.get(
                        DAILYMED_SEARCH,
                        params={"drug_name": term, "pagesize": 10},
                    )
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                except Exception as e:
                    logger.debug(f"DailyMed search failed for '{term}': {e}")
                    continue

                spls = data.get("data", [])
                if not spls:
                    continue

                logger.info(f"DailyMed: found {len(spls)} SPLs for '{term}'")

                for spl in spls:
                    setid = spl.get("setid", "")
                    if not setid:
                        continue

                    source_url = f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={setid}"
                    if self.storage.document_exists(intervention, source_url):
                        continue

                    # Fetch full SPL details
                    try:
                        detail = await self._fetch_spl_detail(client, setid)
                    except Exception as e:
                        logger.debug(f"Failed to fetch SPL {setid}: {e}")
                        detail = {}

                    try:
                        doc = self._spl_to_document(spl, detail, intervention, aliases, source_url)
                        if doc:
                            docs.append(doc)
                    except Exception as e:
                        logger.warning(f"Failed to build RegulatoryDocument from SPL {setid}: {e}")

                # Don't search more terms if we already found results
                if docs:
                    break

        return docs

    async def _fetch_spl_detail(self, client: httpx.AsyncClient, setid: str) -> dict:
        """Fetch full SPL detail from DailyMed."""
        url = DAILYMED_SPL.format(setid=setid)
        resp = await client.get(url)
        if resp.status_code != 200:
            return {}
        return resp.json()

    @staticmethod
    def _spl_to_document(
        spl: dict,
        detail: dict,
        intervention: str,
        aliases: list[str] | None,
        source_url: str,
    ) -> RegulatoryDocument | None:
        """Convert a DailyMed SPL to RegulatoryDocument."""
        # Basic info from search result
        title = spl.get("title", "")
        setid = spl.get("setid", "")

        # Extract sections from detail
        sections = {}
        for section in (detail.get("data", {}).get("sections", []) if detail else []):
            name = (section.get("name") or "").upper()
            text = section.get("text", "")
            sections[name] = text

        # Also handle flat structure
        if not sections and detail:
            spl_data = detail.get("data", detail)
            if isinstance(spl_data, dict):
                for key in ("indications_and_usage", "warnings", "clinical_pharmacology"):
                    val = spl_data.get(key, "")
                    if val:
                        sections[key.upper().replace("_", " ")] = val

        # Extract fields from sections
        indications_text = (
            sections.get("INDICATIONS AND USAGE", "")
            or sections.get("INDICATIONS & USAGE", "")
            or sections.get("INDICATIONS", "")
        )
        warnings_text = sections.get("WARNINGS", "") or sections.get("WARNINGS AND PRECAUTIONS", "")
        pk_text = (
            sections.get("CLINICAL PHARMACOLOGY", "")
            or sections.get("PHARMACOKINETICS", "")
        )

        # Parse approved indications from the indications text
        approved_indications = []
        if indications_text:
            # Take first 500 chars as summary
            approved_indications = [_strip_html(indications_text)[:500]]

        # Drug class from SPL metadata
        drug_class = spl.get("product_type") or None

        # Approval date
        approval_date = None
        initial_approval = spl.get("published_date") or spl.get("effective_time")
        if initial_approval:
            approval_date = _parse_fda_date(initial_approval)

        # NDA number
        nda_number = spl.get("application_number") or None

        # Build abstract from indications
        abstract = _strip_html(indications_text)[:1000] if indications_text else title

        return RegulatoryDocument(
            intervention=intervention.lower(),
            intervention_aliases=aliases or [],
            title=title or f"FDA Label: {intervention}",
            abstract=abstract,
            source_url=source_url,
            date_published=approval_date or date.today(),
            approved_indications=approved_indications,
            approval_date=approval_date,
            drug_class=drug_class,
            warnings_summary=_strip_html(warnings_text)[:500] if warnings_text else None,
            pharmacokinetics_summary=_strip_html(pk_text)[:500] if pk_text else None,
            nda_number=nda_number,
            raw_response=spl,
        )

    async def _search_openfda(
        self,
        intervention: str,
        aliases: list[str] | None,
        terms: list[str],
    ) -> list[Document]:
        """Supplement with openFDA drug label search."""
        docs: list[Document] = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            for term in terms[:3]:
                search_query = f'openfda.generic_name:"{term}"'
                try:
                    resp = await client.get(
                        OPENFDA_LABEL,
                        params={"search": search_query, "limit": 5},
                    )
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                except Exception as e:
                    logger.debug(f"openFDA search failed for '{term}': {e}")
                    continue

                results = data.get("results", [])
                if not results:
                    continue

                logger.info(f"openFDA: found {len(results)} labels for '{term}'")

                for label in results:
                    try:
                        doc = self._openfda_to_document(label, intervention, aliases)
                        if doc and not self.storage.document_exists(intervention, doc.source_url):
                            docs.append(doc)
                    except Exception as e:
                        logger.warning(f"Failed to build RegulatoryDocument from openFDA: {e}")

                if docs:
                    break

        return docs

    @staticmethod
    def _openfda_to_document(
        label: dict,
        intervention: str,
        aliases: list[str] | None,
    ) -> RegulatoryDocument | None:
        """Convert an openFDA label result to RegulatoryDocument."""
        openfda = label.get("openfda", {})

        # Brand and generic names
        brand_names = openfda.get("brand_name", [])
        generic_names = openfda.get("generic_name", [])
        brand = brand_names[0] if brand_names else ""
        generic = generic_names[0] if generic_names else intervention

        title = f"{brand} ({generic})" if brand else generic
        if not title:
            return None

        # Source URL
        spl_id = openfda.get("spl_id", [""])[0] if openfda.get("spl_id") else ""
        if spl_id:
            source_url = f"https://api.fda.gov/drug/label.json?search=openfda.spl_id:{spl_id}"
        else:
            app_number = openfda.get("application_number", [""])[0] if openfda.get("application_number") else ""
            source_url = f"https://api.fda.gov/drug/label/{app_number or generic}"

        # Indications
        indications = label.get("indications_and_usage", [])
        indications_text = indications[0] if indications else ""
        approved_indications = [indications_text[:500]] if indications_text else []

        # Warnings
        warnings = label.get("warnings", []) or label.get("warnings_and_cautions", [])
        warnings_text = warnings[0][:500] if warnings else None

        # PK
        pk = label.get("clinical_pharmacology", [])
        pk_text = pk[0][:500] if pk else None

        # Drug class
        pharm_class = openfda.get("pharm_class_epc", [])
        drug_class = pharm_class[0] if pharm_class else None

        # Application number
        app_numbers = openfda.get("application_number", [])
        nda_number = app_numbers[0] if app_numbers else None

        # Abstract
        abstract = indications_text[:1000] if indications_text else title

        return RegulatoryDocument(
            intervention=intervention.lower(),
            intervention_aliases=aliases or [],
            title=title,
            abstract=abstract,
            source_url=source_url,
            date_published=date.today(),  # openFDA doesn't give approval date easily
            approved_indications=approved_indications,
            drug_class=drug_class,
            warnings_summary=warnings_text,
            pharmacokinetics_summary=pk_text,
            nda_number=nda_number,
            raw_response=label,
        )


def _parse_fda_date(date_str: str | None) -> date | None:
    """Parse FDA date formats (YYYYMMDD, YYYY-MM-DD, etc.)."""
    if not date_str:
        return None
    try:
        clean = date_str.strip().replace("-", "").replace("/", "")
        if len(clean) >= 8:
            return date(int(clean[:4]), int(clean[4:6]), int(clean[6:8]))
        elif len(clean) >= 4:
            return date(int(clean[:4]), 1, 1)
    except (ValueError, IndexError):
        pass
    return None


def _strip_html(text: str) -> str:
    """Strip basic HTML tags from text."""
    import re
    clean = re.sub(r"<[^>]+>", " ", text)
    clean = re.sub(r"\s+", " ", clean)
    return clean.strip()
