"""Web/literature deep research agent using Tavily API.

Searches the web for news articles, blog posts, and general literature
about an intervention's aging/longevity research. Returns NewsDocument objects.
"""

from __future__ import annotations

from datetime import date

from loguru import logger

from src.config import settings
from src.ingest.base import BaseIngestAgent
from src.ingest.query_expander import QueryExpansion
from src.schema.document import Document, NewsDocument


# Module-level flag: set to True when Tavily returns 429 or credit-exhausted
# errors. Once set, all subsequent calls skip the API immediately.
_TAVILY_EXHAUSTED = False


def tavily_is_exhausted() -> bool:
    """Check whether Tavily credits have been exhausted this session."""
    return _TAVILY_EXHAUSTED


def _check_tavily_exhaustion(error: Exception) -> bool:
    """Return True if this error indicates Tavily credits/rate limits are hit."""
    msg = str(error).lower()
    return any(term in msg for term in (
        "429", "rate limit", "insufficient credits", "credit", "quota",
        "too many requests", "exceeded", "limit reached",
    ))


class TavilyAgent(BaseIngestAgent):
    @property
    def source_name(self) -> str:
        return "Tavily"

    async def ingest(
        self,
        intervention: str,
        aliases: list[str] | None = None,
        query_expansion: QueryExpansion | None = None,
        max_results: int = 20,
    ) -> list[Document]:
        global _TAVILY_EXHAUSTED

        if _TAVILY_EXHAUSTED:
            logger.info("Tavily credits exhausted — skipping")
            return []

        if not settings.tavily_api_key:
            logger.warning("TAVILY_API_KEY not set, skipping web search")
            return []

        query = self._get_query("general", intervention, aliases, query_expansion)
        logger.info(f"Tavily search: {query}")

        try:
            from tavily import AsyncTavilyClient

            client = AsyncTavilyClient(api_key=settings.tavily_api_key)
            response = await client.search(
                query=query,
                max_results=max_results,
                search_depth="advanced",
                include_answer=False,
            )
        except Exception as e:
            if _check_tavily_exhaustion(e):
                _TAVILY_EXHAUSTED = True
                logger.warning(
                    f"Tavily credits/rate limit exhausted: {e}. "
                    "Skipping Tavily for all remaining interventions."
                )
            else:
                logger.error(f"Tavily search failed: {e}")
            return []

        results = response.get("results", [])
        if not results:
            logger.info("No Tavily results found")
            return []

        docs: list[Document] = []
        for result in results:
            source_url = result.get("url", "")
            if not source_url:
                continue
            if self.storage.document_exists(intervention, source_url):
                continue

            # Skip academic/journal domains — these should come via PubMed or
            # Europe PMC where they get properly typed. Tagging a Springer
            # review paper as "news" pollutes the hype ratio signal.
            if _is_academic_url(source_url):
                logger.debug(f"Skipping academic URL from web search: {source_url}")
                continue

            try:
                doc = NewsDocument(
                    intervention=intervention.lower(),
                    intervention_aliases=aliases or [],
                    title=result.get("title", ""),
                    abstract=result.get("content", ""),
                    source_url=source_url,
                    date_published=_parse_tavily_date(result.get("published_date")),
                    outlet=_extract_outlet(source_url),
                    raw_response=result,
                )
                docs.append(doc)
            except Exception as e:
                logger.warning(f"Failed to build NewsDocument from Tavily result: {e}")

        logger.info(f"Web search: {len(docs)} new documents for '{intervention}'")
        return docs


def _parse_tavily_date(date_str: str | None) -> date:
    """Parse date from Tavily result. Falls back to today."""
    if not date_str:
        return date.today()
    try:
        # Tavily dates can be ISO format
        return date.fromisoformat(date_str[:10])
    except (ValueError, IndexError):
        return date.today()


def _extract_outlet(url: str) -> str:
    """Extract domain name as outlet from URL."""
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        domain = parsed.netloc.replace("www.", "")
        return domain
    except Exception:
        return ""


# Domains that host academic papers — results from these should come via
# PubMed / Europe PMC where they get properly typed, not as NewsDocument.
_ACADEMIC_DOMAINS = {
    "pubmed.ncbi.nlm.nih.gov",
    "ncbi.nlm.nih.gov",
    "europepmc.org",
    "scholar.google.com",
    "semanticscholar.org",
    "doi.org",
    "link.springer.com",
    "springer.com",
    "wiley.com",
    "onlinelibrary.wiley.com",
    "nature.com",
    "science.org",
    "sciencedirect.com",
    "cell.com",
    "thelancet.com",
    "nejm.org",
    "bmj.com",
    "jamanetwork.com",
    "academic.oup.com",
    "journals.plos.org",
    "frontiersin.org",
    "mdpi.com",
    "biorxiv.org",
    "medrxiv.org",
    "arxiv.org",
    "researchgate.net",
    "clinicaltrials.gov",
    "cochranelibrary.com",
}


def _is_academic_url(url: str) -> bool:
    """Check if a URL points to an academic/journal domain."""
    try:
        from urllib.parse import urlparse

        domain = urlparse(url).netloc.replace("www.", "").lower()
        return any(domain == d or domain.endswith(f".{d}") for d in _ACADEMIC_DOMAINS)
    except Exception:
        return False
