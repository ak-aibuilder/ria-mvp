"""Export endpoints (goals.md §12) — Step 6.

  GET /api/v1/exports/{session_id}/{format}
  format: ucp_supplemental | acp_feed | asa_readiness | enriched_csv

All four read the same persisted product set and apply the enriched view
(enrich.py's _apply_enriched_view — enriched fields shadow raw nulls) so an
export reflects Gate 1's enrichment the same way the pipeline endpoints do.
"""
from __future__ import annotations

import csv
import io
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db.mongo import get_db
from app.services.enrich import _apply_enriched_view
from app.services.pipeline import scored_entry

router = APIRouter(prefix="/exports", tags=["exports"])

FACET_COLUMNS = (
    "occasion", "weather", "fit", "care", "season", "price_band", "color", "material",
)


async def _load_products(db: AsyncIOMotorDatabase, session_id: str) -> list[dict]:
    session = await db.sessions.find_one({"_id": session_id})
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    products = [p async for p in db.products.find({"session_id": session_id}).sort("sku", 1)]
    if not products:
        raise HTTPException(status_code=409, detail="session has no products")
    return products


def _facet_str(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "|".join(str(v) for v in value)
    return str(value)


# --- ucp_supplemental (JSON) -------------------------------------------------

def _ucp_supplemental(products: list[dict], catalog_skus: set[str]) -> list[dict]:
    entries = []
    for raw in products:
        p = _apply_enriched_view(raw)
        qa = p.get("q_and_a") or []
        highlights = [
            item["answer"] for item in qa
            if isinstance(item, dict) and item.get("answer") and not item.get("speculative")
        ]
        rels = p.get("relationship_type") or []
        compatible = [
            r["related_sku"] for r in rels
            if isinstance(r, dict) and r.get("relationship_type") == "complementary"
            and r.get("related_sku") in catalog_skus
        ]
        substitutes = [
            r["related_sku"] for r in rels
            if isinstance(r, dict) and r.get("relationship_type") == "substitute"
            and r.get("related_sku") in catalog_skus
        ]
        facets = p.get("agent_facets") or {}
        entries.append({
            "id": p["sku"],
            "title": p.get("name"),
            "product_highlight": highlights,
            "compatible_products": compatible,
            "substitute_products": substitutes,
            "lifestyle": facets.get("occasion") or [],
            "season": facets.get("season") or [],
        })
    return entries


# --- acp_feed (JSONL) --------------------------------------------------------

def _acp_feed_lines(products: list[dict]) -> list[str]:
    lines = []
    for raw in products:
        p = _apply_enriched_view(raw)
        title = (p.get("name") or "")[:150]
        description = (p.get("description") or "")[:5000]
        entry = {
            "id": p["sku"],
            "title": title,
            "description": description,
            "price": {"amount": p.get("price"), "currency": "USD"},
            "availability": "in_stock",
            "url": f"/products/{p['sku']}",
            "eligibility": {"search": True, "checkout": False},
        }
        lines.append(json.dumps(entry, ensure_ascii=False))
    return lines


# --- asa_readiness (JSON) ----------------------------------------------------

def _asa_readiness(products: list[dict]) -> dict:
    rows = [scored_entry(p) for p in products]
    total = len(rows)
    ready = sum(1 for r in rows if r["tier"] in ("II", "III"))
    pct = round((ready / total) * 100, 1) if total else 0.0

    def _coverage(dim: str) -> float:
        if not total:
            return 0.0
        hit = sum(1 for r in rows if r["dimension_scores"].get(dim, 0) >= 6.0)
        return round((hit / total) * 100, 1)

    if pct >= 80:
        recommendation = "Catalog is Amazon Selling Agent ready — submit for ASA review."
    elif pct >= 40:
        recommendation = "Enrich the remaining gaps before ASA submission."
    else:
        recommendation = "Catalog needs enrichment before it is ASA-eligible."

    return {
        "total_products": total,
        "ready_count": ready,
        "percentage": pct,
        "recommendation": recommendation,
        "requirements_coverage": {
            "structured_data": _coverage("D1"),
            "q_and_a": _coverage("D3"),
            "relationships": _coverage("D5"),
            "brand_voice": None,  # not generated (goals.md §12)
        },
    }


# --- enriched_csv (CSV) ------------------------------------------------------

def _enriched_csv(products: list[dict]) -> str:
    fieldnames = [
        "sku", "name", "description", "price", "category", "brand", "image_urls",
        "tier", "readiness_score",
        "enriched_description",
        *[f"facet_{f}" for f in FACET_COLUMNS],
        "q_and_a_count", "relationship_count",
    ]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for raw in products:
        entry = scored_entry(raw)
        p = _apply_enriched_view(raw)
        enriched = raw.get("enriched") or {}
        facets = p.get("agent_facets") or {}
        row = {
            "sku": raw.get("sku"),
            "name": raw.get("name"),
            "description": raw.get("description"),
            "price": raw.get("price"),
            "category": raw.get("category"),
            "brand": raw.get("brand"),
            "image_urls": _facet_str(raw.get("image_urls")),
            "tier": entry["tier"],
            "readiness_score": entry["readiness_score"],
            "enriched_description": enriched.get("description") or "",
            "q_and_a_count": len(p.get("q_and_a") or []),
            "relationship_count": len(p.get("relationship_type") or []),
        }
        for f in FACET_COLUMNS:
            row[f"facet_{f}"] = _facet_str(facets.get(f))
        writer.writerow(row)
    return buf.getvalue()


@router.get("/{session_id}/{format}")
async def get_export(
    session_id: str,
    format: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    products = await _load_products(db, session_id)
    catalog_skus = {p["sku"] for p in products}

    if format == "ucp_supplemental":
        return _ucp_supplemental(products, catalog_skus)

    if format == "acp_feed":
        body = "\n".join(_acp_feed_lines(products))
        return Response(
            content=body,
            media_type="application/jsonl",
            headers={"Content-Disposition": f'attachment; filename="acp_feed_{session_id}.jsonl"'},
        )

    if format == "asa_readiness":
        return _asa_readiness(products)

    if format == "enriched_csv":
        body = _enriched_csv(products)
        return Response(
            content=body,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="enriched_{session_id}.csv"'},
        )

    raise HTTPException(status_code=404, detail=f"unknown export format: {format}")
