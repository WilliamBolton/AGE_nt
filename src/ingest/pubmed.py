"""PubMed ingest agent using NCBI E-utilities.

Searches PubMed for aging-related research on a given intervention,
fetches full article metadata via XML, and returns typed PubMedDocument objects.

Uses a 3-tier filtering strategy:
  Tier 1: PubMed sort=relevance + hasabstract filter
  Tier 2: Filter by publication type (keep studies, drop editorials)
  Tier 3: Relevance scoring with simple heuristics, keep top N
"""

from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET
from datetime import date

import httpx
from loguru import logger

from src.config import AGING_RELEVANCE_TERMS, settings
from src.ingest.base import BaseIngestAgent
from src.ingest.query_expander import QueryExpansion
from src.schema.document import Document, PubMedDocument

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
ESEARCH_URL = f"{EUTILS_BASE}/esearch.fcgi"
EFETCH_URL = f"{EUTILS_BASE}/efetch.fcgi"

RATE_LIMIT_DELAY = 0.1 if settings.ncbi_api_key else 0.34

# ── Tier 2: Publication type filtering ──────────────────────────────────────

KEEP_PUB_TYPES = {
    "meta-analysis", "systematic review", "randomized controlled trial",
    "clinical trial", "observational study", "comparative study",
    "journal article", "review",
}

DROP_PUB_TYPES = {
    "letter", "comment", "editorial", "published erratum", "news",
}

# ── Tier 3: Relevance scoring ───────────────────────────────────────────────

HIGH_IMPACT_JOURNALS = {
    "nature", "science", "cell", "lancet",
    "new england journal of medicine", "nejm",
    "nature aging", "aging cell", "nature medicine",
    "jama", "bmj", "cell metabolism",
    "nature communications", "aging", "geroscience",
    "journals of gerontology", "aging and disease",
    "frontiers in aging neuroscience",
}

AGING_MESH_LOWER = {
    "aging", "longevity", "cellular senescence", "senescence",
    "life span", "aged", "aged, 80 and over",
}


def _score_paper(article: dict) -> int:
    """Score a paper by relevance to aging research. Higher = more relevant."""
    score = 0
    pub_types = {pt.lower() for pt in article.get("publication_types", [])}
    mesh = {m.lower() for m in article.get("mesh_terms", [])}
    abstract = (article.get("abstract") or "").lower()
    title = (article.get("title") or "").lower()
    text = f"{title} {abstract}"
    journal = (article.get("journal") or "").lower()

    # +3 for meta-analysis or systematic review
    if pub_types & {"meta-analysis", "systematic review"}:
        score += 3

    # +2 for RCT or clinical trial
    if pub_types & {
        "randomized controlled trial", "clinical trial",
        "clinical trial, phase iii", "clinical trial, phase ii",
    }:
        score += 2

    # +1 for aging MeSH terms
    if mesh & AGING_MESH_LOWER:
        score += 1

    # +1 for aging keywords in text
    if any(kw in text for kw in AGING_RELEVANCE_TERMS):
        score += 1

    # +1 for high-impact journal
    if any(j in journal for j in HIGH_IMPACT_JOURNALS):
        score += 1

    # +1 for recency (last 3 years)
    pub_date = article.get("date_published")
    if pub_date and isinstance(pub_date, date):
        if (date.today() - pub_date).days < 365 * 3:
            score += 1

    # -2 if no aging-related terms anywhere (title, abstract, MeSH)
    # Intervention-agnostic: penalises any non-aging paper regardless of drug
    all_text = f"{text} {' '.join(mesh)}"
    if not any(kw in all_text for kw in AGING_RELEVANCE_TERMS):
        score -= 2

    return score


