"""Step 4 verification (goals.md §13): the validation agent executes
search -> get_product_details -> add_to_cart on the enriched index, and the
same query run against the pre- and post-enrichment indexes shows a positive
token reduction (the headline metric, Eval 4).

Live: enriches a focused subset of the fixture on Groq, then runs one shopping
query against both indexes with a shared TokenTracker. No Mongo (drives the
agent directly). Slow under free-tier TPM; enriches only ~8 products.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def _load_env() -> None:
    for line in (ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


_load_env()

from app.services.ingest import ingest  # noqa: E402
from app.services.enrich import enrich_products  # noqa: E402
from app.services.groq_client import GroqEnrichmentClient  # noqa: E402
from app.services.agent import run_agent  # noqa: E402
from app.services.agent_index import EnrichedProductIndex  # noqa: E402
from app.services.token_tracker import TokenTracker  # noqa: E402

# Weather/jacket-heavy subset so the post index has facets to filter on.
SUBSET = {
    "navy-sport-jacket", "zipped-jacket", "classic-leather-jacket",
    "dark-winter-jacket", "olive-green-jacket", "yellow-wool-jumper",
    "silk-summer-top", "white-cotton-shirt",
}
QUERY = (
    "I want to buy one waterproof jacket for rainy weather, under $200, in size M. "
    "Find the single best match, check its details, and add it to my cart."
)


async def main() -> int:
    products = [p for p in ingest((ROOT / "data" / "apparel.csv").read_bytes()).products
                if p["sku"] in SUBSET]
    print(f"subset: {len(products)} products — enriching live (free-tier TPM, be patient)...")

    client = GroqEnrichmentClient()
    enrich_tracker = TokenTracker()
    enriched = await enrich_products(products, client=client, tracker=enrich_tracker)
    facet_counts = sum(1 for p in enriched if (p.get("enriched") or {}).get("agent_facets"))
    print(f"enriched {len(enriched)} products; {facet_counts} have agent_facets. "
          f"enrichment cost ${enrich_tracker.enrichment_summary()['cost_usd']:.4f}")

    pre_index = EnrichedProductIndex.from_products(enriched, use_enriched=False)
    post_index = EnrichedProductIndex.from_products(enriched, use_enriched=True)
    print("pre-index facets:", sorted(pre_index.facet_index.keys()) or "(none)")
    print("post-index facets:", sorted(post_index.facet_index.keys()))

    tracker = TokenTracker()
    print("\n--- PRE-enrichment agent run ---")
    pre = await run_agent(query=QUERY, index=pre_index, index_label="pre", client=client, tracker=tracker)
    print("  tool calls:", [c["name"] for c in pre["tool_calls"]], "| turns:", pre["turns_used"])

    print("--- POST-enrichment agent run ---")
    post = await run_agent(query=QUERY, index=post_index, index_label="post", client=client, tracker=tracker)
    print("  tool calls:", [c["name"] for c in post["tool_calls"]], "| turns:", post["turns_used"])
    print("  response:", post["agent_response"][:200])

    # --- Verify flow on the enriched index ---
    post_tools = [c["name"] for c in post["tool_calls"]]
    flow_ok = all(t in post_tools for t in ("search_products", "get_product_details", "add_to_cart"))
    print(f"\nflow search->details->add_to_cart on enriched index: "
          f"{'PASS' if flow_ok else 'FAIL'} (saw {post_tools})")
    print("  checkout_intent version:", (post["checkout_intent"] or {}).get("intent_version"))
    print("  cart:", [(c['sku'], c['variant']) for c in post["cart_preview"]])

    # --- Headline: pre/post token comparison ---
    qc = tracker.query_comparison()
    pre_prompt = sum(r.prompt_tokens for r in tracker.records if r.index == "pre")
    post_prompt = sum(r.prompt_tokens for r in tracker.records if r.index == "post")
    prompt_red = round((pre_prompt - post_prompt) / pre_prompt * 100, 1) if pre_prompt else 0.0
    print("\n=== HEADLINE: per-query token comparison ===")
    print(f"  PRE : {qc['pre']['total_tokens']} total ({pre_prompt} prompt / "
          f"{qc['pre']['completion_tokens']} completion)  ${qc['pre']['cost_usd']:.6f}")
    print(f"  POST: {qc['post']['total_tokens']} total ({post_prompt} prompt / "
          f"{qc['post']['completion_tokens']} completion)  ${qc['post']['cost_usd']:.6f}")
    print(f"  TOTAL-token reduction : {qc['token_reduction_pct']}% (cost {qc['cost_reduction_pct']}%)")
    print(f"  PROMPT-token reduction: {prompt_red}%  (context the agent had to load — "
          "the retrieval-precision signal facets drive)")
    reduced = qc["post"]["total_tokens"] < qc["pre"]["total_tokens"]
    print(f"  positive total reduction (Eval 4): {'PASS' if reduced else 'FAIL'}")

    if pre.get("fallback_fired") or post.get("fallback_fired"):
        print("  NOTE: text-tool-call fallback fired (logged) — native FC missed a turn.")

    ok = flow_ok and reduced
    print(f"\nStep 4 verification: {'PASS' if ok else 'INCOMPLETE — see above'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
