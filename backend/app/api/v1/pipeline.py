"""Pipeline endpoints (goals.md §7) — the agentic flow with two HITL gates.

  POST /pipeline/start            CSV upload -> ingest + audit (no LLM)
  POST /pipeline/confirm-enrich   Gate 1 -> enrich (Groq) + re-audit
  POST /pipeline/confirm-validate Gate 2 -> enable validation
  GET  /pipeline/status/{session} current phase + audit summary

Sessions are anonymous, keyed by a generated session_id. State lives in two
collections: `sessions` (phase) and `products` (one doc per SKU per session).
The validation agent itself is built in Step 4; Gate 2 only flips the phase.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.db.mongo import get_db
from app.services.enrich import enrich_products
from app.services.groq_client import EnrichmentError, GroqEnrichmentClient
from app.services.ingest import ingest
from app.services.pipeline import audit_view, tier_distribution, scored_entry

router = APIRouter(prefix="/pipeline", tags=["pipeline"])

# Product fields we ingest/persist. _id and session_id are stripped from output.
_PRODUCT_FIELDS = (
    "sku", "name", "description", "price", "category", "image_urls", "brand",
    "attributes", "q_and_a", "raw_review_data", "relationship_type",
    "agent_facets", "enriched", "enriched_provenance", "audit_trail",
    "enrichment_status", "score",
)


class SessionRequest(BaseModel):
    session_id: str


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean(doc: dict) -> dict:
    """Drop Mongo internals for a product returned to the client."""
    return {k: doc.get(k) for k in _PRODUCT_FIELDS if k in doc}


async def _load_session(db: AsyncIOMotorDatabase, session_id: str) -> dict:
    session = await db.sessions.find_one({"_id": session_id})
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    return session


async def _load_products(db: AsyncIOMotorDatabase, session_id: str) -> list[dict]:
    cursor = db.products.find({"session_id": session_id}).sort("sku", 1)
    return [p async for p in cursor]


@router.post("/start")
async def start_pipeline(
    file: UploadFile = File(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict:
    """Ingest a CSV, run the deterministic audit, persist a new session."""
    raw = await file.read()
    result = ingest(raw, strategy="merge")
    if not result.products:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "no valid products parsed from CSV",
                "missing_required": result.report.missing_required,
                "rows_parsed": result.report.rows_parsed,
                "rows_dropped": result.report.rows_dropped,
            },
        )

    session_id = uuid.uuid4().hex
    now = _now()

    # Score up front so the persisted product carries its raw-audit score, and
    # insert one doc per product keyed by the session.
    docs = []
    for p in result.products:
        entry = scored_entry(p)
        docs.append(
            {
                **p,
                "session_id": session_id,
                "score": {
                    "readiness_score": entry["readiness_score"],
                    "dimension_scores": entry["dimension_scores"],
                    "gaps": entry["gaps"],
                },
                "created_at": now,
                "updated_at": now,
            }
        )
    await db.products.insert_many(docs)
    await db.sessions.insert_one(
        {"_id": session_id, "phase": "audit", "created_at": now, "updated_at": now}
    )

    return {
        "session_id": session_id,
        "phase": "audit",
        "report": {
            "rows_parsed": result.report.rows_parsed,
            "rows_dropped": result.report.rows_dropped,
            "duplicate_count": result.report.duplicate_count,
            "alias_mapping": result.report.alias_mapping,
        },
        **audit_view(result.products),
    }


@router.post("/confirm-enrich")
async def confirm_enrich(
    payload: SessionRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict:
    """Gate 1: run enrichment via Groq, re-audit, persist enriched products."""
    await _load_session(db, payload.session_id)
    products = await _load_products(db, payload.session_id)
    if not products:
        raise HTTPException(status_code=409, detail="session has no products")

    before = audit_view(products)

    try:
        client = GroqEnrichmentClient()
    except EnrichmentError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    enriched = await enrich_products(products, client=client)

    now = _now()
    for prod in enriched:
        await db.products.update_one(
            {"_id": prod["_id"]},
            {
                "$set": {
                    "enriched": prod.get("enriched"),
                    "enriched_provenance": prod.get("enriched_provenance", {}),
                    "audit_trail": prod.get("audit_trail", []),
                    "score": prod.get("score"),
                    "enrichment_status": prod.get("enrichment_status", "ok"),
                    "updated_at": now,
                }
            },
        )
    await db.sessions.update_one(
        {"_id": payload.session_id},
        {"$set": {"phase": "enriched", "updated_at": now}},
    )

    after = audit_view(enriched)
    return {
        "session_id": payload.session_id,
        "phase": "enriched",
        "before": {"tier_distribution": before["tier_distribution"]},
        "after": after,
        "enriched_products": [
            {
                "sku": p["sku"],
                "original_fields": {
                    k: p.get(k)
                    for k in ("name", "description", "price", "category",
                              "brand", "image_urls", "attributes")
                },
                "enriched_fields": p.get("enriched") or {},
                "confidence_scores": {
                    k: v.get("confidence", 0.0)
                    for k, v in (p.get("enriched_provenance") or {}).items()
                },
                "enrichment_status": p.get("enrichment_status", "ok"),
                "audit_trail": p.get("audit_trail", []),
            }
            for p in enriched
        ],
        "report": {
            "succeeded": sum(1 for p in enriched if p.get("enrichment_status") == "ok"),
            "failed": sum(1 for p in enriched if p.get("enrichment_status") == "failed"),
        },
    }


@router.post("/confirm-validate")
async def confirm_validate(
    payload: SessionRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict:
    """Gate 2: enable validation. The agent loop itself is built in Step 4."""
    session = await _load_session(db, payload.session_id)
    if session.get("phase") not in ("enriched", "validate_ready"):
        raise HTTPException(
            status_code=409, detail="run enrichment (Gate 1) before enabling validation"
        )
    await db.sessions.update_one(
        {"_id": payload.session_id},
        {"$set": {"phase": "validate_ready", "updated_at": _now()}},
    )
    return {
        "session_id": payload.session_id,
        "phase": "validate_ready",
        "validation_enabled": True,
    }


@router.get("/status/{session_id}")
async def pipeline_status(
    session_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict:
    session = await _load_session(db, session_id)
    products = await _load_products(db, session_id)
    return {
        "session_id": session_id,
        "phase": session.get("phase", "audit"),
        "products": [_clean(p) for p in products],
        **audit_view(products),
    }
