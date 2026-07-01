"""RIA v2 FastAPI application entry point.

Step 1 scaffold: CORS + health check only. Pipeline, validation, and export
routers are mounted in later build steps (goals.md §13).
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings

settings = get_settings()

app = FastAPI(title="RIA v2", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "ria-v2", "model": settings.GROQ_MODEL}
