"""Evidence trajectory scorer — research momentum analysis.

Computes publication velocity, acceleration, source diversification,
trial pipeline progression, and an overall momentum score for an
aging intervention. Pure computation — no LLM calls.

Called by:
  - MCP server: get_evidence_trajectory (via _run_tool_cached → discover_tools)
  - API: GET /tools/trajectory/{intervention}
"""

from __future__ import annotations

import json
import math
import sqlite3
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import BaseModel

from src.config import settings
from src.stats.summary import generate_summary
from src.storage.manager import StorageManager


# ── Pydantic result models ──────────────────────────────────────────────────


class VelocityMetrics(BaseModel):
    """Publication velocity: docs per year, recent vs historical."""

    recent_years: list[int]
    historical_years: list[int]
    publications_per_year_recent: float
    publications_per_year_historical: float
    acceleration_factor: float | None  # recent / historical (None if no history)


class DiversificationMetrics(BaseModel):
    """Source type diversification over time."""

    total_source_types: int
    recent_source_types: list[str]
    historical_source_types: list[str]
    new_source_types: list[str]  # in recent but not historical
    shannon_entropy: float
    max_entropy: float
    diversity_ratio: float  # shannon / max (0-1)


class TrialPipelineMetrics(BaseModel):
    """Clinical trial pipeline progression."""

    total_trials: int
    by_phase: dict[str, int]
    by_status: dict[str, int]
    completed_with_results: int
    highest_phase: str | None
    avg_days_to_completion: float | None
    pipeline_score: float  # 0-1


class YearlyCounts(BaseModel):
    """Plot-ready yearly time series."""

    years: list[int]
    total: list[int]
    by_source: dict[str, list[int]]


class CumulativeCounts(BaseModel):
    """Plot-ready cumulative time series."""

    years: list[int]
    total: list[int]


class TrialPhaseSeries(BaseModel):
    """Plot-ready trial phase time series (trials registered per year by phase)."""

    years: list[int]
    by_phase: dict[str, list[int]]


class TrendsOverlay(BaseModel):
    """Plot-ready Google Trends overlay data."""

    dates: list[str]
    interest: list[int]


class TrajectoryResult(BaseModel):
    """Complete trajectory analysis result."""

    intervention: str
    generated_at: str
    total_documents: int
    data_quality: str  # sufficient | limited | insufficient

    # Core metrics
    phase: str  # emerging | accelerating | mature | stagnant | declining | insufficient_data
    momentum_score: float | None  # 0-1, None if insufficient

    # Detailed metrics
    velocity: VelocityMetrics | None
    diversification: DiversificationMetrics | None
    trial_pipeline: TrialPipelineMetrics | None

    # Plot-ready time series
    yearly_counts: YearlyCounts | None
    cumulative: CumulativeCounts | None
    trial_phases: TrialPhaseSeries | None
    trends_overlay: TrendsOverlay | None


# ── Main function ───────────────────────────────────────────────────────────


