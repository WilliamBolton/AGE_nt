from __future__ import annotations

from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

import os
from dotenv import load_dotenv
from google.genai import types

PROJECT_ROOT = Path(__file__).resolve().parent.parent

load_dotenv()  # reads .env from project root

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
# OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY")

retry_config=types.HttpRetryOptions(
    attempts=5,  # Maximum retry attempts
    exp_base=7,  # Delay multiplier
    initial_delay=1, # Initial delay before first retry (in seconds)
    http_status_codes=[429, 500, 503, 504] # Retry on these HTTP errors
)


class LLMProvider(str, Enum):
    OPENAI = "openai"
    GEMINI = "gemini"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    llm_provider: LLMProvider = LLMProvider.OPENAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    medgemma_endpoint: str = ""

    # External APIs
    ncbi_api_key: str = ""
    tavily_api_key: str = ""

    # Storage
    database_url: str = "sqlite:///data/longevity_lens.db"

    # Logging
    log_level: str = "INFO"

    @property
    def sqlite_path(self) -> Path:
        """Absolute path to the SQLite database file."""
        relative = self.database_url.replace("sqlite:///", "")
        return PROJECT_ROOT / relative

    @property
    def documents_dir(self) -> Path:
        """Directory for per-intervention JSON files."""
        return PROJECT_ROOT / "data" / "documents"

    @property
    def query_cache_dir(self) -> Path:
        """Directory for cached query expansion results."""
        return PROJECT_ROOT / "data" / "query_cache"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


# ── Configurable aging-relevance terms ───────────────────────────────────────
# Used by ingest scoring to determine if a paper/trial is aging-relevant.
# Shared across all agents so the penalty is intervention-agnostic.

AGING_RELEVANCE_TERMS: set[str] = {
    "aging", "ageing", "longevity", "lifespan", "healthspan",
    "senescence", "senolytic", "geroprotect", "geroprotective",
    "age-related", "elderly", "older adults", "older adult",
    "frailty", "sarcopenia", "epigenetic clock", "biological age",
    "rejuvenation", "immunosenescence", "inflammaging", "geroscience",
    "hallmarks of aging", "cellular senescence", "life span",
    "aged", "aged, 80 and over",
}
