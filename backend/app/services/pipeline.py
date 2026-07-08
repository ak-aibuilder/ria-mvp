"""Pipeline helpers: scoring + tier classification + catalog summaries.

Pure functions shared by the pipeline endpoints (start / confirm-enrich /
status). No I/O — the router owns persistence.
"""
from __future__ import annotations

from app.services.audit import assign_tier, score_product
from app.services.enrich import _apply_enriched_view

TIER_ORDER = ["III", "II", "I", "0"]


def score_with_tier(product: dict) -> dict:
    """Score a product (using its enriched view if present) and attach a tier.

    Returns the score dict augmented with tier/label. Does not mutate input.
    """
    score = score_product(_apply_enriched_view(product))
    tier = assign_tier(score)
    return {**score, **tier}


def scored_entry(product: dict) -> dict:
    """A compact per-product audit row for API responses."""
    st = score_with_tier(product)
    return {
        "sku": product["sku"],
        "name": product.get("name"),
        "readiness_score": st["readiness_score"],
        "dimension_scores": st["dimension_scores"],
        "gaps": st["gaps"],
        "tier": st["tier"],
        "label": st["label"],
    }


def tier_distribution(scored: list[dict]) -> dict[str, int]:
    """Count products per tier, always emitting all four tiers (0 included)."""
    dist = {t: 0 for t in TIER_ORDER}
    for row in scored:
        dist[row["tier"]] = dist.get(row["tier"], 0) + 1
    return dist


def audit_view(products: list[dict]) -> dict:
    """Full audit summary: per-product rows + tier distribution."""
    scored = [scored_entry(p) for p in products]
    return {
        "scored_products": scored,
        "tier_distribution": tier_distribution(scored),
        "product_count": len(scored),
    }
