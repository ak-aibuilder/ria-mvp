"""Diagnostic: token cost of search_products vs get_product_details, Pre vs Post.

Enriches a subset live, runs the SAME query against the pre- and post-enrichment
indexes, and breaks down where tokens go — by tool, using two lenses:

  1. Result-payload tokens (o200k_base, exact/deterministic): how big the JSON
     each tool returns is. This is what the agent must re-read every later turn,
     so it compounds.
  2. LLM turn usage (actual Groq billing): prompt/completion tokens on the turn
     that EMITTED each tool call.
"""
from __future__ import annotations

import asyncio
import os
import sys
from collections import defaultdict
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
from app.services.token_tracker import TokenTracker, count_tokens  # noqa: E402

SUBSET = {
    "navy-sport-jacket", "zipped-jacket", "classic-leather-jacket",
    "dark-winter-jacket", "olive-green-jacket", "yellow-wool-jumper",
    "silk-summer-top", "white-cotton-shirt",
}
QUERY = (
    "I want to buy one waterproof jacket for rainy weather, under $200, in size M. "
    "Find the single best match, check its details, and add it to my cart."
)


def _breakdown(run: dict) -> dict:
    """Aggregate result-payload tokens per tool from tool_calls, and turn usage
    per emitted tool from turn_log."""
    result_toks: dict[str, list[int]] = defaultdict(list)
    for tc in run["tool_calls"]:
        import json
        result_toks[tc["name"]].append(count_tokens(json.dumps(tc["result"])))

    turn_by_tool: dict[str, dict[str, int]] = defaultdict(lambda: {"prompt": 0, "completion": 0, "turns": 0})
    for t in run["turn_log"]:
        key = t["emitted"][0] if t["emitted"] else "final"
        turn_by_tool[key]["prompt"] += t["prompt_tokens"]
        turn_by_tool[key]["completion"] += t["completion_tokens"]
        turn_by_tool[key]["turns"] += 1
    return {"result_toks": result_toks, "turn_by_tool": turn_by_tool}


def _print_index(label: str, run: dict) -> None:
    b = _breakdown(run)
    print(f"\n===== {label.upper()} index =====")
    print(f"tool sequence: {[c['name'] for c in run['tool_calls']]}")
    print(f"{'tool':<22}{'calls':>6}{'result_toks(sum/avg)':>24}{'turn_prompt':>13}{'turn_compl':>12}")
    for tool in ("search_products", "get_product_details", "add_to_cart", "final"):
        rt = b["result_toks"].get(tool, [])
        tb = b["turn_by_tool"].get(tool, {"prompt": 0, "completion": 0, "turns": 0})
        if not rt and tb["turns"] == 0:
            continue
        rsum = sum(rt)
        ravg = round(rsum / len(rt), 1) if rt else 0
        print(f"{tool:<22}{len(rt):>6}{f'{rsum}/{ravg}':>24}{tb['prompt']:>13}{tb['completion']:>12}")


async def main() -> int:
    products = [p for p in ingest((ROOT / "data" / "apparel.csv").read_bytes()).products
                if p["sku"] in SUBSET]
    print(f"enriching {len(products)}-product subset live...")
    client = GroqEnrichmentClient()
    enriched = await enrich_products(products, client=client, tracker=TokenTracker())

    pre_index = EnrichedProductIndex.from_products(enriched, use_enriched=False)
    post_index = EnrichedProductIndex.from_products(enriched, use_enriched=True)

    # Enrichment just saturated the free-tier 8000 TPM window; let it reset before
    # the agent runs so they don't 429 out (see capability-bets Step 2).
    print("cooling down 65s for TPM reset before agent runs...")
    await asyncio.sleep(65)

    tracker = TokenTracker()
    pre = await run_agent(query=QUERY, index=pre_index, index_label="pre", client=client, tracker=tracker)
    post = await run_agent(query=QUERY, index=post_index, index_label="post", client=client, tracker=tracker)

    _print_index("pre", pre)
    _print_index("post", post)

    # Direct per-tool result-payload comparison (deterministic, no LLM noise).
    import json
    print("\n===== RESULT-PAYLOAD tokens per tool (o200k_base, exact) =====")
    print(f"{'tool':<22}{'PRE sum':>10}{'POST sum':>10}{'delta':>8}")
    for tool in ("search_products", "get_product_details", "add_to_cart"):
        pre_sum = sum(count_tokens(json.dumps(c["result"])) for c in pre["tool_calls"] if c["name"] == tool)
        post_sum = sum(count_tokens(json.dumps(c["result"])) for c in post["tool_calls"] if c["name"] == tool)
        print(f"{tool:<22}{pre_sum:>10}{post_sum:>10}{post_sum - pre_sum:>+8}")

    qc = tracker.query_comparison()
    print(f"\ntotals: PRE {qc['pre']['total_tokens']}  POST {qc['post']['total_tokens']}  "
          f"({qc['token_reduction_pct']}% reduction)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
