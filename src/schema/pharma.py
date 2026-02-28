"""Pydantic models for pharma and biotech company profiles.

These are NOT document subclasses — they represent LLM-generated company
profiles loaded directly from JSON files in data/pharma_profiles/ and
data/biotech_profiles/.

Every factual claim (funding, founding year, pipeline compounds, acquisitions)
must have a source URL or reference.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── Shared sub-models ────────────────────────────────────────────────────────


class LongevityAsset(BaseModel):
    """A compound or product relevant to longevity in a pharma pipeline."""

    compound: str
    intervention_link: str | None = None  # maps to our interventions
    status: str = ""  # "approved" | "phase3" | "phase2" | "phase1" | "preclinical"
    indication: str = ""
    relevance: str = ""  # why this matters for longevity
    source: str = ""  # URL or reference for this claim


class PipelineCompound(BaseModel):
    """A compound in a biotech's pipeline."""

    compound: str
    intervention_link: str | None = None  # maps to our interventions
    target: str = ""
    mechanism: str = ""
    indication: str | None = None
    phase: str = ""  # "preclinical" | "phase1" | "phase2" | "phase3" | "approved"
    hallmarks: list[str] = Field(default_factory=list)  # AgingHallmark values
    categories: list[str] = Field(default_factory=list)  # intervention categories
    source: str = ""  # URL or reference


class AcquisitionRecord(BaseModel):
    """A historical acquisition."""

    target: str
    year: int | None = None
    value_usd: int | None = None
    relevance: str = ""
    source: str = ""


class KeyPerson(BaseModel):
    """A key person at a company."""

    name: str
    role: str = ""
    background: str = ""


class AcquisitionEstimate(BaseModel):
    """Estimated acquisition value for a biotech."""

    low_usd: int | None = None
    high_usd: int | None = None
    methodology: str = ""
    comparable_deals: list[str] = Field(default_factory=list)


class AcquisitionPattern(BaseModel):
    """A pharma company's acquisition strategy."""

    preferred_stage: str = ""  # "preclinical" | "phase1" | "phase2+" etc.
    avg_deal_size_usd: int | None = None
    focus_areas: list[str] = Field(default_factory=list)
    recent_trend: str = ""


# ── Company profiles ─────────────────────────────────────────────────────────


class PharmaProfile(BaseModel):
    """Profile of a large pharma company with longevity relevance analysis."""

    company: str
    ticker: str | None = None
    hq: str = ""
    market_cap_approx: str | None = None
    therapeutic_areas: list[str] = Field(default_factory=list)

    # Longevity analysis
    aging_relevance: str = "low"  # "high" | "moderate" | "low"
    aging_relevance_reasoning: str = ""
    existing_longevity_assets: list[LongevityAsset] = Field(default_factory=list)
    pipeline_hallmarks_overlap: list[str] = Field(default_factory=list)
    aging_signal_strength: int = Field(default=1, ge=1, le=10)

    # M&A
    recent_acquisitions: list[AcquisitionRecord] = Field(default_factory=list)
    acquisition_pattern: AcquisitionPattern = Field(default_factory=AcquisitionPattern)

    # Provenance
    sources: list[str] = Field(default_factory=list)
    needs_review: bool = True


class BiotechProfile(BaseModel):
    """Profile of a longevity-focused biotech company."""

    company: str
    ticker: str | None = None
    founded: int | None = None
    hq: str | None = None
    stage: str = "preclinical"  # "preclinical" | "clinical" | "approved"
    total_funding_usd: int | None = None

    # Pipeline
    pipeline: list[PipelineCompound] = Field(default_factory=list)
    hallmarks_targeted: list[str] = Field(default_factory=list)
    category_links: list[str] = Field(default_factory=list)

    # Team & investors
    key_people: list[KeyPerson] = Field(default_factory=list)
    investors_notable: list[str] = Field(default_factory=list)

    # Strategic analysis
    risks: list[str] = Field(default_factory=list)
    competitive_advantages: list[str] = Field(default_factory=list)
    acquisition_estimate: AcquisitionEstimate | None = None

    # Provenance
    sources: list[str] = Field(default_factory=list)
    needs_review: bool = True
