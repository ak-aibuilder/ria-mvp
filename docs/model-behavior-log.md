# Model Behavior Log - RIA v2

Tracks predicted failure modes (FM-1..FM-5 from goals.md §3) and every
unexpected model behavior discovered during the build. Update in real time.

| FM | Prediction |
|---|---|
| FM-1 | Fabricated product attributes not in source CSV |
| FM-2 | Facet values outside controlled vocabulary |
| FM-3 | Hallucinated catalog SKUs in relationship enrichment |
| FM-4 | Agent shows only 1 result when multiple match |
| FM-5 | Negative token reduction (enrichment adds bloat) |

## Entry Template

```
### YYYY-MM-DD - short title
- **Step:** e.g. Step 4 (validation agent)
- **FM:** FM-? or "new"
- **What happened:**
- **What I changed:**
- **Tokens consumed:**
```

## Entries

### 2026-07-01 - Step 1 model integration baseline
- **Step:** Step 1 (scaffold + model integration)
- **FM:** none (baseline; no failure mode triggered)
- **What happened:** First live call to `openai/gpt-oss-120b` via Groq with
  `response_format={"type": "json_object"}` and the ENRICH_FACETS prompt on a
  sample "Alpine Waterproof Rain Jacket". Returned valid JSON on the first try:
  `{"agent_facets": {"weather": ["rain","warm"], "price_band": "100_200",
  "color": "navy"}}`. Two behaviors worth noting: (1) the model correctly
  omitted every facet it couldn't infer (occasion/fit/care/season/material)
  rather than guessing — the opposite of FM-1/FM-2, a good sign for the
  no-hallucination bet; (2) all emitted values were inside the controlled
  vocabulary. `response_format=json_object` meant the retry/`_extract_json`
  safety net never fired.
- **What I changed:** Nothing — behavior matched intent. Kept the defensive
  JSON-extraction + one-retry path from v1 in `groq_client.py` anyway.
- **Tokens consumed:** prompt=458, completion=510, total=968. The high
  completion count reflects gpt-oss reasoning tokens even at "Reasoning: low";
  worth watching against the FM-5 (token-bloat) bet in Step 3.

### 2026-07-01 - Step 2 free-tier rate limiting (429)
- **Step:** Step 2 (pipeline API — enrichment orchestrator)
- **FM:** new (infra/serving constraint, not one of FM-1..5)
- **What happened:** First full 5-product enrichment run fired up to ~20
  concurrent Groq calls (5 products x up to 4 gap dimensions). Groq's free tier
  ("on_demand", 8000 TPM) returned HTTP 429 rate_limit_exceeded on 6-7 of the
  calls, each reserving ~2.3k tokens. The orchestrator degraded gracefully
  (per-dim failures logged, products merged with whatever succeeded) so the
  pipeline still produced tier shifts, but ~1/3 of dimensions were dropped.
- **What I changed:** (1) `PRODUCT_CONCURRENCY` 8 -> 2 in enrich.py; (2) added
  `max_retries=6` to the AsyncOpenAI client so 429s self-heal via the SDK's
  retry-after backoff. Re-run: 5/5 products fully enriched (only 1 transient
  dim-level 429, absorbed), tiers moved 5xTier-0 -> 5xTier-II. Logged as a
  capability bet (docs/capability-bets.md).
- **Tokens consumed:** ~20 enrichment calls at ~1-2.5k tokens each per run;
  precise per-call accounting lands with the TokenTracker in Step 3.

