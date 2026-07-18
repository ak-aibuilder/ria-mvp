# Build Log — RIA v2

Chronological record of what shipped each build step: deliverables, problems
hit + fixes, and verification outcome. Maintained after every step. Cross-refs:
[goals.md](goals.md) (spec), [model-behavior-log.md](model-behavior-log.md)
(model behaviors), [capability-bets.md](capability-bets.md) (model-limited
features), [dataset-readiness.md](dataset-readiness.md) (fixture assessment).

---

## Step 1 — Scaffold + model integration

**Commit:** `e5815fb` — "Step 1: scaffold + Groq model integration"

**Delivered:**
- FastAPI backend + Next.js frontend scaffolded.
- Groq client (`groq_client.py`) on the OpenAI-compatible SDK targeting
  `openai/gpt-oss-120b`, adapted from v1's Anthropic client.
- Ported from v1 (goals §6): `audit.py` (+ `assign_tier()`), `merger.py`,
  prompt templates (`prompts.py`, re-adapted for GPT-OSS, not Claude).
- Settings/config, `.env.example`, `scripts/verify_step1.py`.

**Problems + fixes:** None. First live `gpt-oss-120b` call via Groq with
`response_format=json_object` on the ENRICH_FACETS prompt returned valid JSON on
the first try, stayed inside the controlled vocabulary, and correctly omitted
facets it couldn't infer — the opposite of FM-1/FM-2 (model-behavior-log
2026-07-01). Kept v1's defensive JSON-extraction + one-retry path anyway.

**Verification:** `verify_step1.py` — a single enrichment call returns valid
JSON. PASS. Tokens: prompt=458, completion=510 (completion inflated by gpt-oss
reasoning tokens even at "Reasoning: low" — first FM-5 signal).

---

## Step 2 — Pipeline API

**Commit:** `e389c57` — "Step 2: pipeline API (ingest, audit, tiers, enrichment orchestrator)"

**Delivered:**
- Agentic pipeline with two HITL gates (goals §7): `POST /pipeline/start`
  (ingest + deterministic audit + tier labels), `POST /pipeline/confirm-enrich`
  (Gate 1: Groq enrichment + re-audit), `POST /pipeline/confirm-validate`
  (Gate 2), `GET /pipeline/status/{session}`.
- `ingest.py` (Shopify-format CSV parse, header-alias normalization, variant-row
  dedupe), `enrich.py` (per-gap-dimension enrichment orchestrator), `pipeline.py`
  (scoring/tier helpers), MongoDB session/product persistence (`db/mongo.py`).
- `scripts/verify_step2.py` against the 20-product `data/apparel.csv` fixture.

**Problems + fixes:**
- **Free-tier 429 rate limiting (capability-bets row 1).** First full 20-product
  run fired ~20 concurrent Groq calls (5 products × up to 4 gap dims) and blew
  past Groq's free-tier 8000 TPM ceiling → HTTP 429 on 6–7 calls, dropping
  enrichment dimensions. Fix: `PRODUCT_CONCURRENCY` 8→2 in `enrich.py` +
  `max_retries=6` on the AsyncOpenAI client (honors server retry-after backoff).
  Re-run: 5/5 products fully enriched, tiers moved 5×Tier-0 → 5×Tier-II.
  Logged as model-behavior-log 2026-07-01 (Step 2) + a capability bet.

**Verification:** `verify_step2.py` — `POST /pipeline/start` on the fixture
returns 20 products with audit scores + tier labels. PASS. The live 20-product
enrichment leg (Gate 1→2) is gated behind `RIA_VERIFY_ENRICH=1` because it is
slow under free-tier TPM.

---

## Step 3 — Token tracking

**Commit:** pending (uncommitted at time of writing).

**Delivered:**
- `token_tracker.py`: `TokenTracker` reads `client.last_usage` (hooks it, no
  client restructuring), tagging each call by **phase** (enrichment |
  validation) and **index** (pre | post | none). Pricing per goals §5.
  - `query_comparison()` — HEADLINE metric (pre vs post per-query tokens/cost +
    % reduction), populated in Step 4.
  - `enrichment_summary()` / `enrichment_by_sku()` — secondary enrichment cost.
  - `count_tokens()` / `raw_product_prose()` — o200k_base data-size counting for
    baselines/Eval 4.
