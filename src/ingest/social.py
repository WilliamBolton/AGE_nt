"""Social media ingest agent — Reddit.

Searches Reddit subreddits (r/longevity, r/Nootropics, r/supplements, r/Biohackers)
for discussions about interventions. Only includes posts where the intervention
name or an alias appears in the title or body. No hard cap per subreddit.
Returns SocialDocument objects.
"""

from __future__ import annotations

from datetime import date, datetime

import httpx
from loguru import logger

from src.ingest.base import BaseIngestAgent
from src.ingest.query_expander import QueryExpansion
from src.schema.document import Document, SocialDocument

SUBREDDITS = ["longevity", "Nootropics", "supplements", "Biohackers"]
REDDIT_SEARCH_URL = "https://www.reddit.com/r/{subreddit}/search.json"


class SocialAgent(BaseIngestAgent):
    @property
    def source_name(self) -> str:
        return "Social Media (Reddit)"

    async def ingest(
        self,
        intervention: str,
        aliases: list[str] | None = None,
        query_expansion: QueryExpansion | None = None,
        max_results: int = 100,
    ) -> list[Document]:
        # Build search query
        search_query = intervention
        if query_expansion and query_expansion.synonyms:
            extra = query_expansion.synonyms[:2]
            search_query = " OR ".join([intervention] + extra)

        # Build relevance filter terms (lowercase)
        filter_terms = {intervention.lower()}
        if aliases:
            filter_terms.update(a.lower() for a in aliases)
        if query_expansion:
            filter_terms.update(s.lower() for s in query_expansion.synonyms)

        logger.info(f"Reddit search: '{search_query}' in {SUBREDDITS}")
        logger.info(f"Reddit filter terms: {filter_terms}")

        docs: list[Document] = []

        async with httpx.AsyncClient(
            timeout=15.0,
            headers={"User-Agent": "LongevityLens/0.1 (research tool)"},
        ) as client:
            for subreddit in SUBREDDITS:
                try:
                    sub_docs = await self._search_subreddit(
                        client, subreddit, search_query,
                        intervention, aliases or [], filter_terms,
                    )
                    docs.extend(sub_docs)
                except Exception as e:
                    logger.warning(f"Reddit r/{subreddit} search failed: {e}")

        # Sort by engagement (score + comments) and take top max_results
        docs.sort(key=lambda d: (d.score or 0) + (d.comment_count or 0), reverse=True)
        docs = docs[:max_results]

        logger.info(f"Social: {len(docs)} new documents for '{intervention}'")
        return docs

    async def _search_subreddit(
        self,
        client: httpx.AsyncClient,
        subreddit: str,
        query: str,
        intervention: str,
        aliases: list[str],
        filter_terms: set[str],
    ) -> list[Document]:
        """Search a single subreddit via Reddit JSON API."""
        url = REDDIT_SEARCH_URL.format(subreddit=subreddit)
        params = {
            "q": query,
            "restrict_sr": "on",
            "sort": "relevance",
            "t": "all",
            "limit": 100,  # Reddit API max per page
        }

        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

        posts = data.get("data", {}).get("children", [])
        docs: list[Document] = []

        for post in posts:
            post_data = post.get("data", {})
            permalink = post_data.get("permalink", "")
            source_url = f"https://www.reddit.com{permalink}" if permalink else ""

            if not source_url:
                continue
            if self.storage.document_exists(intervention, source_url):
                continue

            selftext = post_data.get("selftext", "")
            title = post_data.get("title", "")

            # Relevance filter: intervention name or alias must appear in title or body
            text_lower = f"{title} {selftext}".lower()
            if not any(term in text_lower for term in filter_terms):
                continue

            try:
                created_utc = post_data.get("created_utc", 0)
                pub_date = datetime.fromtimestamp(created_utc).date() if created_utc else date.today()

                doc = SocialDocument(
                    intervention=intervention.lower(),
                    intervention_aliases=aliases,
                    title=title,
                    abstract=selftext[:2000] if selftext else title,
                    source_url=source_url,
                    date_published=pub_date,
                    platform="reddit",
                    subreddit=subreddit,
                    score=post_data.get("score"),
                    comment_count=post_data.get("num_comments"),
                    raw_response=post_data,
                )
                docs.append(doc)
            except Exception as e:
                logger.warning(f"Failed to build SocialDocument: {e}")

        return docs
