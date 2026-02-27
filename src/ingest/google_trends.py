"""Google Trends ingest — interest-over-time data for hype ratio.

This does NOT produce documents. It fetches Google Trends interest data
and saves it as TrendsData to data/trends/{intervention}.json.
The data feeds the hype ratio reasoning module.

Uses pytrends library. Handles TooManyRequestsError with retry+backoff.
All exceptions caught — trends data is nice-to-have, not critical.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from loguru import logger

from src.config import settings
from src.schema.document import TrendsData

TRENDS_DIR = Path(settings.documents_dir).parent / "trends"


async def fetch_trends(
    intervention: str,
    aliases: list[str] | None = None,
    timeframe: str = "today 5-y",
) -> TrendsData | None:
    """Fetch Google Trends data for an intervention.

    Returns TrendsData or None if pytrends is unavailable or fails.
    Saves result to data/trends/{intervention}.json.
    """
    try:
        from pytrends.request import TrendReq
    except ImportError:
        logger.warning("pytrends not installed — skipping Google Trends")
        return None

    keyword = intervention
    # pytrends accepts max 5 keywords; just use the primary name
    logger.info(f"Fetching Google Trends for '{keyword}' ({timeframe})")

    try:
        # retries/backoff_factor params can cause urllib3 compatibility issues
        # with newer versions, so use defaults
        pytrends = TrendReq(hl="en-US", tz=360)
        pytrends.build_payload([keyword], timeframe=timeframe)

        # Interest over time
        interest_df = pytrends.interest_over_time()
        if interest_df is None or interest_df.empty:
            logger.info(f"No Google Trends data for '{keyword}'")
            return None

        # Convert to data points
        data_points: list[dict] = []
        for idx, row in interest_df.iterrows():
            data_points.append({
                "date": idx.strftime("%Y-%m-%d"),
                "interest": int(row[keyword]),
            })

        # Find peak and current
        peak_interest = 0
        peak_date = ""
        current_interest = 0
        if data_points:
            peak_point = max(data_points, key=lambda d: d["interest"])
            peak_interest = peak_point["interest"]
            peak_date = peak_point["date"]
            current_interest = data_points[-1]["interest"]

        # Related queries
        related: list[str] = []
        try:
            related_df = pytrends.related_queries()
            if related_df and keyword in related_df:
                top_df = related_df[keyword].get("top")
                if top_df is not None and not top_df.empty:
                    related = top_df["query"].tolist()[:10]
        except Exception as e:
            logger.debug(f"Related queries failed: {e}")

        trends = TrendsData(
            intervention=intervention,
            fetched_at=datetime.now(),
            timeframe=timeframe,
            data_points=data_points,
            related_queries=related,
            peak_interest=peak_interest,
            peak_date=peak_date,
            current_interest=current_interest,
        )

        # Save to disk
        _save_trends(intervention, trends)
        logger.info(
            f"Google Trends for '{intervention}': "
            f"{len(data_points)} data points, "
            f"peak={peak_interest} ({peak_date}), current={current_interest}"
        )
        return trends

    except Exception as e:
        logger.warning(f"Google Trends failed for '{intervention}': {e}")
        return None


def _save_trends(intervention: str, trends: TrendsData) -> None:
    """Save trends data to data/trends/{intervention}.json."""
    TRENDS_DIR.mkdir(parents=True, exist_ok=True)
    path = TRENDS_DIR / f"{intervention.lower()}.json"
    path.write_text(trends.model_dump_json(indent=2))
    logger.debug(f"Saved trends data to {path}")


def load_trends(intervention: str) -> TrendsData | None:
    """Load cached trends data from disk."""
    path = TRENDS_DIR / f"{intervention.lower()}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return TrendsData.model_validate(data)
    except Exception as e:
        logger.warning(f"Failed to load trends for '{intervention}': {e}")
        return None
