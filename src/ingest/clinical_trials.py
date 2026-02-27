"""ClinicalTrials.gov v2 API ingest agent.

Queries the v2 API for aging-related trials matching an intervention,
parses the JSON response, and returns typed ClinicalTrialDocument objects
with full temporal lifecycle data.

Filtering: prioritizes trials with aging-related conditions, deprioritizes
pure oncology/transplant trials without aging endpoints.
"""

from __future__ import annotations

from datetime import date

import httpx
from loguru import logger

from src.config import AGING_RELEVANCE_TERMS
from src.ingest.base import BaseIngestAgent
from src.ingest.query_expander import QueryExpansion
from src.schema.document import ClinicalTrialDocument, Document

CT_API_BASE = "https://clinicaltrials.gov/api/v2/studies"


def _score_trial(study: dict) -> int:
    """Score a trial by relevance to aging research."""
    score = 0
    protocol = study.get("protocolSection", {})
    conditions = protocol.get("conditionsModule", {}).get("conditions", [])
    ident = protocol.get("identificationModule", {})
    title = (ident.get("officialTitle") or "") + " " + (ident.get("briefTitle") or "")
    desc = protocol.get("descriptionModule", {}).get("briefSummary", "") or ""
    text = f"{title} {desc} {' '.join(conditions)}".lower()

    outcomes = protocol.get("outcomesModule", {})
    primary = " ".join(o.get("measure", "") for o in outcomes.get("primaryOutcomes", []))
    text += f" {primary}".lower()

    # +3 for aging-related terms in conditions/description/outcomes
    if any(term in text for term in AGING_RELEVANCE_TERMS):
        score += 3

    # +2 for completed status (has data)
    status = protocol.get("statusModule", {}).get("overallStatus", "").lower()
    if status in ("completed", "has results"):
        score += 2

    # +1 for phase 2/3
    phases = protocol.get("designModule", {}).get("phases", [])
    phase_str = " ".join(phases).lower()
    if "phase 3" in phase_str or "phase 2" in phase_str:
        score += 1

    # -2 if no aging-related terms anywhere (intervention-agnostic)
    if not any(term in text for term in AGING_RELEVANCE_TERMS):
        score -= 2

    return score


