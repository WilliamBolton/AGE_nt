"""Google Patents ingest agent via Lens.org API.

Searches for patent filings related to an intervention and aging.
Patent activity is a commercial interest signal — many recent filings indicate
someone is investing in IP protection for this compound in aging applications.

Uses Lens.org patent search API (free tier: 50 requests/day, no auth for basic).
Falls back to a stub if the API is unavailable.
"""

from __future__ import annotations

from datetime import date

import httpx
from loguru import logger

from src.config import AGING_RELEVANCE_TERMS
from src.ingest.base import BaseIngestAgent
from src.ingest.query_expander import QueryExpansion
from src.schema.document import Document, PatentDocument

LENS_PATENT_SEARCH = "https://api.lens.org/patent/search"


def _score_patent(patent: dict) -> int:
    """Score a patent by aging relevance."""
    score = 0
    title = (patent.get("title") or "").lower()
    abstract = (patent.get("abstract") or "").lower()
    text = f"{title} {abstract}"

    if any(kw in text for kw in AGING_RELEVANCE_TERMS):
        score += 2

    # Granted patents are stronger signals
    status = (patent.get("legal_status") or "").lower()
    if "granted" in status or "active" in status:
        score += 1

    # Recency
    filing_date = patent.get("date_published") or patent.get("filing_date")
    if filing_date:
        try:
            parts = filing_date[:10].split("-")
            d = date(int(parts[0]), int(parts[1]), int(parts[2]))
            if (date.today() - d).days < 365 * 5:
                score += 1
        except (ValueError, IndexError):
            pass

    # Penalty: no aging terms
    if not any(kw in text for kw in AGING_RELEVANCE_TERMS):
        score -= 2

    return score


