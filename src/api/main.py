"""FastAPI application — LongevityLens API.

Run with:
    uvicorn src.api.main:app --reload --port 8000

Interactive docs at http://localhost:8000/docs
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.dependencies import init_storage, shutdown_storage
from src.api.routes import ingest, interventions, reasoning


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: initialize storage. Shutdown: close connections."""
    await init_storage()
    yield
    await shutdown_storage()


app = FastAPI(
    title="LongevityLens",
    description=(
        "Agentic system that scrapes, standardises, and reasons over "
        "scientific evidence for aging interventions."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow everything for local dev / Streamlit
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routers
app.include_router(interventions.router)
app.include_router(reasoning.router)
app.include_router(ingest.router)


@app.get("/health", tags=["system"])
async def health_check() -> dict:
    return {"status": "ok", "service": "longevity-lens"}