### 2026-07-08 - Step 4 agent: turn cap, over-searching, and the headline miss
- **Step:** Step 4 (validation agent)
- **FM:** FM-5 (realized at the query level)
- **What happened:** Three distinct behaviors surfaced building the Groq
  tool-use agent:
  1. **MAX_TURNS=4 truncates the flow.** goals §5/§10 specified 4, but the full
     search -> get_product_details -> add_to_cart -> summary flow (plus one
     exploratory retry) needs ~6. At 4 the agent ran out of turns mid-flow and
     returned "(no response)". Also restored v1's forced final-summary turn.
  2. **gpt-oss over-searches.** Even with an explicit "at most two searches"
     rule in the system prompt, the agent ran 3 searches, and search count was
     the dominant source of per-query token noise (runs swung +6.1% / -24.5% /
     -5.6%). Fixed by enforcing the cap in the harness: after 2 searches, the
     search tool is dropped from the tool list for remaining turns.
  3. **The headline (Eval 4) does NOT pass on the free-tier 8-product subset.**
     Once behavior was controlled (both indexes: 2 searches -> details ->
     add_to_cart, 5 turns), post-enrichment cost -2.5% (marginally MORE): prompt
     4470 vs 4422, completion 473 vs 400. Root causes, isolated: (a) FM-5 —
     enriched products carry richer data so each read is heavier; (b) small
     catalog makes keyword groping cheap, so there's little for facets to save;
     (c) "waterproof" is a literal description keyword, so keyword search matches
     as well as a facet filter — facets only win on *inference* queries
     (wool->cold) or at catalog scale.
- **What I changed:** MAX_TURNS 4->6; forced final-summary turn; harness search
  cap (≤2); trimmed enriched description + compact facets in get_product_details
  so a single read stays bounded; decisive-purchase prompt. The text-tool-call
  fallback parser is in place but did NOT fire (native function calling worked).
  Logged the headline miss as a capability bet.
- **Tokens consumed per query (controlled):** pre 4822 total, post 4943 total
  (both ~$0.001/query). Enrichment of the 8-product subset ~$0.0073.
- **Verification outcome:** flow search->details->add_to_cart on the enriched
  index PASS (ria/2.0 checkout intent produced); positive token reduction FAIL
  at this scale — the win needs a larger enriched catalog and/or an
  inference-dependent query. See capability-bets + build-log Step 4.

### 2026-07-08 - Step 4 addendum: per-tool token breakdown + free-tier TPD exhausted
- **Step:** Step 4 (validation agent — diagnostic)
- **FM:** FM-5 (mechanism isolated)
- **What happened:** Deterministic offline measurement (pure tool functions +
  merger's no-LLM facet extractor, so no Groq) of tool-result payload tokens,
  pre vs post, on the 8-product subset:
  - `search_products`: PRE 325 tok (8 results) -> POST 89 tok (2 results),
    **-236 tok/call**. Driver: the `weather=rain` facet filter narrows 8->2;
    per-match projection is identical, only the count differs. This payload
    persists in context and is re-read every later turn, so it compounds.
  - `get_product_details`: PRE 119 -> POST 145, **+26 tok/call** (POST adds
    agent_facets; description trimmed keeps it bounded).
  - So the facet mechanism structurally favors POST (big search saving >> small
    details penalty). Yet the live total was flat/negative because (a) the agent
    did not reliably emit the facet filter — controlled-run POST prompt tokens
    (4470) ~= PRE (4422), proving the 8->2 narrowing usually didn't fire — and
    (b) gpt-oss reasoning/completion tokens dominate and are noisy (POST 473 vs
    PRE 400), swamping the data saving at 8-product scale.
  - **Also found a real bug:** enforcing the search cap by REMOVING
    search_products from the tools mid-conversation makes gpt-oss call a tool
    "not in request.tools" -> Groq 400. Fixed by keeping the tool present and
    returning a "search_limit_reached" nudge from the executor instead.
- **What I changed:** search-cap now returns a stop nudge (no tool removal);
  recorded the per-tool structural finding.
- **INFRA — free-tier daily budget exhausted:** the six cumulative live runs hit
  Groq's tokens-per-DAY cap (Limit 200000, Used ~199.5k). No further live gpt-oss
  calls until the daily window resets or Dev Tier. Lesson: iterate the agent
  against a mocked client; reserve live calls for a single final confirmation.
- **Tokens consumed:** ~200k for the day (daily cap). Offline diagnostic: 0 (no
  API calls).
