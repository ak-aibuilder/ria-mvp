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