def score_trajectory(intervention: str, storage: StorageManager) -> TrajectoryResult:
    """Compute evidence trajectory for an intervention.

    Args:
        intervention: Canonical intervention name (lowercase).
        storage: StorageManager instance.

    Returns:
        TrajectoryResult with metrics and plot-ready arrays.
    """
    # Step 1: Load summary
    summary = generate_summary(intervention)
    if not summary or summary.get("total_documents", 0) == 0:
        return _insufficient_data_result(intervention)

    total_docs = summary["total_documents"]
    by_year: dict[str, int] = summary.get("by_year", {})

    # Step 2: Data sufficiency
    if total_docs < 5:
        return _insufficient_data_result(intervention)

    data_quality = "sufficient" if total_docs >= 30 else "limited"

    # Step 3: Year-by-source breakdown from documents
    docs = storage.get_documents(intervention)
    year_source: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for doc in docs:
        yr = doc.date_published.year
        st = doc.source_type.value
        year_source[yr][st] += 1

    # Step 4: Velocity
    current_year = date.today().year
    all_years = sorted(int(y) for y in by_year.keys())
    completed_years = [y for y in all_years if y < current_year]

    if len(completed_years) >= 2:
        recent_years = completed_years[-2:]
    elif completed_years:
        recent_years = completed_years[-1:]
    else:
        recent_years = []

    historical_years = [y for y in completed_years if y not in recent_years]

    recent_total = sum(by_year.get(str(y), 0) for y in recent_years)
    historical_total = sum(by_year.get(str(y), 0) for y in historical_years)

    pubs_recent = recent_total / len(recent_years) if recent_years else 0.0
    pubs_historical = historical_total / len(historical_years) if historical_years else 0.0

    acceleration_factor: float | None = None
    if pubs_historical > 0:
        acceleration_factor = round(pubs_recent / pubs_historical, 2)

    velocity = VelocityMetrics(
        recent_years=recent_years,
        historical_years=historical_years,
        publications_per_year_recent=round(pubs_recent, 1),
        publications_per_year_historical=round(pubs_historical, 1),
        acceleration_factor=acceleration_factor,
    )

    # Step 5: Diversification
    recent_set: set[str] = set()
    historical_set: set[str] = set()
    source_counts: Counter[str] = Counter()
    for yr, sources in year_source.items():
        for st, cnt in sources.items():
            source_counts[st] += cnt
            if yr in recent_years or yr == current_year:
                recent_set.add(st)
            else:
                historical_set.add(st)

    new_sources = sorted(recent_set - historical_set)
    n_sources = len(source_counts)
    total_all = sum(source_counts.values())

    entropy = 0.0
    if total_all > 0 and n_sources > 1:
        for count in source_counts.values():
            p = count / total_all
            if p > 0:
                entropy -= p * math.log2(p)

    max_entropy = math.log2(n_sources) if n_sources > 1 else 1.0
    diversity_ratio = entropy / max_entropy if max_entropy > 0 else 0.0

    diversification = DiversificationMetrics(
        total_source_types=n_sources,
        recent_source_types=sorted(recent_set),
        historical_source_types=sorted(historical_set),
        new_source_types=new_sources,
        shannon_entropy=round(entropy, 3),
        max_entropy=round(max_entropy, 3),
        diversity_ratio=round(diversity_ratio, 3),
    )

    # Step 6: Trial pipeline
    trials_data = summary.get("clinical_trials", {})
    trial_count = trials_data.get("count", 0)
    trial_pipeline: TrialPipelineMetrics | None = None
    pipeline_score: float | None = None

    if trial_count > 0:
        by_phase = trials_data.get("by_phase", {})
        by_status = trials_data.get("by_status", {})
        with_results = trials_data.get("with_results", 0)

        phase_order = ["EARLY_PHASE1", "PHASE1", "PHASE2", "PHASE3", "PHASE4"]
        highest = None
        for p in reversed(phase_order):
            if by_phase.get(p, 0) > 0:
                highest = p
                break

        avg_days = _compute_avg_trial_duration(intervention)
        pipeline_score = _compute_pipeline_score(
            by_phase, by_status, with_results, trial_count
        )

        trial_pipeline = TrialPipelineMetrics(
            total_trials=trial_count,
            by_phase=by_phase,
            by_status=by_status,
            completed_with_results=with_results,
            highest_phase=highest,
            avg_days_to_completion=avg_days,
            pipeline_score=pipeline_score,
        )

    # Step 7: Classify phase
    phase = _classify_phase(
        total_docs=total_docs,
        acceleration_factor=acceleration_factor,
        pubs_per_year_recent=pubs_recent,
        diversity_ratio=diversity_ratio,
        all_years=all_years,
        by_year=by_year,
        current_year=current_year,
    )

    # Step 8: Momentum score
    momentum = _compute_momentum(
        pubs_per_year_recent=pubs_recent,
        acceleration_factor=acceleration_factor,
        diversity_ratio=diversity_ratio,
        pipeline_score=pipeline_score,
    )

    # Step 9: Plot-ready arrays
    yearly_counts = _build_yearly_counts(all_years, by_year, year_source)
    cumulative = _build_cumulative(yearly_counts)

    # Step 10: Trial phase series
    trial_phases = _build_trial_phase_series(intervention) if trial_count > 0 else None

    # Step 11: Google Trends overlay
    trends_overlay = _load_trends_overlay(intervention)

    return TrajectoryResult(
        intervention=intervention,
        generated_at=date.today().isoformat(),
        total_documents=total_docs,
        data_quality=data_quality,
        phase=phase,
        momentum_score=momentum,
        velocity=velocity,
        diversification=diversification,
        trial_pipeline=trial_pipeline,
        yearly_counts=yearly_counts,
        cumulative=cumulative,
        trial_phases=trial_phases,
        trends_overlay=trends_overlay,
    )