class PubMedAgent(BaseIngestAgent):
    @property
    def source_name(self) -> str:
        return "PubMed"

    async def ingest(
        self,
        intervention: str,
        aliases: list[str] | None = None,
        query_expansion: QueryExpansion | None = None,
        max_results: int = 100,
    ) -> list[Document]:
        query = self._get_query("pubmed", intervention, aliases, query_expansion)
        logger.info(f"PubMed search query: {query}")

        async with httpx.AsyncClient(timeout=30.0) as client:
            # Tier 1: Request larger candidate pool with relevance sort
            candidate_pool = max(max_results * 3, 200)
            pmids = await self._esearch(query, candidate_pool, client)
            if not pmids:
                logger.info("No PubMed results found")
                return []
            logger.info(f"Found {len(pmids)} candidate PMIDs")

            # Fetch article metadata
            articles = await self._efetch_all(pmids, client)
            logger.info(f"Fetched {len(articles)} articles")

        # Tier 2: Filter by publication type
        before_filter = len(articles)
        articles = [a for a in articles if not self._should_drop_pub_type(a)]
        logger.info(f"Tier 2 pub-type filter: {before_filter} -> {len(articles)} articles")

        # Tier 3: Score and rank by relevance
        for a in articles:
            a["_relevance_score"] = _score_paper(a)
        articles.sort(key=lambda a: a["_relevance_score"], reverse=True)
        articles = articles[:max_results]
        if articles:
            logger.info(
                f"Tier 3 scoring: keeping top {len(articles)} "
                f"(scores: {articles[0]['_relevance_score']} to {articles[-1]['_relevance_score']})"
            )

        # Build documents, skipping duplicates
        docs: list[Document] = []
        for article in articles:
            source_url = article.get("source_url", "")
            if self.storage.document_exists(intervention, source_url):
                continue
            try:
                doc = PubMedDocument(
                    intervention=intervention.lower(),
                    intervention_aliases=aliases or [],
                    pmid=article["pmid"],
                    title=article.get("title", ""),
                    abstract=article.get("abstract", ""),
                    source_url=source_url,
                    date_published=article.get("date_published", date.today()),
                    doi=article.get("doi"),
                    authors=article.get("authors", []),
                    journal=article.get("journal"),
                    mesh_terms=article.get("mesh_terms", []),
                    publication_types=article.get("publication_types", []),
                    raw_response=article.get("raw_xml_snippet", {}),
                )
                docs.append(doc)
            except Exception as e:
                logger.warning(f"Failed to build PubMedDocument for PMID {article.get('pmid')}: {e}")

        logger.info(f"PubMed: {len(docs)} new documents for '{intervention}'")
        return docs

    @staticmethod
    def _should_drop_pub_type(article: dict) -> bool:
        """Tier 2: Drop editorials, letters, errata. Keep studies."""
        pub_types = {pt.lower() for pt in article.get("publication_types", [])}
        # If any type is in the drop list AND none are in the keep list, drop it
        if pub_types & DROP_PUB_TYPES and not pub_types & KEEP_PUB_TYPES:
            return True
        return False

    async def _esearch(
        self,
        query: str,
        max_results: int,
        client: httpx.AsyncClient,
    ) -> list[str]:
        """Search PubMed, return list of PMIDs."""
        # Tier 1: relevance sort + has-abstract filter
        full_query = f"{query} AND hasabstract"
        params: dict = {
            "db": "pubmed",
            "term": full_query,
            "retmax": max_results,
            "retmode": "json",
            "sort": "relevance",
        }
        if settings.ncbi_api_key:
            params["api_key"] = settings.ncbi_api_key

        try:
            resp = await client.get(ESEARCH_URL, params=params)
            logger.info(f"PubMed esearch URL: {resp.url}")
            resp.raise_for_status()
            data = resp.json()
            result = data.get("esearchresult", {})
            total = result.get("count", "?")
            pmids = result.get("idlist", [])
            logger.info(f"PubMed total matches: {total}, returning: {len(pmids)}")
            return pmids
        except Exception as e:
            logger.error(f"PubMed esearch failed: {e}")
            return []

    async def _efetch_batch(
        self,
        pmids: list[str],
        client: httpx.AsyncClient,
    ) -> list[dict]:
        """Fetch article XML for a batch of PMIDs."""
        params: dict = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
            "rettype": "abstract",
        }
        if settings.ncbi_api_key:
            params["api_key"] = settings.ncbi_api_key

        try:
            resp = await client.get(EFETCH_URL, params=params)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
            articles = []
            for article_elem in root.findall(".//PubmedArticle"):
                parsed = self._parse_article_xml(article_elem)
                if parsed:
                    articles.append(parsed)
            return articles
        except Exception as e:
            logger.error(f"PubMed efetch failed for {len(pmids)} PMIDs: {e}")
            return []

    async def _efetch_all(
        self,
        pmids: list[str],
        client: httpx.AsyncClient,
        batch_size: int = 50,
    ) -> list[dict]:
        """Fetch all PMIDs in batches, respecting rate limits."""
        all_articles: list[dict] = []
        for i in range(0, len(pmids), batch_size):
            batch = pmids[i : i + batch_size]
            articles = await self._efetch_batch(batch, client)
            all_articles.extend(articles)
            if i + batch_size < len(pmids):
                await asyncio.sleep(RATE_LIMIT_DELAY)
        return all_articles

    @staticmethod
    def _parse_article_xml(article_elem: ET.Element) -> dict | None:
        """Parse a single <PubmedArticle> XML element into a dict."""
        try:
            medline = article_elem.find(".//MedlineCitation")
            if medline is None:
                return None

            # PMID
            pmid_elem = medline.find(".//PMID")
            pmid = pmid_elem.text if pmid_elem is not None else ""
            if not pmid:
                return None

            # Title
            title_elem = medline.find(".//ArticleTitle")
            title = title_elem.text or "" if title_elem is not None else ""

            # Abstract — may have multiple sections
            abstract_parts = []
            for abs_text in medline.findall(".//AbstractText"):
                label = abs_text.get("Label", "")
                text = abs_text.text or ""
                if label:
                    abstract_parts.append(f"{label}: {text}")
                else:
                    abstract_parts.append(text)
            abstract = "\n".join(abstract_parts)

            # Authors
            authors = []
            for author in medline.findall(".//Author"):
                last = author.findtext("LastName", "")
                first = author.findtext("ForeName", "")
                if last:
                    authors.append(f"{last} {first}".strip())

            # Journal
            journal = medline.findtext(".//Journal/Title", "")

            # Date
            pub_date = PubMedAgent._parse_pub_date(medline)

            # DOI
            doi = None
            for aid in article_elem.findall(".//ArticleId"):
                if aid.get("IdType") == "doi":
                    doi = aid.text
                    break

            # MeSH terms
            mesh_terms = []
            for mesh in medline.findall(".//MeshHeading/DescriptorName"):
                if mesh.text:
                    mesh_terms.append(mesh.text)

            # Publication types
            pub_types = []
            for pt in medline.findall(".//PublicationTypeList/PublicationType"):
                if pt.text:
                    pub_types.append(pt.text)

            return {
                "pmid": pmid,
                "title": title,
                "abstract": abstract,
                "authors": authors,
                "journal": journal,
                "date_published": pub_date,
                "doi": doi,
                "mesh_terms": mesh_terms,
                "publication_types": pub_types,
                "source_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            }
        except Exception as e:
            logger.warning(f"Failed to parse PubMed article XML: {e}")
            return None

    @staticmethod
    def _parse_pub_date(medline: ET.Element) -> date:
        """Parse PubMed date, handling partial dates."""
        pub_date = medline.find(".//PubDate")
        if pub_date is not None:
            year = pub_date.findtext("Year")
            month = pub_date.findtext("Month", "1")
            day = pub_date.findtext("Day", "1")
            if year:
                month_map = {
                    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
                    "may": 5, "jun": 6, "jul": 7, "aug": 8,
                    "sep": 9, "oct": 10, "nov": 11, "dec": 12,
                }
                try:
                    m = int(month)
                except ValueError:
                    m = month_map.get(month.lower()[:3], 1)
                try:
                    d = int(day)
                except ValueError:
                    d = 1
                try:
                    return date(int(year), m, d)
                except ValueError:
                    return date(int(year), 1, 1)

        medline_date = pub_date.findtext("MedlineDate", "") if pub_date is not None else ""
        if medline_date:
            parts = medline_date.split()
            if parts and parts[0].isdigit():
                return date(int(parts[0]), 1, 1)

        return date.today()
