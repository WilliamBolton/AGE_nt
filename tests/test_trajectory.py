"""Tests for the evidence trajectory scorer."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.tools.trajectory import (
    TrajectoryResult,
    _classify_phase,
    _compute_momentum,
    _compute_pipeline_score,
    score_trajectory,
)

# ── Helpers ──────────────────────────────────────────────────────────────────

CURRENT_YEAR = date.today().year


def _make_mock_storage(docs: list | None = None) -> MagicMock:
    """Create a mock StorageManager returning the given docs."""
    storage = MagicMock()
    storage.get_documents.return_value = docs or []
    return storage


def _make_mock_doc(year: int, source_type: str = "pubmed") -> MagicMock:
    """Create a minimal mock Document."""
    doc = MagicMock()
    doc.date_published = date(year, 6, 15)
    doc.source_type.value = source_type
    return doc


def _make_summary(
    total: int,
    by_year: dict[str, int],
    clinical_trials: dict | None = None,
) -> dict:
    """Create a minimal summary dict."""
    return {
        "intervention": "test",
        "total_documents": total,
        "by_year": by_year,
        "by_source_type": {"pubmed": total},
        "clinical_trials": clinical_trials or {"count": 0},
    }


# ── Phase classification tests ──────────────────────────────────────────────


class TestClassifyPhase:
    def test_emerging(self):
        phase = _classify_phase(
            total_docs=12,
            acceleration_factor=2.0,
            pubs_per_year_recent=5.0,
            diversity_ratio=0.3,
            all_years=[2023, 2024, 2025],
            by_year={"2023": 2, "2024": 4, "2025": 6},
            current_year=CURRENT_YEAR,
        )
        assert phase == "emerging"

    def test_declining(self):
        phase = _classify_phase(
            total_docs=80,
            acceleration_factor=0.3,
            pubs_per_year_recent=3.0,
            diversity_ratio=0.6,
            all_years=[2020, 2021, 2022, 2023, 2024, 2025],
            by_year={"2020": 20, "2021": 18, "2022": 15, "2023": 12, "2024": 5, "2025": 3},
            current_year=CURRENT_YEAR,
        )
        assert phase == "declining"

    def test_stagnant(self):
        phase = _classify_phase(
            total_docs=50,
            acceleration_factor=0.6,
            pubs_per_year_recent=3.0,
            diversity_ratio=0.2,
            all_years=[2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025],
            by_year={"2018": 5, "2019": 6, "2020": 7, "2021": 8, "2022": 7, "2023": 6, "2024": 4, "2025": 3},
            current_year=CURRENT_YEAR,
        )
        assert phase == "stagnant"

    def test_accelerating(self):
        phase = _classify_phase(
            total_docs=60,
            acceleration_factor=2.5,
            pubs_per_year_recent=20.0,
            diversity_ratio=0.7,
            all_years=[2020, 2021, 2022, 2023, 2024, 2025],
            by_year={"2020": 5, "2021": 6, "2022": 8, "2023": 12, "2024": 18, "2025": 25},
            current_year=CURRENT_YEAR,
        )
        assert phase == "accelerating"

    def test_mature(self):
        phase = _classify_phase(
            total_docs=200,
            acceleration_factor=1.1,
            pubs_per_year_recent=25.0,
            diversity_ratio=0.85,
            all_years=list(range(2010, CURRENT_YEAR)),
            by_year={str(y): 15 for y in range(2010, CURRENT_YEAR)},
            current_year=CURRENT_YEAR,
        )
        assert phase == "mature"


# ── Momentum score tests ────────────────────────────────────────────────────


class TestMomentum:
    def test_bounds_high(self):
        score = _compute_momentum(50.0, 5.0, 1.0, 1.0)
        assert 0.0 <= score <= 1.0

    def test_bounds_low(self):
        score = _compute_momentum(0.0, 0.1, 0.0, 0.0)
        assert 0.0 <= score <= 1.0

    def test_no_pipeline(self):
        score = _compute_momentum(10.0, 1.5, 0.7, None)
        assert 0.0 <= score <= 1.0

    def test_no_acceleration(self):
        score = _compute_momentum(10.0, None, 0.5, None)
        assert 0.0 <= score <= 1.0

    def test_higher_velocity_means_higher_score(self):
        low = _compute_momentum(5.0, 1.0, 0.5, None)
        high = _compute_momentum(20.0, 1.0, 0.5, None)
        assert high > low

    def test_higher_acceleration_means_higher_score(self):
        low = _compute_momentum(10.0, 0.5, 0.5, None)
        high = _compute_momentum(10.0, 3.0, 0.5, None)
        assert high > low


# ── Pipeline score tests ────────────────────────────────────────────────────


class TestPipelineScore:
    def test_empty(self):
        assert _compute_pipeline_score({}, {}, 0, 0) == 0.0

    def test_phase3_with_results(self):
        score = _compute_pipeline_score(
            by_phase={"PHASE3": 5, "PHASE2": 3},
            by_status={"COMPLETED": 6, "RECRUITING": 2},
            with_results=4,
            total_trials=8,
        )
        assert 0.0 < score <= 1.0

    def test_bounds(self):
        score = _compute_pipeline_score(
            by_phase={"PHASE4": 10},
            by_status={"COMPLETED": 10},
            with_results=10,
            total_trials=10,
        )
        assert 0.0 <= score <= 1.0


# ── Integration tests ───────────────────────────────────────────────────────


class TestScoreTrajectory:
    @patch("src.tools.trajectory.generate_summary")
    @patch("src.tools.trajectory._load_trends_overlay", return_value=None)
    @patch("src.tools.trajectory._build_trial_phase_series", return_value=None)
    @patch("src.tools.trajectory._compute_avg_trial_duration", return_value=None)
    def test_insufficient_data(self, _dur, _trials, _trends, mock_summary):
        mock_summary.return_value = {"total_documents": 3, "by_year": {"2024": 3}}
        storage = _make_mock_storage([_make_mock_doc(2024)])
        result = score_trajectory("test", storage)
        assert result.phase == "insufficient_data"
        assert result.momentum_score is None

    @patch("src.tools.trajectory.generate_summary")
    @patch("src.tools.trajectory._load_trends_overlay", return_value=None)
    @patch("src.tools.trajectory._build_trial_phase_series", return_value=None)
    @patch("src.tools.trajectory._compute_avg_trial_duration", return_value=None)
    def test_basic_trajectory(self, _dur, _trials, _trends, mock_summary):
        by_year = {str(y): 10 for y in range(2020, CURRENT_YEAR)}
        mock_summary.return_value = _make_summary(
            total=10 * (CURRENT_YEAR - 2020), by_year=by_year
        )
        docs = [_make_mock_doc(y) for y in range(2020, CURRENT_YEAR) for _ in range(10)]
        storage = _make_mock_storage(docs)

        result = score_trajectory("test", storage)
        assert isinstance(result, TrajectoryResult)
        assert result.phase in ("emerging", "accelerating", "mature", "stagnant", "declining")
        assert result.momentum_score is not None
        assert 0.0 <= result.momentum_score <= 1.0

    @patch("src.tools.trajectory.generate_summary")
    @patch("src.tools.trajectory._load_trends_overlay", return_value=None)
    @patch("src.tools.trajectory._build_trial_phase_series", return_value=None)
    @patch("src.tools.trajectory._compute_avg_trial_duration", return_value=None)
    def test_plot_ready_arrays(self, _dur, _trials, _trends, mock_summary):
        by_year = {"2020": 5, "2021": 8, "2022": 12, "2023": 15, "2024": 20}
        mock_summary.return_value = _make_summary(total=60, by_year=by_year)
        docs = []
        for yr_str, cnt in by_year.items():
            docs.extend(_make_mock_doc(int(yr_str)) for _ in range(cnt))
        storage = _make_mock_storage(docs)

        result = score_trajectory("test", storage)
        assert result.yearly_counts is not None
        yc = result.yearly_counts

        # Years should be contiguous
        assert yc.years == list(range(2020, 2025))
        # Total length matches years
        assert len(yc.total) == len(yc.years)
        # All source arrays match years length
        for arr in yc.by_source.values():
            assert len(arr) == len(yc.years)

        # Cumulative should be non-decreasing
        assert result.cumulative is not None
        for i in range(1, len(result.cumulative.total)):
            assert result.cumulative.total[i] >= result.cumulative.total[i - 1]

    @patch("src.tools.trajectory.generate_summary")
    @patch("src.tools.trajectory._load_trends_overlay", return_value=None)
    @patch("src.tools.trajectory._build_trial_phase_series", return_value=None)
    @patch("src.tools.trajectory._compute_avg_trial_duration", return_value=None)
    def test_no_trials_still_works(self, _dur, _trials, _trends, mock_summary):
        mock_summary.return_value = _make_summary(total=30, by_year={"2023": 15, "2024": 15})
        docs = [_make_mock_doc(2023) for _ in range(15)] + [_make_mock_doc(2024) for _ in range(15)]
        storage = _make_mock_storage(docs)

        result = score_trajectory("test", storage)
        assert result.trial_pipeline is None
        assert result.trial_phases is None
        assert result.momentum_score is not None


# ── Real data integration test ──────────────────────────────────────────────

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "age_nt.db"
DOC_PATH = Path(__file__).resolve().parent.parent / "data" / "documents" / "rapamycin.json"
DB_EXISTS = DB_PATH.exists() and DOC_PATH.exists()


@pytest.mark.skipif(not DB_EXISTS, reason="Real data not available")
class TestRealData:
    def test_rapamycin(self):
        storage = StorageManager()
        result = score_trajectory("rapamycin", storage)
        assert isinstance(result, TrajectoryResult)
        assert result.total_documents > 100
        assert result.phase in ("emerging", "accelerating", "mature", "stagnant", "declining")
        assert result.momentum_score is not None
        assert result.velocity is not None
        assert result.diversification is not None
        assert result.yearly_counts is not None
        assert result.cumulative is not None
        # Rapamycin should have trial data
        assert result.trial_pipeline is not None


# Conditionally import StorageManager only for real data tests
if DB_EXISTS:
    from src.storage.manager import StorageManager
