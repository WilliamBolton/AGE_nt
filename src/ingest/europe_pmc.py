"""Europe PMC ingest agent — journals, preprints, and Cochrane reviews.

Replaces the preprints-only agent. Europe PMC is a superset of PubMed: it indexes
journal articles, preprints (bioRxiv, medRxiv), Cochrane reviews, WHO trial
registries, and patents.

Uses the same 3-tier relevance scoring as PubMed, plus citation-count boost.
Deduplicates against PubMed docs by DOI or PMID.
"""

from __future__ import annotations

import asyncio
from datetime import date

import httpx
from loguru import logger

from src.config import AGING_RELEVANCE_TERMS
from src.ingest.base import BaseIngestAgent
from src.ingest.query_expander import QueryExpansion
from src.schema.document import Document, EuropePMCDocument

EUROPEPMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

# Publication types to drop (noise)
DROP_PUB_TYPES = {"letter", "comment", "editorial", "erratum", "news"}


def _score_paper(paper: dict, all_terms: set[str]) -> int:
    """Score a Europe PMC paper by relevance to aging research."""
    score = 0
    title = (paper.get("title") or "").lower()
    abstract = (paper.get("abstractText") or "").lower()
    text = f"{title} {abstract}"
    journal = (paper.get("journalTitle") or "").lower()
    pub_types = {pt.lower() for pt in (paper.get("pubTypeList", {}).get("pubType", []) or [])}
    cited_by = paper.get("citedByCount", 0) or 0

    # Publication type scoring
    if pub_types & {"meta-analysis", "systematic-review", "systematic review"}:
        score += 3
    if pub_types & {"randomized-controlled-trial", "randomized controlled trial", "clinical-trial"}:
        score += 2

    # Aging keyword scoring
    if any(kw in text for kw in AGING_RELEVANCE_TERMS):
        score += 1

    # High-impact journal
    high_impact = {
        "nature", "science", "cell", "lancet", "nature aging", "aging cell",
        "nature medicine", "geroscience", "aging", "cell metabolism",
    }
    if any(j in journal for j in high_impact):
        score += 1

    # Recency
    try:
        pub_date = _parse_epmc_date(paper.get("firstPublicationDate"))
        if (date.today() - pub_date).days < 365 * 3:
            score += 1
    except Exception:
        pass

    # Citation count boost
    if cited_by > 200:
        score += 2
    elif cited_by > 50:
        score += 1

    # Penalty: no aging terms anywhere
    if not any(kw in text for kw in AGING_RELEVANCE_TERMS):
        score -= 2

    return score


class EuropePMCAgent(BaseIngestAgent):
    @property
    def source_name(self) -> str:
        return "Europe PMC"

    async def ingest(
        self,
        intervention: str,
        aliases: list[str] | None = None,
        query_expansion: QueryExpansion | None = None,
        max_results: int = 100,
    ) -> list[Document]:
        # Build search query using expanded terms
        terms = self._all_terms(intervention, aliases, query_expansion)
        quoted = [f'"{t}"' if " " in t else t for t in terms]
        term_query = " OR ".join(quoted)
        query = f"({term_query}) AND (aging OR ageing OR longevity OR senescence)"
        query += "&resultType=core&format=json"

        logger.info(f"Europe PMC search: {term_query[:80]}...")

        # Collect existing DOIs and PMIDs for dedup against PubMed
        existing_docs = self.storage.get_documents(intervention)
        existing_dois: set[str] = set()
        existing_pmids: set[str] = set()
        for d in existing_docs:
            doi = getattr(d, "doi", None)
            if doi:
                existing_dois.add(doi.lower())
            pmid = getattr(d, "pmid", None)
            if pmid:
                existing_pmids.add(pmid)

        all_papers: list[dict] = []
        cursor: str | None = None

        async with httpx.AsyncClient(timeout=30.0) as client:
            # Fetch a larger candidate pool for scoring
            candidate_pool = max(max_results * 2, 200)
            while len(all_papers) < candidate_pool:
                page_size = min(candidate_pool - len(all_papers), 200)
                params: dict = {
                    "query": f"({term_query}) AND (aging OR ageing OR longevity OR senescence)",
                    "resultType": "core",
                    "format": "json",
                    "pageSize": page_size,
                }
                if cursor:
                    params["cursorMark"] = cursor

                try:
                    resp = await client.get(EUROPEPMC_SEARCH, params=params)
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as e:
                    logger.error(f"Europe PMC search failed: {e}")
                    break

                if not cursor:
                    hit_count = data.get("hitCount", 0)
                    logger.info(f"Europe PMC total hits: {hit_count}")

                results = data.get("resultList", {}).get("result", [])
                if not results:
                    break

                all_papers.extend(results)

                next_cursor = data.get("nextCursorMark")
                if not next_cursor or next_cursor == cursor:
                    break
                cursor = next_cursor
                await asyncio.sleep(0.1)  # Be polite

        logger.info(f"Europe PMC fetched {len(all_papers)} candidate papers")

        # Filter: drop noise publication types
        all_papers = [p for p in all_papers if not _should_drop(p)]

        # Score and rank
        all_terms_set = set(AGING_RELEVANCE_TERMS)
        for p in all_papers:
            p["_score"] = _score_paper(p, all_terms_set)
        all_papers.sort(key=lambda p: p["_score"], reverse=True)
        all_papers = all_papers[:max_results]

        if all_papers:
            logger.info(
                f"Europe PMC scoring: top {len(all_papers)} "
                f"(scores: {all_papers[0]['_score']} to {all_papers[-1]['_score']})"
            )

        # Build documents, deduplicating
        docs: list[Document] = []
        for paper in all_papers:
            source_url = _build_source_url(paper)
            if not source_url:
                continue
            if self.storage.document_exists(intervention, source_url):
                continue

            # Dedup against PubMed by DOI or PMID
            doi = paper.get("doi", "")
            pmid = paper.get("pmid", "")
            if doi and doi.lower() in existing_dois:
                continue
            if pmid and pmid in existing_pmids:
                continue

            try:
                is_cochrane = _is_cochrane(paper)
                is_preprint = _is_preprint(paper)
                preprint_server = _detect_preprint_server(paper) if is_preprint else None

                doc = EuropePMCDocument(
                    intervention=intervention.lower(),
                    intervention_aliases=aliases or [],
                    title=paper.get("title", ""),
                    abstract=paper.get("abstractText", ""),
                    source_url=source_url,
                    date_published=_parse_epmc_date(paper.get("firstPublicationDate")),
                    pmid=pmid or None,
                    pmcid=paper.get("pmcid") or None,
                    doi=doi or None,
                    authors=_parse_authors(paper.get("authorString", "")),
                    journal=paper.get("journalTitle"),
                    cited_by_count=paper.get("citedByCount"),
                    is_open_access=paper.get("isOpenAccess", "N") == "Y",
                    peer_reviewed=not is_preprint,
                    is_preprint=is_preprint,
                    is_cochrane=is_cochrane,
                    preprint_server=preprint_server,
                    publication_types=paper.get("pubTypeList", {}).get("pubType", []) or [],
                    mesh_terms=_extract_mesh(paper),
                    raw_response=paper,
                )
                docs.append(doc)
            except Exception as e:
                logger.warning(f"Failed to build EuropePMCDocument: {e}")

        logger.info(f"Europe PMC: {len(docs)} new documents for '{intervention}'")
        return docs


