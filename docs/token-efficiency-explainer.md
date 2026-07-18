# Token Efficiency in Agentic Commerce — Why Eval 4 Changed

This explains why the original Eval 4 (per-product token reduction) was the
wrong metric, what the fixture data showed, and why the replacement metric
(products examined + tool calls to resolution, goals.md §4) is the correct
one. Standalone reference — see [build-log.md](build-log.md) for the
step-by-step build history and [dataset-readiness.md](dataset-readiness.md)
for the underlying measurements.

## 1. The original assumption

Eval 4 v1 assumed enrichment should shrink each product's token footprint:
raw marketing prose gets rewritten into compact structured JSON (facets,
Q&A, relationships), so a per-product before/after comparison should show
fewer tokens after enrichment. Pass criterion: `post-enrichment total tokens
< pre-enrichment total tokens`, scored on % reduction.

That assumption treats enrichment as **compression** — the same information,
represented more efficiently.

## 2. What the data showed

`dataset-readiness.md` §6 measured the fixture's raw per-product text
(description + attributes, o200k_base tokenizer):

| | value |
|---|---|
| Median raw tokens/product | 21 |
| Mean raw tokens/product | 21.3 |
| Max raw tokens/product | 41 (`navy-sport-jacket`) |
| Min raw tokens/product | 8 (`striped-skirt-and-top`) |

Raw descriptions are already lean — 1–2 sentences pulled from a Shopify
export. There is almost no prose bloat to compress.

Enrichment, meanwhile, *adds* content on top of the original text: 3–5 Q&A
pairs, a structured `agent_facets` block, 2–4 relationships, and (when D2 is
a gap) a rewritten 150–250 word description. Every one of those is
additional tokens layered onto a product that started at 8–41. The enriched
representation is necessarily larger, not smaller — confirmed live in Step 4
(`model-behavior-log.md`, 2026-07-08): `get_product_details` payload went
from 119 tokens pre-enrichment to 145 tokens post (+26/call), because the
enriched read now carries `agent_facets` alongside the trimmed description.

Per-product tokens go **up**, not down. Eval 4 v1 was checking for a
reduction that the enrichment design never intended to produce.

## 3. Why this isn't a failure

The value of enrichment was never "the same product description, said in
fewer tokens." It's that **structured facets let the agent skip products it
doesn't need to read at all.**

The mechanism is visible in the same Step 4 diagnostic
(`model-behavior-log.md`, 2026-07-08 addendum), measured offline on the
8-product subset:

- `search_products` payload: **325 tokens (8 unfiltered matches) → 89 tokens
  (2 matches via a `weather=rain` facet filter)** — a 236-token/call
  reduction, because the *count* of products returned drops, not the
  per-product encoding.
- `get_product_details` payload: 119 → 145 tokens (+26/call) — the one place
  enrichment costs more per unit.

One large search-side saving that scales with how many products get
filtered out, against one small per-product read-side cost. The win isn't
compression — it's **retrieval**: fewer products enter the context window at
all.

## 4. The scale dependency

At 20 products (the fixture size), that mechanism is real but small relative
to fixed overhead. The controlled Step 4 run showed total per-query cost of
4822 (pre) vs 4943 (post) tokens — a wash, because:

- The system prompt and gpt-oss reasoning/completion tokens are a fixed cost
  per turn, present regardless of catalog size, and they're noisy (completion
  swung 400→473 tokens between runs).
- With only 8–20 products in scope, keyword search over the *whole* catalog
  is already cheap — there's little for a facet filter to save by narrowing
  8 products down to 2.

At catalog scale, that ratio inverts. Fixed cost (system prompt, reasoning)
stays roughly constant per query. Variable cost (how much product data
enters context) scales with how many products the agent has to read to
resolve the query. A pre-enrichment agent without facet filters degrades
toward scanning or keyword-groping a growing candidate set; a
post-enrichment agent with `weather=rain, price_max=200` narrows to the same
small handful of candidates whether the catalog holds 20 products or 1,000.
Projected out using the measured per-item costs above (~21 tok/item raw
listing, ~145 tok/item enriched detail read), the search-payload saving
compounds with catalog size while the per-product read penalty does not — at
enough scale the filtered read dominates and the unfiltered scan's cost
grows roughly linearly with catalog size, which is the basis for the
100/500/1000-product cost projection now in Eval 4 (goals.md §4). Producing
exact dollar figures at those scales is a Step 7 eval run, not a claim this
document makes.

## 5. The corrected metric

Eval 4 (goals.md §4, revised) now measures:

1. **Products examined** — distinct SKU count appearing in tool results
   across the full agent loop, pre vs. post enrichment.
2. **Tool calls to resolution** — total tool call count, pre vs. post.
3. **Projected per-query cost at 100/500/1000-product scale**, extrapolated
   from measured per-product token costs.

Pass: post-enrichment examines fewer products **and** uses fewer-or-equal
tool calls. The old 20-product total-token delta is kept only as a
supporting data point (goals.md §4b) — informative context, not the
pass/fail line.

The agent (`agent.py`) now returns `skus_examined` and `tool_call_count`
directly in its response so this can be scored without re-deriving it from
the raw tool-call transcript.

## 6. The lesson

Token efficiency in agentic commerce is a **retrieval problem, not a
compression problem.** An agent doesn't need each product to be described
in fewer tokens — it needs a way to avoid reading products that aren't
relevant to begin with. Structured facets are valuable because they let the
agent filter *before* it reads, not because they make any single product
cheaper to represent. Measuring "did the product get smaller" tests the
wrong thing; measuring "did the agent read less of the catalog to get the
same answer" tests the thing enrichment actually does.