# ── Helpers ─────────────────────────────────────────────────────────────────


def _insufficient_data_result(intervention: str) -> TrajectoryResult:
    return TrajectoryResult(
        intervention=intervention,
        generated_at=date.today().isoformat(),
        total_documents=0,
        data_quality="insufficient",
        phase="insufficient_data",
        momentum_score=None,
        velocity=None,
        diversification=None,
        trial_pipeline=None,
        yearly_counts=None,
        cumulative=None,
        trial_phases=None,
        trends_overlay=None,
    )


def _classify_phase(
    total_docs: int,
    acceleration_factor: float | None,
    pubs_per_year_recent: float,
    diversity_ratio: float,
    all_years: list[int],
    by_year: dict[str, int],
    current_year: int,
) -> str:
    """Classify the intervention's research phase.

    Priority order (first match wins):
    1. Emerging: < 20 total docs AND recent velocity > 0
    2. Declining: acceleration < 0.5 AND last 3 years trending down
    3. Stagnant: acceleration < 0.8 AND low diversity
    4. Accelerating: acceleration > 1.5 AND not declining trend
    5. Mature: > 100 docs AND steady velocity AND diverse
    6. Fallback based on acceleration direction
    """
    # 3-year trend direction
    completed = [y for y in all_years if y < current_year]
    last_3 = completed[-3:] if len(completed) >= 3 else completed
    trend_values = [by_year.get(str(y), 0) for y in last_3]
    declining_trend = len(trend_values) >= 2 and trend_values[-1] < trend_values[0]

    if total_docs < 20 and pubs_per_year_recent > 0:
        return "emerging"

    if acceleration_factor is not None:
        if acceleration_factor < 0.5 and declining_trend:
            return "declining"
        if acceleration_factor < 0.8 and diversity_ratio < 0.4:
            return "stagnant"
        if acceleration_factor > 1.5 and not declining_trend:
            return "accelerating"

    if total_docs > 100 and diversity_ratio > 0.5:
        if acceleration_factor is None or 0.8 <= acceleration_factor <= 1.5:
            return "mature"

    # Fallback
    if acceleration_factor is not None and acceleration_factor > 1.0:
        return "accelerating"
    return "stagnant"


def _compute_momentum(
    pubs_per_year_recent: float,
    acceleration_factor: float | None,
    diversity_ratio: float,
    pipeline_score: float | None,
) -> float:
    """Compute composite momentum score (0-1)."""
    # Velocity: sigmoid-like, 25 docs/year → ~1.0
    velocity_score = min(1.0, pubs_per_year_recent / 25.0)

    # Acceleration: sigmoid mapping, 1.0 → 0.5, 2.0 → ~0.8, 3.0+ → ~1.0
    if acceleration_factor is not None:
        accel_score = 1.0 / (1.0 + math.exp(-1.5 * (acceleration_factor - 1.0)))
    else:
        accel_score = 0.5  # neutral

    div_score = diversity_ratio

    if pipeline_score is not None:
        momentum = (
            0.40 * velocity_score
            + 0.25 * accel_score
            + 0.20 * div_score
            + 0.15 * pipeline_score
        )
    else:
        # Renormalize without trial pipeline
        momentum = 0.47 * velocity_score + 0.29 * accel_score + 0.24 * div_score

    return round(max(0.0, min(1.0, momentum)), 3)


def _compute_pipeline_score(
    by_phase: dict[str, int],
    by_status: dict[str, int],
    with_results: int,
    total_trials: int,
) -> float:
    """Compute a 0-1 pipeline score from trial data."""
    if total_trials == 0:
        return 0.0

    phase_weights = {
        "EARLY_PHASE1": 0.1,
        "PHASE1": 0.2,
        "PHASE2": 0.4,
        "PHASE3": 0.7,
        "PHASE4": 0.9,
        "NA": 0.15,
        "Unknown": 0.1,
    }

    weighted_sum = 0.0
    counted = 0
    for phase, count in by_phase.items():
        w = phase_weights.get(phase, 0.1)
        weighted_sum += w * count
        counted += count

    phase_score = weighted_sum / counted if counted > 0 else 0.0

    completed = by_status.get("COMPLETED", 0)
    completion_ratio = completed / total_trials

    results_ratio = with_results / total_trials

    score = 0.50 * phase_score + 0.30 * completion_ratio + 0.20 * results_ratio
    return round(min(1.0, score), 3)


