"""NIH Reporter ingest agent — federally funded research grants.

Fetches active and recent grants from the NIH Reporter API related to
an intervention and aging. Funding data feeds trajectory scoring —
funding momentum over time is a strong signal for intervention maturity.

NIA (National Institute on Aging) funding gets a scoring boost.
"""

from __future__ import annotations

import asyncio
from datetime import date

import httpx
from loguru import logger

from src.config import AGING_RELEVANCE_TERMS
from src.ingest.base import BaseIngestAgent
from src.ingest.query_expander import QueryExpansion
from src.schema.document import Document, GrantDocument

NIH_REPORTER_URL = "https://api.reporter.nih.gov/v2/projects/search"


def _score_grant(project: dict) -> int:
    """Score a grant by aging relevance and funding significance."""
    score = 0
    title = (project.get("project_title") or "").lower()
    abstract = (project.get("abstract_text") or "").lower()
    text = f"{title} {abstract}"

    # Aging keyword scoring
    if any(kw in text for kw in AGING_RELEVANCE_TERMS):
        score += 1

    # NIA funding — strong aging signal
    agency_fundings = project.get("agency_ic_fundings") or []
    nih_institutes = set()
    for funding in agency_fundings:
        ic = funding.get("abbreviation", "")
        if ic:
            nih_institutes.add(ic.upper())
    if "NIA" in nih_institutes:
        score += 2

    # Active grants
    if project.get("project_end_date"):
        try:
            end_str = project["project_end_date"][:10]
            parts = end_str.split("-")
            end_date = date(int(parts[0]), int(parts[1]), int(parts[2]))
            if end_date >= date.today():
                score += 1
        except (ValueError, IndexError):
            pass

    # Large awards
    award_amount = project.get("award_amount") or 0
    if award_amount > 500_000:
        score += 1

    # Penalty: no aging terms
    if not any(kw in text for kw in AGING_RELEVANCE_TERMS):
        score -= 2

    return score


class NIHReporterAgent(BaseIngestAgent):
    @property
    def source_name(self) -> str:
        return "NIH Reporter"

    async def ingest(
        self,
        intervention: str,
        aliases: list[str] | None = None,
        query_expansion: QueryExpansion | None = None,
        max_results: int = 100,
    ) -> list[Document]:
        # NIH Reporter text search is broad — use quoted intervention name
        # and boolean AND to keep results focused
        search_text = f'"{intervention}" AND (aging OR longevity OR senescence)'

        logger.info(f"NIH Reporter search: {search_text[:80]}...")

        all_projects: list[dict] = []
        offset = 0

        async with httpx.AsyncClient(timeout=30.0) as client:
            while len(all_projects) < max_results:
                limit = min(100, max_results - len(all_projects))
                payload = {
                    "criteria": {
                        "advanced_text_search": {
                            "search_field": "terms",
                            "search_text": search_text,
                        }
                    },
                    "offset": offset,
                    "limit": limit,
                }

                try:
                    resp = await client.post(
                        NIH_REPORTER_URL,
                        json=payload,
                        headers={"Content-Type": "application/json"},
                    )
                    if resp.status_code == 429:
                        logger.warning("NIH Reporter rate limited, waiting 5s...")
                        await asyncio.sleep(5)
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as e:
                    logger.error(f"NIH Reporter search failed: {e}")
                    break

                meta = data.get("meta", {})
                total = meta.get("total", 0)
                if offset == 0:
                    logger.info(f"NIH Reporter total results: {total}")

                results = data.get("results") or []
                if not results:
                    break

                all_projects.extend(results)
                offset += len(results)

                if offset >= total or offset >= max_results:
                    break
                await asyncio.sleep(0.5)

        logger.info(f"NIH Reporter fetched {len(all_projects)} candidate grants")

        # Score and rank
        for p in all_projects:
            p["_score"] = _score_grant(p)
        all_projects.sort(key=lambda p: p["_score"], reverse=True)
        all_projects = all_projects[:max_results]

        # Build documents
        docs: list[Document] = []
        for project in all_projects:
            project_num = project.get("project_num") or ""
            if not project_num:
                continue

            source_url = f"https://reporter.nih.gov/project-details/{project_num}"
            if self.storage.document_exists(intervention, source_url):
                continue

            try:
                doc = self._project_to_document(project, intervention, aliases)
                if doc:
                    docs.append(doc)
            except Exception as e:
                logger.warning(f"Failed to build GrantDocument for {project_num}: {e}")

        logger.info(f"NIH Reporter: {len(docs)} new documents for '{intervention}'")
        return docs

    @staticmethod
    def _project_to_document(
        project: dict,
        intervention: str,
        aliases: list[str] | None,
    ) -> GrantDocument | None:
        """Convert an NIH Reporter project to a GrantDocument."""
        project_num = project.get("project_num", "")
        title = project.get("project_title") or ""
        abstract = project.get("abstract_text") or ""

        # PI info
        contact_pi = project.get("contact_pi_name") or ""
        pi_names = project.get("principal_investigators") or []
        pi_name = contact_pi
        if not pi_name and pi_names:
            first_pi = pi_names[0] if pi_names else {}
            pi_name = first_pi.get("full_name", "") if isinstance(first_pi, dict) else ""

        # Organisation
        org = project.get("organization") or {}
        org_name = org.get("org_name", "") if isinstance(org, dict) else ""

        # Funding
        award_amount = project.get("award_amount")
        fiscal_year = project.get("fiscal_year")

        # Dates
        grant_start = _parse_nih_date(project.get("project_start_date"))
        grant_end = _parse_nih_date(project.get("project_end_date"))

        # Funding mechanism (R01, R21, etc.) — first 3 chars of project number
        funding_mechanism = None
        if project_num and len(project_num) >= 3:
            mechanism = project_num[:3].strip()
            if mechanism[0].isalpha():
                funding_mechanism = mechanism

        # NIH institute
        nih_institute = None
        agency_fundings = project.get("agency_ic_fundings") or []
        if agency_fundings:
            nih_institute = agency_fundings[0].get("abbreviation", "")

        # Use grant start or fiscal year for date_published
        if grant_start:
            pub_date = grant_start
        elif fiscal_year:
            pub_date = date(fiscal_year, 1, 1)
        else:
            pub_date = date.today()

        source_url = f"https://reporter.nih.gov/project-details/{project_num}"

        return GrantDocument(
            intervention=intervention.lower(),
            intervention_aliases=aliases or [],
            title=title,
            abstract=abstract,
            source_url=source_url,
            date_published=pub_date,
            project_number=project_num,
            pi_name=pi_name or None,
            organisation=org_name or None,
            total_funding=float(award_amount) if award_amount else None,
            fiscal_year=fiscal_year,
            grant_start=grant_start,
            grant_end=grant_end,
            funding_mechanism=funding_mechanism,
            nih_institute=nih_institute,
            raw_response=project,
        )


def _parse_nih_date(date_str: str | None) -> date | None:
    """Parse NIH Reporter date (ISO format or similar)."""
    if not date_str:
        return None
    try:
        # Format: "2024-01-15T00:00:00" or "2024-01-15"
        clean = date_str[:10]
        parts = clean.split("-")
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        return None