class ClinicalTrialsAgent(BaseIngestAgent):
    @property
    def source_name(self) -> str:
        return "ClinicalTrials.gov"

    async def ingest(
        self,
        intervention: str,
        aliases: list[str] | None = None,
        query_expansion: QueryExpansion | None = None,
        max_results: int = 50,
    ) -> list[Document]:
        # Build a search query using intervention terms
        terms = [intervention] + (aliases or [])
        if query_expansion:
            terms.extend(query_expansion.synonyms)
        # Use query.term for broad matching (query.intr is too restrictive)
        search_query = " OR ".join(terms)
        logger.info(f"ClinicalTrials.gov search: {search_query}")

        async with httpx.AsyncClient(timeout=30.0) as client:
            # Fetch a larger candidate pool for filtering
            candidate_pool = max(max_results * 3, 100)
            studies = await self._search_studies(search_query, candidate_pool, client)

        if not studies:
            logger.info("No ClinicalTrials.gov results found")
            return []

        logger.info(f"ClinicalTrials.gov: {len(studies)} candidate studies")

        # Score and rank studies by aging relevance
        scored = [(s, _score_trial(s)) for s in studies]
        scored.sort(key=lambda x: x[1], reverse=True)
        top_studies = scored[:max_results]
        if top_studies:
            logger.info(
                f"CT.gov scoring: keeping top {len(top_studies)} "
                f"(scores: {top_studies[0][1]} to {top_studies[-1][1]})"
            )

        docs: list[Document] = []
        for study, _score in top_studies:
            parsed = self._parse_study(study)
            if not parsed:
                continue
            source_url = parsed["source_url"]
            if self.storage.document_exists(intervention, source_url):
                continue
            try:
                doc = ClinicalTrialDocument(
                    intervention=intervention.lower(),
                    intervention_aliases=aliases or [],
                    nct_id=parsed["nct_id"],
                    title=parsed["title"],
                    abstract=parsed.get("brief_summary", ""),
                    source_url=source_url,
                    date_published=parsed.get("date_published", date.today()),
                    phase=parsed.get("phase"),
                    status=parsed.get("status"),
                    enrollment=parsed.get("enrollment"),
                    sponsor=parsed.get("sponsor"),
                    conditions=parsed.get("conditions", []),
                    primary_outcomes=parsed.get("primary_outcomes", []),
                    results_summary=parsed.get("results_summary"),
                    date_registered=parsed.get("date_registered"),
                    date_started=parsed.get("date_started"),
                    date_completed=parsed.get("date_completed"),
                    date_results_posted=parsed.get("date_results_posted"),
                    raw_response=study,
                )
                docs.append(doc)
            except Exception as e:
                logger.warning(f"Failed to build ClinicalTrialDocument for {parsed.get('nct_id')}: {e}")

        logger.info(f"ClinicalTrials.gov: {len(docs)} new documents for '{intervention}'")
        return docs

    async def _search_studies(
        self,
        search_query: str,
        max_results: int,
        client: httpx.AsyncClient,
    ) -> list[dict]:
        """Query the v2 API. Handles pagination via nextPageToken."""
        all_studies: list[dict] = []
        page_token: str | None = None

        while len(all_studies) < max_results:
            params: dict = {
                "query.term": search_query,
                "pageSize": min(max_results - len(all_studies), 100),
                "format": "json",
            }
            if page_token:
                params["pageToken"] = page_token

            try:
                resp = await client.get(CT_API_BASE, params=params)
                logger.debug(f"CT.gov API URL: {resp.url}")
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.error(f"ClinicalTrials.gov API error: {e}")
                break

            studies = data.get("studies", [])
            if not studies:
                break
            all_studies.extend(studies)

            page_token = data.get("nextPageToken")
            if not page_token:
                break

        return all_studies[:max_results]

    @staticmethod
    def _parse_study(study: dict) -> dict | None:
        """Parse a single study JSON from the v2 API."""
        try:
            protocol = study.get("protocolSection", {})
            ident = protocol.get("identificationModule", {})
            desc = protocol.get("descriptionModule", {})
            status_mod = protocol.get("statusModule", {})
            design = protocol.get("designModule", {})
            outcomes = protocol.get("outcomesModule", {})
            sponsor_mod = protocol.get("sponsorCollaboratorsModule", {})
            conditions_mod = protocol.get("conditionsModule", {})
            results = study.get("resultsSection", {})

            nct_id = ident.get("nctId", "")
            if not nct_id:
                return None

            # Phase — may be a list
            phases = design.get("phases", [])
            phase = phases[0] if phases else None

            # Primary outcomes
            primary_outcomes = []
            for outcome in outcomes.get("primaryOutcomes", []):
                measure = outcome.get("measure", "")
                if measure:
                    primary_outcomes.append(measure)

            # Results summary
            results_summary = None
            if results:
                flow = results.get("participantFlowModule", {})
                if flow:
                    results_summary = f"Enrollment: {flow.get('recruitmentDetails', 'N/A')}"

            return {
                "nct_id": nct_id,
                "title": ident.get("officialTitle") or ident.get("briefTitle", ""),
                "brief_summary": desc.get("briefSummary", ""),
                "status": status_mod.get("overallStatus"),
                "phase": phase,
                "enrollment": design.get("enrollmentInfo", {}).get("count"),
                "sponsor": sponsor_mod.get("leadSponsor", {}).get("name"),
                "conditions": conditions_mod.get("conditions", []),
                "primary_outcomes": primary_outcomes,
                "results_summary": results_summary,
                "source_url": f"https://clinicaltrials.gov/study/{nct_id}",
                # Temporal dates
                "date_published": _parse_ct_date(
                    status_mod.get("studyFirstSubmitDate")
                    or (status_mod.get("startDateStruct", {}).get("date"))
                ),
                "date_registered": _parse_ct_date(status_mod.get("studyFirstSubmitDate")),
                "date_started": _parse_ct_date(
                    status_mod.get("startDateStruct", {}).get("date")
                ),
                "date_completed": _parse_ct_date(
                    status_mod.get("completionDateStruct", {}).get("date")
                    or status_mod.get("primaryCompletionDateStruct", {}).get("date")
                ),
                "date_results_posted": _parse_ct_date(
                    status_mod.get("resultsFirstSubmitDate")
                ),
            }
        except Exception as e:
            logger.warning(f"Failed to parse CT.gov study: {e}")
            return None


def _parse_ct_date(date_str: str | None) -> date | None:
    """Parse ClinicalTrials.gov date (YYYY-MM-DD, YYYY-MM, or YYYY)."""
    if not date_str:
        return None
    try:
        parts = date_str.split("-")
        year = int(parts[0])
        month = int(parts[1]) if len(parts) > 1 else 1
        day = int(parts[2]) if len(parts) > 2 else 1
        return date(year, month, day)
    except (ValueError, IndexError):
        return None