- Instrumented `enrich.py` (records every enrichment call, `phase=enrichment`,
  `label=sku`); wired into `/confirm-enrich` (response carries `token_metrics`;
  session persists `token_metrics.enrichment`).
- `docs/dataset-readiness.md` — full readiness assessment of the fixture.

**Problems + fixes:**
- **Concurrency race on shared `last_usage`.** Enrichment fans out per-dimension
  calls on one shared client. Fix: `record_last` is called synchronously
  immediately after the `await` with no intervening await, so `last_usage` still
  reflects that coroutine's own call. Known accepted limitation: on a JSON-retry
  only the second raw call's usage is captured (undercount); documented in code.
- **Eval 4 measurement was wrong (found via dataset-readiness).** Raw
  descriptions are already lean (max 41 tokens), so per-product raw-vs-enriched
  size comparison shows negative reduction for every product (FM-5 by
  construction). Reframed Eval 4 + FM-5 + the token-efficiency metric around
  **per-query** cost (pre vs post index), not per-product size. See goals §4b.

**Verification:**
- `verify_step3.py` (deterministic, synthetic usage): cost math, per-sku
  breakdown, pre/post `query_comparison`, phase-filter isolation. PASS.
- Live 2-product enrichment (real Groq): 7 per-call records captured; catalog
  summary `{calls:7, prompt:2082, completion:3083, total:5165, cost:$0.002162}`;
  per-product breakdown correct. Completion > prompt confirms the reasoning-token
  inflation behind FM-5.

Also this step: created `docs/build-log.md`; added goals §4b (Metrics
Framework); reframed Eval 4 + FM-5 around per-query cost.

---

## Step 4 — Validation agent

**Commit:** pending (uncommitted at time of writing).

**Delivered:**
- `agent.py`: Groq/OpenAI tool-use loop (ported from v1's Anthropic agent, goals
  §6). TOOL_DEFS converted to OpenAI function format; `ToolExecutor`
  (search/get_product_details/add_to_cart); checkout intent v2 (goals §11,
  `intent_version: ria/2.0`, UCP/AP2 blocks); TokenTracker instrumentation
  (`phase=validation`, `index=pre|post`); defensive plain-text tool-call fallback
  parser (present, did not fire).
- `agent_index.py`: ported `EnrichedProductIndex` (facet + by_sku indexes; pre
  index carries source attrs only, post index adds enriched agent_facets).
- `validate.py` API: `POST /validate/query` (single index) + `POST
  /validate/compare` (both indexes, one tracker → headline `query_comparison`).
- `scripts/verify_step4.py`: live enrich-subset + before/after agent runs.

**Problems + fixes:**
- **Turn cap too tight.** MAX_TURNS=4 (goals §5/§10) truncated the full
  search→details→add_to_cart→summary flow → "(no response)". Fixed: MAX_TURNS→6,
  restored forced final-summary turn, updated goals §5/§10.
- **gpt-oss over-searches.** Prompt-level "≤2 searches" ignored; search count was
  the main per-query token-noise source. Fixed: harness-enforced cap (drop
  search tool after 2 searches).
- **Enriched reads are heavier (FM-5 at query level).** `get_product_details`
  returned full 150–250-word enriched prose. Fixed: trim description + surface
  compact `agent_facets` + Q&A/relationship counts so a read stays bounded.

**Verification:** `verify_step4.py` (live, 8-product subset, controlled behavior:
2 searches → details → add_to_cart on both indexes).
- Flow search → get_product_details → add_to_cart on the **enriched** index:
  **PASS** (added navy-sport-jacket size M; `ria/2.0` checkout intent produced).
- Before/after token reduction (Eval 4): **FAIL at this scale** — pre 4822 vs
  post 4943 total (−2.5%). Not noise: with identical agent behavior, post is
  marginally heavier because enriched reads are richer (FM-5), the 8-product
  catalog makes keyword groping cheap, and "waterproof" is a literal description
  keyword so facets add no retrieval advantage. The headline win needs a larger
  enriched catalog (Dev Tier) and/or an inference-dependent query. Logged as an
  open capability bet. **Step 4 is flow-complete; the headline metric is blocked
  on catalog scale, not code.**

---
