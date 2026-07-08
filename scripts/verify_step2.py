"""Step 2 verification (goals.md §13): POST /pipeline/start returns audit scores
with tier labels.

Uses the canonical fixture data/apparel.csv (20 products). Drives the ASGI app
in-process via httpx (no uvicorn needed). The deterministic audit path always
runs. The live enrichment path (Gate 1 -> Gate 2) is gated behind
RIA_VERIFY_ENRICH=1 because enriching all 20 products on Groq's free-tier
8000 TPM is throttled and slow (~minutes); see docs/capability-bets.md.
Cleans up the session it creates.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

FIXTURE = ROOT / "data" / "apparel.csv"


def _load_root_env() -> None:
    env_path = ROOT / ".env"
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


_load_root_env()

import httpx  # noqa: E402
from app.main import app  # noqa: E402
from app.db.mongo import get_db, close  # noqa: E402

RUN_ENRICH = os.environ.get("RIA_VERIFY_ENRICH") == "1"


async def main() -> int:
    transport = httpx.ASGITransport(app=app)
    session_id = None
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            # --- Verify criterion: /pipeline/start returns audit scores + tiers ---
            with FIXTURE.open("rb") as fh:
                files = {"file": ("apparel.csv", fh, "text/csv")}
                r = await c.post("/api/v1/pipeline/start", files=files, timeout=60)
            r.raise_for_status()
            start = r.json()
            session_id = start["session_id"]
            scored = start["scored_products"]

            assert start["product_count"] == 20, (
                f"expected 20 products from fixture, got {start['product_count']}"
            )
            for row in scored:
                assert "tier" in row and "label" in row, f"missing tier/label: {row}"
                assert "readiness_score" in row
            print(f"PASS: /pipeline/start ingested {start['product_count']} products "
                  "with audit scores + tier labels")
            print("  ingest report:", start["report"])
            print("  raw tier distribution:", start["tier_distribution"])

            # --- Status works in audit phase (no LLM) ---
            r = await c.get(f"/api/v1/pipeline/status/{session_id}", timeout=30)
            r.raise_for_status()
            print("PASS: status phase =", r.json()["phase"])

            if not RUN_ENRICH:
                print("\nSKIP: Gate 1 enrichment (set RIA_VERIFY_ENRICH=1 to run the "
                      "live 20-product enrichment — slow on free-tier TPM).")
                return 0

            # --- Gate 1: enrichment + re-audit (live Groq, throttled) ---
            print("\nRunning Gate 1 (confirm-enrich) — live 20-product enrichment...")
            r = await c.post(
                "/api/v1/pipeline/confirm-enrich",
                json={"session_id": session_id},
                timeout=1800,
            )
            r.raise_for_status()
            enr = r.json()
            print("PASS: confirm-enrich completed")
            print("  before tiers:", enr["before"]["tier_distribution"])
            print("  after  tiers:", enr["after"]["tier_distribution"])
            print("  enrichment report:", enr["report"])

            r = await c.post(
                "/api/v1/pipeline/confirm-validate",
                json={"session_id": session_id},
                timeout=30,
            )
            r.raise_for_status()
            print("PASS: confirm-validate ->", r.json()["phase"])

        return 0
    finally:
        if session_id:
            db = get_db()
            await db.products.delete_many({"session_id": session_id})
            await db.sessions.delete_one({"_id": session_id})
            print(f"\ncleaned up test session {session_id}")
        await close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