class PatentAgent(BaseIngestAgent):
    @property
    def source_name(self) -> str:
        return "Patents (Lens.org)"

    async def ingest(
        self,
        intervention: str,
        aliases: list[str] | None = None,
        query_expansion: QueryExpansion | None = None,
        max_results: int = 50,
    ) -> list[Document]:
        terms = self._all_terms(intervention, aliases, query_expansion)

        # Try Lens.org first
        docs = await self._try_lens(intervention, aliases, terms, max_results)
        if docs is not None:
            return docs

        # Fallback: try Google Patents scraping via simple HTTP
        docs = await self._try_google_patents(intervention, aliases, terms, max_results)
        if docs is not None:
            return docs

        logger.warning("Patents agent: no working patent API available, returning empty")
        return []

    async def _try_lens(
        self,
        intervention: str,
        aliases: list[str] | None,
        terms: list[str],
        max_results: int,
    ) -> list[Document] | None:
        """Try Lens.org patent search API."""
        # Build query: intervention terms AND aging context
        query_terms = " OR ".join(f'"{t}"' for t in terms[:5])
        aging_terms = "aging OR longevity OR senescence OR geroprotect OR lifespan"
        query = f"({query_terms}) AND ({aging_terms})"

        logger.info(f"Lens.org patent search: {query[:80]}...")

        payload = {
            "query": query,
            "size": min(max_results, 50),
            "sort": [{"relevance": "desc"}],
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.post(
                    LENS_PATENT_SEARCH,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code in (401, 403, 429):
                    logger.info(f"Lens.org returned {resp.status_code}, trying fallback")
                    return None
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPStatusError as e:
                logger.info(f"Lens.org HTTP error: {e}, trying fallback")
                return None
            except Exception as e:
                logger.info(f"Lens.org failed: {e}, trying fallback")
                return None

        results = data.get("data", [])
        total = data.get("total", 0)
        logger.info(f"Lens.org total patent results: {total}")

        if not results:
            return []

        # Score and rank
        for r in results:
            r["_score"] = _score_patent(r)
        results.sort(key=lambda r: r["_score"], reverse=True)

        docs: list[Document] = []
        for patent in results:
            try:
                doc = self._lens_to_document(patent, intervention, aliases)
                if doc and not self.storage.document_exists(intervention, doc.source_url):
                    docs.append(doc)
            except Exception as e:
                logger.warning(f"Failed to build PatentDocument from Lens.org: {e}")

        logger.info(f"Lens.org patents: {len(docs)} new documents for '{intervention}'")
        return docs

    async def _try_google_patents(
        self,
        intervention: str,
        aliases: list[str] | None,
        terms: list[str],
        max_results: int,
    ) -> list[Document] | None:
        """Try Google Patents search via HTTP scraping.

        Google Patents doesn't have a public API, so we attempt a simple
        search and parse the results page. This is fragile and may break.
        """
        query = f"{intervention} aging longevity"
        url = f"https://patents.google.com/xhr/query?url=q%3D{query.replace(' ', '+')}&exp=&type=PATENT"

        logger.info(f"Google Patents search: {query}")

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            try:
                resp = await client.get(url)
                if resp.status_code != 200:
                    logger.info(f"Google Patents returned {resp.status_code}")
                    return None
                data = resp.json()
            except Exception as e:
                logger.info(f"Google Patents failed: {e}")
                return None

        # Google Patents XHR returns a nested structure
        results = data.get("results", {}).get("cluster", [])
        if not results:
            return None

        docs: list[Document] = []
        for cluster in results:
            for result in cluster.get("result", []):
                if len(docs) >= max_results:
                    break

                patent_data = result.get("patent", {})
                patent_id = patent_data.get("publication_number", "")
                if not patent_id:
                    continue

                title = patent_data.get("title", "")
                abstract_localized = patent_data.get("abstract", "")
                snippet = result.get("snippet", "")

                # Aging relevance check
                text = f"{title} {abstract_localized} {snippet}".lower()
                if not any(kw in text for kw in AGING_RELEVANCE_TERMS):
                    continue

                source_url = f"https://patents.google.com/patent/{patent_id}"
                if self.storage.document_exists(intervention, source_url):
                    continue

                # Parse filing date
                filing_date_str = patent_data.get("filing_date", "")
                filing_date = _parse_patent_date(filing_date_str)

                # Parse assignee
                assignee = ""
                assignees = patent_data.get("assignee", [])
                if assignees and isinstance(assignees, list):
                    assignee = assignees[0] if isinstance(assignees[0], str) else ""

                # Inventors
                inventors = patent_data.get("inventor", [])
                if isinstance(inventors, list):
                    inventors = [i for i in inventors if isinstance(i, str)]
                else:
                    inventors = []

                try:
                    doc = PatentDocument(
                        intervention=intervention.lower(),
                        intervention_aliases=aliases or [],
                        title=title or f"Patent {patent_id}",
                        abstract=abstract_localized or snippet or "",
                        source_url=source_url,
                        date_published=filing_date or date.today(),
                        patent_id=patent_id,
                        assignee=assignee or None,
                        inventors=inventors,
                        filing_date=filing_date,
                        patent_office=_detect_office(patent_id),
                        raw_response=result,
                    )
                    docs.append(doc)
                except Exception as e:
                    logger.warning(f"Failed to build PatentDocument: {e}")

        logger.info(f"Google Patents: {len(docs)} new documents for '{intervention}'")
        return docs

    @staticmethod
    def _lens_to_document(
        patent: dict,
        intervention: str,
        aliases: list[str] | None,
    ) -> PatentDocument | None:
        """Convert a Lens.org patent result to PatentDocument."""
        lens_id = patent.get("lens_id", "")
        doc_num = patent.get("doc_number") or patent.get("publication_number") or lens_id
        if not doc_num:
            return None

        title = patent.get("title") or f"Patent {doc_num}"
        abstract = patent.get("abstract") or ""

        # Applicants/assignees
        applicants = patent.get("applicants") or []
        assignee = applicants[0].get("name", "") if applicants and isinstance(applicants[0], dict) else None

        # Inventors
        inventor_list = patent.get("inventors") or []
        inventors = []
        for inv in inventor_list:
            name = inv.get("name", "") if isinstance(inv, dict) else str(inv)
            if name:
                inventors.append(name)

        # Dates
        filing_date = _parse_patent_date(patent.get("filing_date"))
        grant_date = _parse_patent_date(patent.get("grant_date"))
        pub_date = _parse_patent_date(patent.get("date_published")) or filing_date or date.today()

        # Status
        legal_status = patent.get("legal_status") or ""
        patent_status = None
        if "granted" in legal_status.lower():
            patent_status = "granted"
        elif "pending" in legal_status.lower() or "application" in legal_status.lower():
            patent_status = "pending"
        elif "expired" in legal_status.lower():
            patent_status = "expired"

        # Office
        jurisdiction = patent.get("jurisdiction") or ""
        patent_office = _jurisdiction_to_office(jurisdiction) or _detect_office(doc_num)

        # Claims
        claims = patent.get("claims") or []
        claims_count = len(claims) if isinstance(claims, list) else None

        source_url = f"https://www.lens.org/lens/patent/{lens_id}" if lens_id else f"https://patents.google.com/patent/{doc_num}"

        return PatentDocument(
            intervention=intervention.lower(),
            intervention_aliases=aliases or [],
            title=title,
            abstract=abstract,
            source_url=source_url,
            date_published=pub_date,
            patent_id=doc_num,
            assignee=assignee,
            inventors=inventors,
            filing_date=filing_date,
            grant_date=grant_date,
            patent_status=patent_status,
            patent_office=patent_office,
            claims_count=claims_count,
            raw_response=patent,
        )


def _parse_patent_date(date_str: str | None) -> date | None:
    """Parse patent date in various formats."""
    if not date_str:
        return None
    try:
        clean = date_str[:10]
        if "-" in clean:
            parts = clean.split("-")
        elif "/" in clean:
            parts = clean.split("/")
        else:
            # YYYYMMDD format
            if len(clean) == 8:
                return date(int(clean[:4]), int(clean[4:6]), int(clean[6:8]))
            return None
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        return None


def _detect_office(patent_id: str) -> str | None:
    """Detect patent office from publication number prefix."""
    pid = patent_id.upper().strip()
    if pid.startswith("US"):
        return "USPTO"
    elif pid.startswith("EP"):
        return "EPO"
    elif pid.startswith("WO"):
        return "WIPO"
    elif pid.startswith("CN"):
        return "CNIPA"
    elif pid.startswith("JP"):
        return "JPO"
    return None


def _jurisdiction_to_office(jurisdiction: str) -> str | None:
    """Map Lens.org jurisdiction codes to patent office names."""
    mapping = {
        "US": "USPTO",
        "EP": "EPO",
        "WO": "WIPO",
        "CN": "CNIPA",
        "JP": "JPO",
        "KR": "KIPO",
        "AU": "IP Australia",
        "CA": "CIPO",
        "GB": "UKIPO",
    }
    return mapping.get(jurisdiction.upper().strip())
