"""Semantic Scholar ingest agent.

Fetches papers from the Semantic Scholar Academic Graph API.
Provides citation counts and influential citation counts — particularly
valuable for understanding a paper's impact on the field.

Deduplicates against PubMed and Europe PMC docs by DOI.
"""

from __future__ import annotations

import asyncio
from datetime import date

import httpx
from loguru import logger

from src.config import AGING_RELEVANCE_TERMS
from src.ingest.base import BaseIngestAgent
from src.ingest.query_expander import QueryExpansion
from src.schema.document import Document, SemanticScholarDocument

S2_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
S2_FIELDS = (
    "paperId,title,abstract,year,citationCount,influentialCitationCount,"
    "tldr,publicationTypes,journal,externalIds,isOpenAccess,authors"
)

# Rate limit: 100 requests/min → ~0.6s between requests to be safe
RATE_LIMIT_DELAY = 0.7


def _score_paper(paper: dict) -> int:
    """Score a Semantic Scholar paper by aging relevance + citation impact."""
    score = 0
    title = (paper.get("title") or "").lower()
    abstract = (paper.get("abstract") or "").lower()
    text = f"{title} {abstract}"
    citation_count = paper.get("citationCount") or 0

    # Aging keyword scoring
    if any(kw in text for kw in AGING_RELEVANCE_TERMS):
        score += 1

    # Citation count boost
    if citation_count > 500:
        score += 3
    elif citation_count > 200:
        score += 2
    elif citation_count > 50:
        score += 1

    # Influential citations (high-quality signal)
    influential = paper.get("influentialCitationCount") or 0
    if influential > 20:
        score += 2
    elif influential > 5:
        score += 1

    # Publication type
    pub_types = {(pt or "").lower() for pt in (paper.get("publicationTypes") or [])}
    if "review" in pub_types:
        score += 1

    # Recency
    year = paper.get("year")
    if year and year >= date.today().year - 3:
        score += 1

    # Penalty: no aging terms
    if not any(kw in text for kw in AGING_RELEVANCE_TERMS):
        score -= 2

    return score


class SemanticScholarAgent(BaseIngestAgent):
    @property
    def source_name(self) -> str:
        return "Semantic Scholar"

    async def ingest(
        self,
        intervention: str,
        aliases: list[str] | None = None,
        query_expansion: QueryExpansion | None = None,
        max_results: int = 100,
    ) -> list[Document]:
        # S2 works best with short keyword queries, not long natural language
        query = f"{intervention} aging longevity"

        logger.info(f"Semantic Scholar search: {query[:80]}...")

        # Collect existing DOIs for dedup against PubMed and Europe PMC
        existing_docs = self.storage.get_documents(intervention)
        existing_dois: set[str] = set()
        for d in existing_docs:
            doi = getattr(d, "doi", None)
            if doi:
                existing_dois.add(doi.lower())

        all_papers: list[dict] = []
        offset = 0
        per_page = 100  # S2 max

        retries = 0
        max_retries = 3

        async with httpx.AsyncClient(timeout=30.0) as client:
            while len(all_papers) < max_results:
                limit = min(per_page, max_results - len(all_papers))
                params = {
                    "query": query,
                    "fields": S2_FIELDS,
                    "offset": offset,
                    "limit": limit,
                }
                try:
                    resp = await client.get(S2_SEARCH_URL, params=params)
                    if resp.status_code == 429:
                        retries += 1
                        if retries > max_retries:
                            logger.warning("Semantic Scholar: max retries reached, stopping")
                            break
                        wait = 10 * retries
                        logger.warning(f"Semantic Scholar rate limited, waiting {wait}s (retry {retries}/{max_retries})...")
                        await asyncio.sleep(wait)
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    retries = 0  # Reset on success
                except Exception as e:
                    logger.error(f"Semantic Scholar search failed: {e}")
                    break

                total = data.get("total", 0)
                if offset == 0:
                    logger.info(f"Semantic Scholar total results: {total}")

                papers = data.get("data", [])
                if not papers:
                    break

                all_papers.extend(papers)
                offset += len(papers)

                if offset >= total or offset >= max_results:
                    break
                await asyncio.sleep(RATE_LIMIT_DELAY)

        logger.info(f"Semantic Scholar fetched {len(all_papers)} candidate papers")

        # Score and rank
        for p in all_papers:
            p["_score"] = _score_paper(p)
        all_papers.sort(key=lambda p: p["_score"], reverse=True)
        all_papers = all_papers[:max_results]

        # Build documents
        docs: list[Document] = []
        for paper in all_papers:
            paper_id = paper.get("paperId", "")
            if not paper_id:
                continue

            # Build source URL
            source_url = f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}"

            if self.storage.document_exists(intervention, source_url):
                continue

            # Dedup by DOI
            ext_ids = paper.get("externalIds") or {}
            doi = ext_ids.get("DOI", "")
            if doi and doi.lower() in existing_dois:
                continue

            try:
                # Extract authors
                authors = []
                for a in (paper.get("authors") or []):
                    name = a.get("name", "")
                    if name:
                        authors.append(name)

                # Parse journal
                journal_info = paper.get("journal") or {}
                journal_name = journal_info.get("name") if isinstance(journal_info, dict) else None

                # TLDR
                tldr_obj = paper.get("tldr") or {}
                tldr_text = tldr_obj.get("text") if isinstance(tldr_obj, dict) else None

                # Date
                year = paper.get("year")
                pub_date = date(year, 1, 1) if year else date.today()

                doc = SemanticScholarDocument(
                    intervention=intervention.lower(),
                    intervention_aliases=aliases or [],
                    title=paper.get("title") or "",
                    abstract=paper.get("abstract") or "",
                    source_url=source_url,
                    date_published=pub_date,
                    paper_id=paper_id,
                    doi=doi or None,
                    authors=authors,
                    journal=journal_name,
                    year=year,
                    citation_count=paper.get("citationCount"),
                    influential_citation_count=paper.get("influentialCitationCount"),
                    tldr=tldr_text,
                    publication_types=paper.get("publicationTypes") or [],
                    is_open_access=paper.get("isOpenAccess", False) or False,
                    raw_response=paper,
                )
                docs.append(doc)
            except Exception as e:
                logger.warning(f"Failed to build SemanticScholarDocument for {paper_id}: {e}")

        logger.info(f"Semantic Scholar: {len(docs)} new documents for '{intervention}'")
        return docs
