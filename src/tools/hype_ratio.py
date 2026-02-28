"""
Social hype scoring: Reddit entries from data/documents/{intervention}.json
and Google Trends from data/trends/{intervention}.json.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .intervention_resolver import _project_root, find_document_path, find_trends_path


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def get_reddit_entries(intervention_name: str, data_dir: Path | None = None) -> list[dict[str, Any]]:
    """
    Load data/documents/{intervention}.json and return documents where
    source_type == 'social' and (platform == 'reddit' or 'subreddit' in doc).
    """
    path = find_document_path(intervention_name, data_dir)
    data = _load_json(path) if path else None
    if not data:
        return []
    docs = data.get("documents") or []
    out = []
    for d in docs:
        if not isinstance(d, dict):
            continue
        st = (d.get("source_type") or "").lower()
        if st != "social":
            continue
        if (d.get("platform") or "").lower() == "reddit" or "subreddit" in d:
            out.append(d)
    return out


def get_trends_data(intervention_name: str, data_dir: Path | None = None) -> dict[str, Any] | None:
    """Load data/trends/{intervention}.json (Google Trends interest over time)."""
    path = find_trends_path(intervention_name, data_dir)
    return _load_json(path) if path else None


def score_social_hype(
    intervention_name: str,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    """
    Score social hype for the intervention using:
    - Reddit: count of entries, subreddits mentioned
    - Trends: mean interest, trend (recent vs older), max interest
    Returns a dict with score (0-100), summary text, reddit_count, trends_summary.
    """
    reddit = get_reddit_entries(intervention_name, data_dir)
    trends = get_trends_data(intervention_name, data_dir)

    reddit_count = len(reddit)
    subreddits = list({str(d.get("subreddit", "")).strip() for d in reddit if d.get("subreddit")})

    score = 0.0
    parts = []

    # Reddit component (e.g. up to 50 points): more posts + more subreddits = more hype
    if reddit_count > 0:
        r_score = min(50.0, 10.0 + reddit_count * 1.5 + len(subreddits) * 2.0)
        score += r_score
        parts.append(f"Reddit: {reddit_count} posts across {len(subreddits)} subreddit(s): {', '.join(subreddits[:5]) or 'N/A'}{'...' if len(subreddits) > 5 else ''}.")
    else:
        parts.append("Reddit: no Reddit entries found in the documents corpus.")

    # Trends component (e.g. up to 50 points): mean interest and trend
    if trends and isinstance(trends.get("data_points"), list):
        pts = trends["data_points"]
        if pts:
            interests = [p.get("interest", 0) for p in pts if isinstance(p.get("interest"), (int, float))]
            if interests:
                mean_interest = sum(interests) / len(interests)
                recent = interests[-min(12, len(interests)):] if len(interests) >= 12 else interests
                older = interests[:-len(recent)] if len(interests) > len(recent) else []
                recent_avg = sum(recent) / len(recent) if recent else 0
                older_avg = sum(older) / len(older) if older else recent_avg
                trend_up = recent_avg > older_avg
                t_score = min(50.0, (mean_interest / 100.0) * 25.0 + (30.0 if trend_up else 10.0))
                score += t_score
                parts.append(
                    f"Google Trends: mean interest {mean_interest:.1f}, "
                    f"recent {'higher' if trend_up else 'lower'} than earlier period."
                )
            else:
                parts.append("Google Trends: no interest values in data_points.")
        else:
            parts.append("Google Trends: empty data_points.")
    else:
        parts.append("Google Trends: no trends file or data for this intervention.")

    summary = " ".join(parts)
    return {
        "intervention": intervention_name,
        "hype_score": round(min(100.0, score), 1),
        "reddit_count": reddit_count,
        "subreddits": subreddits,
        "trends_available": bool(trends and (trends.get("data_points") or [])),
        "summary": summary,
    }
