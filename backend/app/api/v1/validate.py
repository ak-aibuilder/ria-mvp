"""Validation endpoints (goals.md §7, §10) — the Step 4 agent.

  POST /validate/query    run the agent against the pre- or post-enrichment index
  POST /validate/compare  run the SAME query against both indexes and return the
                          headline pre/post token comparison

The agent is data-invariant: the only thing that differs between pre and post is
whether the index carries enriched agent_facets to filter on.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.db.mongo import get_db
from app.services.agent import run_agent
from app.services.agent_index import EnrichedProductIndex
from app.services.groq_client import EnrichmentError, GroqEnrichmentClient
from app.services.token_tracker import TokenTracker

router = APIRouter(prefix="/validate", tags=["validate"])


class QueryRequest(BaseModel):
    session_id: str
    query: str
    index: str = "post"  # "pre" | "post"


class CompareRequest(BaseModel):
    session_id: str
    query: str


async def _load_products(db: AsyncIOMotorDatabase, session_id: str) -> list[dict]:
    session = await db.sessions.find_one({"_id": session_id})
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    products = [p async for p in db.products.find({"session_id": session_id}).sort("sku", 1)]
    if not products:
        raise HTTPException(status_code=409, detail="session has no products")
    return products


def _client() -> GroqEnrichmentClient:
    try:
        return GroqEnrichmentClient()
    except EnrichmentError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/query")
async def validate_query(
    payload: QueryRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict:
    if payload.index not in ("pre", "post"):
        raise HTTPException(status_code=400, detail="index must be 'pre' or 'post'")
    products = await _load_products(db, payload.session_id)
    index = EnrichedProductIndex.from_products(products, use_enriched=(payload.index == "post"))
    tracker = TokenTracker()
    result = await run_agent(
        query=payload.query,
        index=index,
        index_label=payload.index,
        client=_client(),
        tracker=tracker,
    )
    usage = [r for r in tracker.records if r.index == payload.index]
    return {
        "session_id": payload.session_id,
        "transcript": result,
        "token_usage": {
            "calls": len(usage),
            "total_tokens": sum(r.total_tokens for r in usage),
            "cost_usd": round(sum(r.cost_usd for r in usage), 6),
        },
    }


@router.post("/compare")
async def validate_compare(
    payload: CompareRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict:
    """Headline: same query, both indexes, one tracker -> pre/post comparison."""
    products = await _load_products(db, payload.session_id)
    tracker = TokenTracker()
    client = _client()

    pre_index = EnrichedProductIndex.from_products(products, use_enriched=False)
    post_index = EnrichedProductIndex.from_products(products, use_enriched=True)

    pre = await run_agent(query=payload.query, index=pre_index, index_label="pre", client=client, tracker=tracker)
    post = await run_agent(query=payload.query, index=post_index, index_label="post", client=client, tracker=tracker)

    comparison = tracker.query_comparison()
    await db.sessions.update_one(
        {"_id": payload.session_id},
        {"$set": {"token_metrics.query_comparison": comparison, "updated_at": datetime.now(timezone.utc)}},
    )
    return {
        "session_id": payload.session_id,
        "query": payload.query,
        "query_comparison": comparison,
        "pre": pre,
        "post": post,
    }