def _should_drop(paper: dict) -> bool:
    """Drop noise publication types."""
    pub_types = {pt.lower() for pt in (paper.get("pubTypeList", {}).get("pubType", []) or [])}
    return bool(pub_types & DROP_PUB_TYPES and not pub_types - DROP_PUB_TYPES)


def _is_cochrane(paper: dict) -> bool:
    """Detect Cochrane Database reviews — automatic Level 1 evidence."""
    journal = (paper.get("journalTitle") or "").lower()
    source = (paper.get("source") or "").lower()
    return "cochrane" in journal or source == "cochrane"


def _is_preprint(paper: dict) -> bool:
    """Detect preprints from Europe PMC metadata."""
    source = (paper.get("source") or "").upper()
    pub_types = {pt.lower() for pt in (paper.get("pubTypeList", {}).get("pubType", []) or [])}
    return "PPR" in source or "preprint" in pub_types


def _detect_preprint_server(paper: dict) -> str | None:
    """Identify bioRxiv vs medRxiv for preprints."""
    publisher = (paper.get("bookOrReportDetails", {}) or {}).get("publisher", "") or ""
    publisher = publisher.lower()
    if "medrxiv" in publisher:
        return "medRxiv"
    if "biorxiv" in publisher:
        return "bioRxiv"
    doi = (paper.get("doi") or "").lower()
    if "medrxiv" in doi:
        return "medRxiv"
    if "biorxiv" in doi:
        return "bioRxiv"
    return None


def _build_source_url(paper: dict) -> str:
    """Build a canonical source URL."""
    doi = paper.get("doi", "")
    if doi:
        return f"https://doi.org/{doi}"
    pmcid = paper.get("pmcid", "")
    if pmcid:
        return f"https://europepmc.org/article/PMC/{pmcid}"
    pmid = paper.get("pmid", "")
    if pmid:
        return f"https://europepmc.org/article/MED/{pmid}"
    epmc_id = paper.get("id", "")
    if epmc_id:
        source = paper.get("source", "MED")
        return f"https://europepmc.org/article/{source}/{epmc_id}"
    return ""


def _parse_epmc_date(date_str: str | None) -> date:
    """Parse Europe PMC date format (YYYY-MM-DD)."""
    if not date_str:
        return date.today()
    try:
        parts = date_str.split("-")
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        try:
            return date(int(date_str[:4]), 1, 1)
        except (ValueError, IndexError):
            return date.today()


def _parse_authors(authors_str: str) -> list[str]:
    """Parse author string like 'Smith J, Jones K' into a list."""
    if not authors_str:
        return []
    return [a.strip() for a in authors_str.split(",") if a.strip()]


def _extract_mesh(paper: dict) -> list[str]:
    """Extract MeSH terms from Europe PMC metadata."""
    mesh_list = paper.get("meshHeadingList", {})
    if not mesh_list:
        return []
    headings = mesh_list.get("meshHeading", [])
    if not headings:
        return []
    terms = []
    for h in headings:
        desc = h.get("descriptorName")
        if desc:
            terms.append(desc)
    return terms