def _compute_avg_trial_duration(intervention: str) -> float | None:
    """Average days from registered to completed for finished trials."""
    db_path = str(settings.sqlite_path)
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cursor = conn.execute(
            """
            SELECT AVG(julianday(date_completed) - julianday(date_registered))
            FROM documents
            WHERE intervention = ?
              AND source_type = 'clinicaltrials'
              AND date_registered IS NOT NULL
              AND date_completed IS NOT NULL
              AND date_completed > date_registered
            """,
            (intervention,),
        )
        row = cursor.fetchone()
        conn.close()
        if row and row[0] is not None:
            return round(row[0], 1)
    except Exception as e:
        logger.warning(f"Trial duration query failed: {e}")
    return None


def _build_yearly_counts(
    all_years: list[int],
    by_year: dict[str, int],
    year_source: dict[int, dict[str, int]],
) -> YearlyCounts:
    """Build plot-ready yearly count arrays with contiguous year range."""
    if not all_years:
        return YearlyCounts(years=[], total=[], by_source={})

    year_range = list(range(min(all_years), max(all_years) + 1))
    totals = [by_year.get(str(y), 0) for y in year_range]

    all_sources: set[str] = set()
    for sources in year_source.values():
        all_sources.update(sources.keys())

    by_source: dict[str, list[int]] = {}
    for st in sorted(all_sources):
        by_source[st] = [year_source.get(y, {}).get(st, 0) for y in year_range]

    return YearlyCounts(years=year_range, total=totals, by_source=by_source)


def _build_cumulative(yearly: YearlyCounts) -> CumulativeCounts:
    """Build cumulative sum from yearly totals."""
    cumulative: list[int] = []
    running = 0
    for t in yearly.total:
        running += t
        cumulative.append(running)
    return CumulativeCounts(years=yearly.years, total=cumulative)


def _build_trial_phase_series(intervention: str) -> TrialPhaseSeries | None:
    """Build trial-phase-by-year series from SQLite."""
    db_path = str(settings.sqlite_path)
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cursor = conn.execute(
            """
            SELECT strftime('%Y', COALESCE(date_registered, date_published)) as yr,
                   phase, COUNT(*) as cnt
            FROM documents
            WHERE intervention = ? AND source_type = 'clinicaltrials' AND phase IS NOT NULL
            GROUP BY yr, phase
            ORDER BY yr
            """,
            (intervention,),
        )
        rows = cursor.fetchall()
        conn.close()
    except Exception as e:
        logger.warning(f"Trial phase series query failed: {e}")
        return None

    if not rows:
        return None

    year_phase: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    all_phases: set[str] = set()
    for yr_str, phase, cnt in rows:
        if yr_str:
            yr = int(yr_str)
            year_phase[yr][phase] += cnt
            all_phases.add(phase)

    if not year_phase:
        return None

    year_range = list(range(min(year_phase), max(year_phase) + 1))
    by_phase: dict[str, list[int]] = {}
    for p in sorted(all_phases):
        by_phase[p] = [year_phase.get(y, {}).get(p, 0) for y in year_range]

    return TrialPhaseSeries(years=year_range, by_phase=by_phase)


def _load_trends_overlay(intervention: str) -> TrendsOverlay | None:
    """Load Google Trends data as plot-ready arrays."""
    trends_path = settings.documents_dir.parent / "trends" / f"{intervention}.json"
    if not trends_path.exists():
        return None
    try:
        data = json.loads(trends_path.read_text())
        points = data.get("data_points", [])
        if not points:
            return None
        return TrendsOverlay(
            dates=[p["date"] for p in points],
            interest=[p["interest"] for p in points],
        )
    except Exception as e:
        logger.warning(f"Failed to load trends for trajectory: {e}")
        return None
