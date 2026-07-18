"""Step 3 verification (goals.md §13): token tracking math is correct and the
tracker exposes the phase/index breakdowns the demo needs.

Deterministic — feeds the TokenTracker synthetic usage objects (no Groq, no
Mongo), so it runs in CI. The live path (confirm-enrich returning token_metrics)
is exercised by verify_step2.py with RIA_VERIFY_ENRICH=1.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.token_tracker import (  # noqa: E402
    INDEX_POST,
    INDEX_PRE,
    PHASE_ENRICHMENT,
    PHASE_VALIDATION,
    TokenTracker,
    call_cost,
)

MODEL = "openai/gpt-oss-120b"


class _Usage:
    """Stand-in for the OpenAI usage object the Groq client stores."""

    def __init__(self, prompt: int, completion: int) -> None:
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.total_tokens = prompt + completion


def _approx(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol


def main() -> int:
    t = TokenTracker(model=MODEL)

    # --- Enrichment phase: three calls across two SKUs -------------------
    t.record(_Usage(458, 510), phase=PHASE_ENRICHMENT, label="sku-a")  # D3
    t.record(_Usage(400, 300), phase=PHASE_ENRICHMENT, label="sku-a")  # D6
    t.record(_Usage(500, 200), phase=PHASE_ENRICHMENT, label="sku-b")  # D3
    t.record(None, phase=PHASE_ENRICHMENT, label="sku-b")  # failed call: skipped

    es = t.enrichment_summary()
    assert es["calls"] == 3, es
    assert es["prompt_tokens"] == 1358, es
    assert es["completion_tokens"] == 1010, es
    assert es["total_tokens"] == 2368, es

    # Cost: prompt @ $0.15/1M + completion @ $0.60/1M.
    expected_cost = round(1358 / 1e6 * 0.15 + 1010 / 1e6 * 0.60, 6)
    assert _approx(es["cost_usd"], expected_cost), (es["cost_usd"], expected_cost)
    print(f"PASS: enrichment_summary math (cost ${es['cost_usd']:.6f} for 3 calls)")

    by = t.enrichment_by_sku()
    assert set(by) == {"sku-a", "sku-b"}, by
    assert by["sku-a"]["calls"] == 2 and by["sku-a"]["total_tokens"] == 1668, by
    assert by["sku-b"]["calls"] == 1 and by["sku-b"]["total_tokens"] == 700, by
    print("PASS: per-product (by-sku) token efficiency breakdown")

    # --- Validation phase: headline pre/post query comparison -----------
    # Raw catalog forces a bigger, keyword-groping agent run; enriched catalog
    # lets it filter facets, so post is much cheaper.
    t.record(_Usage(3000, 1200), phase=PHASE_VALIDATION, index=INDEX_PRE)
    t.record(_Usage(900, 400), phase=PHASE_VALIDATION, index=INDEX_POST)

    qc = t.query_comparison()
    assert qc["pre"]["total_tokens"] == 4200, qc
    assert qc["post"]["total_tokens"] == 1300, qc
    assert qc["token_reduction_pct"] == round((4200 - 1300) / 4200 * 100, 1), qc
    pre_cost = call_cost(MODEL, 3000, 1200)
    post_cost = call_cost(MODEL, 900, 400)
    assert qc["cost_reduction_pct"] == round((pre_cost - post_cost) / pre_cost * 100, 1), qc
    assert qc["token_reduction_pct"] > 0, "post-enrichment query should be cheaper"
    print(
        "PASS: query_comparison headline metric — "
        f"{qc['token_reduction_pct']}% fewer tokens, "
        f"{qc['cost_reduction_pct']}% cheaper per query"
    )

    # --- Isolation: enrichment totals unaffected by validation records ---
    assert t.enrichment_summary()["calls"] == 3, "phase filter leaked"
    print("PASS: phase/index filters isolate enrichment from validation")

    print("\nStep 3 token tracking verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
