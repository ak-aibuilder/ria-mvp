# RIA v2 - Goals and Build Spec

**Framework:** Anthropic Weekly Product Development
**Build target:** 2 weeks (scope exceeds one week; weekly checkpoints apply)

---

## 1. User + Problem

A catalog operations lead at a mid-market D2C retailer needs to know which products in their catalog will fail when an AI shopping agent tries to reason over them, because their product data was built for SEO and human browsing, not for agent consumption.

## 2. Delightful Use Case

Upload a 20-product CSV. Within 60 seconds, see a tier distribution: 14 products at Tier I, 6 not agent-ready, zero at Tier II or III. The inference cost projection says this catalog costs $0.47 per agent query at current token counts.

Confirm enrichment. RIA's agent generates conversational Q&A pairs, structured facets, and relationship metadata. 30 seconds later, the tier distribution shifts: 8 at Tier III (Graph Ready), 10 at Tier II (API Ready), 2 at Tier I. Token cost drops to $0.08 per query. That's 83% less inference spend at scale.

Ask the before/after agent: "What's the best jacket for a rainy day in size M under $200?" The pre-enrichment agent gropes around with keyword search. The post-enrichment agent uses weather=rain and price_max=200 facet filters, finds the right product, checks details, adds to cart, and generates a checkout intent with UCP capability declarations and AP2 spending guardrails.

Download the UCP supplemental feed (upload to Google Merchant Center), the ACP product feed (for ChatGPT discovery), and the Amazon ASA readiness report.

## 3. Failure Modes

FM-1: GPT-OSS-120B fabricates product attributes not present in the source CSV (e.g., invents "water-resistant" for a product where the description doesn't mention it).

FM-2: Facet enrichment assigns values outside the controlled vocabulary (e.g., occasion="everyday" instead of "casual").

FM-3: Relationship enrichment hallucinates SKUs that don't exist in the catalog.

FM-4: The validation agent stops after finding one product instead of surfacing 2-3 options when multiple products match the query.

FM-5: Token tracking shows negative reduction (enriched output is LARGER than raw input), meaning enrichment added bloat instead of structuring the data.

## 4. Five Evals

```
Eval 1: Given a catalog with 20 products where 8 are missing Q&A pairs,
        the audit should flag exactly those 8 with D3 below threshold.
        Pass: 8/8 flagged, 0 false positives. Fail: anything else.
        Scoring: 5 = exact. 4 = 7/8 or 1 false positive. 3 = 6/8.
        2 = < 6/8. 1 = wrong dimension flagged. 0 = audit crashes.
        Threshold: >= 4

Eval 2: Given a product with no description, enrichment should generate
        a description containing material, fit, and occasion, using only
        facts present in the product's existing attributes.
        Pass: all three present, no hallucinated facts. Fail: any missing
        or any fact not derivable from source data.
        Scoring: 5 = all three + zero hallucination. 4 = 2/3 present.
        3 = 1/3 present. 0 = hallucinated facts. Threshold: >= 4

Eval 3: Given "waterproof jacket under $200 in size M" on the enriched
        catalog, the agent should find at least one matching product
        using structured facet filters (not keyword search alone).
        Pass: correct product found via weather/price filters.
        Fail: hallucinated product, or found via keyword only, or nothing.
        Scoring: 5 = correct product via structured filters + checkout intent.
        4 = correct product via filters, no checkout intent.
        3 = correct product via keyword only. 2 = wrong product.
        0 = hallucinated. Threshold: >= 3.5

Eval 4: Token tracking should report a positive token_reduction_pct for
        every enriched product (structured JSON should be smaller than
        raw marketing prose in token count).
        Pass: all products show positive reduction. Fail: any negative.
        Scoring: 5 = all positive. 4 = 1 negative. 3 = 2 negative.
        0 = majority negative. Threshold: >= 4

Eval 5: UCP supplemental feed export should produce valid JSON where every
        entry has an "id" matching a catalog SKU, and no entry references
        a SKU not in the catalog.
        Pass: all entries valid. Fail: any missing id or phantom SKU.
        Scoring: 5 = perfect. 4 = 1 error. 3 = 2-3 errors.
        0 = structurally invalid JSON. Threshold: >= 4
```

---

## 5. Technical Context for Build

### What v2 changes from v1

1. **Architecture:** Pipeline becomes agent-driven with two HITL gates, replacing v1's four-tab wizard.
2. **Models:** GPT-OSS-120B via Groq replaces Anthropic Claude. GPT-OSS-20B as enrichment-only fallback.
3. **Features:** Token cost tracking, three-tier readiness labels, multi-protocol exports (UCP, ACP, ASA), updated checkout intent with AP2 and UCP fields.

### Tech stack

- Backend: FastAPI (Python 3.11+)
- Frontend: Next.js (React/TypeScript)
- Database: MongoDB Atlas
- Inference: Groq API (OpenAI-compatible SDK)
- Models: `openai/gpt-oss-120b` (primary), `openai/gpt-oss-20b` (fallback)
- Hosting: Railway

### Model configuration

```python
# Enrichment (Phases 1-3)
model = "openai/gpt-oss-120b"
temperature = 0.3
max_tokens = 2048
response_format = {"type": "json_object"}
# Add "Reasoning: low" as first line of system prompt

# Validation agent (Phase 4)
model = "openai/gpt-oss-120b"
temperature = 0.2
max_tokens = 1024
tool_choice = "auto"
max_turns = 4
# Add "Reasoning: medium" as first line of system prompt

# Fallback (enrichment only, not for agent)
model = "openai/gpt-oss-20b"

# Token counting
tokenizer = tiktoken.get_encoding("o200k_base")

# Pricing (per 1M tokens, as of June 2026)
# gpt-oss-120b: $0.15 input / $0.60 output
# gpt-oss-20b: $0.075 input / $0.30 output
```

---

## 6. What to Extract from v1

Clone `https://github.com/ak-aibuilder/ria-v1` as read-only reference. Copy these four things:

**audit.py** - Copy as-is. Add `assign_tier()` function and token counting. Pure Python, no LLM dependency.

**merger.py** - Copy unchanged. Production-grade merge logic with provenance tracking.

**prompts.py** - Do NOT copy v1 originals (they target Claude). Use the adapted prompts below.

**Tool schemas from agent.py** - Extract `TOOL_DEFS` (search_products, get_product_details, add_to_cart) and `ToolExecutor` class. Convert from Anthropic format to OpenAI format. Do NOT copy `run_agent` (it uses the Anthropic SDK).

---

## 7. Pipeline Architecture

### v1 (wizard, replacing this)

User clicks Upload -> clicks Audit -> clicks Enrich -> clicks Validate

### v2 (agentic with HITL gates)

```
Upload CSV
  -> auto ingest + audit (no LLM)
  -> GATE 1: user reviews scores, confirms enrichment
  -> auto enrich (GPT-OSS-120B) + re-audit
  -> GATE 2: user reviews enriched data, confirms validation
  -> validation agent runs (GPT-OSS-120B)
  -> results: before/after, token costs, tier shifts, exports
```

### API endpoints

```
POST /api/v1/pipeline/start           (CSV upload, returns audit results)
POST /api/v1/pipeline/confirm-enrich  (Gate 1, runs enrichment + re-audit)
POST /api/v1/pipeline/confirm-validate (Gate 2, enables validation)
POST /api/v1/validate/query           (agent query, pre or post enrichment)
GET  /api/v1/exports/{session}/{format} (ucp|acp|asa|csv)
GET  /api/v1/pipeline/status/{session}
```

### Frontend

Single scrolling page, not tabs. Upload at top, audit results appear automatically, Gate 1 button, enrichment results with before/after, Gate 2 button, validation chat with side-by-side comparison, export download buttons at bottom.

---

## 8. Tier Classification

```python
# Decision: three tiers mapped to audit scores
def assign_tier(scores):
    overall = scores["readiness_score"]
    dims = scores["dimension_scores"]
    if overall >= 8.0 and dims.get("D5", 0) >= 6.0 and all(v >= 5.0 for v in dims.values()):
        return {"tier": "III", "label": "Graph Ready"}
    if overall >= 6.5 and dims.get("D3", 0) >= 6.0 and dims.get("D6", 0) >= 6.0:
        return {"tier": "II", "label": "API Ready"}
    if overall >= 4.0 and dims.get("D1", 0) >= 6.0:
        return {"tier": "I", "label": "Markup Ready"}
    return {"tier": "0", "label": "Not Agent Ready"}
```

---

## 9. Enrichment Prompts (adapted for GPT-OSS-120B)

### Controlled vocabulary (all enrichment prompts reference this)

```
occasion: casual, work, formal, athletic, loungewear, wedding, vacation
weather: hot, warm, mild, cool, cold, rain, snow
fit: slim, regular, relaxed, oversized
care: machine_wash, hand_wash, dry_clean
season: spring, summer, fall, winter
price_band: under_50, 50_100, 100_200, 200_plus
relationship_type: often_bought_with, substitute, complementary, accessory_for
```

### Q&A enrichment (D3)

```python
ENRICH_QA = {
    "system": (
        "Reasoning: low\n\n"
        "Generate customer Q&A pairs for apparel products. "
        "Use ONLY the provided attributes. Do not invent facts. "
        "Return valid JSON only."
    ),
    "user_template": (
        "Product: {name}\nDescription: {description}\n"
        "Attributes: {attributes_json}\nCategory: {category}\n\n"
        "Generate 3-5 Q&A pairs covering at least two intents from: "
        "sizing, material, care, occasion, fit, styling.\n"
        "If an answer requires information not in the attributes, "
        'set "speculative": true.\n\n'
        'Return: {{"q_and_a": [{{"question": "...", "answer": "...", '
        '"intent": "...", "speculative": false}}, ...]}}'
    ),
    "output_key": "q_and_a",
}
```

### Facet enrichment (D6)

```python
ENRICH_FACETS = {
    "system": (
        "Reasoning: low\n\n"
        "Extract structured facets from apparel products.\n"
        "Controlled vocabulary:\n"
        "  occasion: casual, work, formal, athletic, loungewear, wedding, vacation\n"
        "  weather: hot, warm, mild, cool, cold, rain, snow\n"
        "  fit: slim, regular, relaxed, oversized\n"
        "  care: machine_wash, hand_wash, dry_clean\n"
        "  season: spring, summer, fall, winter\n"
        "  price_band: under_50, 50_100, 100_200, 200_plus\n"
        "Use ONLY these values. Return valid JSON only.\n\n"
        "Inference rules:\n"
        "- waterproof/water-resistant/rain -> weather includes 'rain'\n"
        "- thermal/fleece/wool/parka/insulated -> weather includes 'cold'\n"
        "- lightweight/breathable/linen/summer -> weather includes 'hot' or 'warm'\n"
        "- silk/satin/tuxedo/gown -> occasion includes 'formal'\n"
        "- athletic/sporty/gym/running/yoga -> occasion includes 'athletic'\n"
        "- jeans/tee/hoodie/everyday -> occasion includes 'casual'\n"
        "- Always emit weather for outerwear categories.\n"
        "- Always emit color/material when visible in product name."
    ),
    "user_template": (
        "Product: {name}\nDescription: {description}\n"
        "Category: {category}\nPrice: {price}\n"
        "Attributes: {attributes_json}\n\n"
        'Return: {{"agent_facets": {{"occasion": [...], "weather": [...], '
        '"fit": "...", "care": "...", "season": [...], "price_band": "...", '
        '"color": "...", "material": "..."}}}}\n'
        "Omit any facet you cannot infer with high confidence."
    ),
    "output_key": "agent_facets",
}
```

### Description enrichment (D2)

```python
ENRICH_DESCRIPTION = {
    "system": (
        "Reasoning: low\n\n"
        "Rewrite product descriptions to be richer and agent-consumable. "
        "Do NOT invent product facts. Expand only on stated attributes. "
        "Return valid JSON only."
    ),
    "user_template": (
        "Product: {name}\nOriginal description: {description}\n"
        "Attributes: {attributes_json}\nCategory: {category}\n\n"
        "Rewrite to 150-250 words. Lead with what the product is, "
        "then fit/feel, then use-cases and styling.\n\n"
        'Return: {{"enhanced_description": "...", '
        '"claims_preserved": ["..."], "claims_added": ["..."]}}'
    ),
    "output_key": "enhanced_description",
}
```

### Relationship enrichment (D5)

```python
ENRICH_RELATIONSHIPS = {
    "system": (
        "Reasoning: low\n\n"
        "Suggest product relationships using ONLY SKUs from the provided catalog. "
        "Do not invent SKUs. Return valid JSON only."
    ),
    "user_template": (
        "Focus product: {sku} - {name} ({category})\n"
        "Catalog (SKU, name, category):\n{catalog_summary}\n\n"
        "Suggest 2-4 relationships. Valid types: often_bought_with, "
        "substitute, complementary, accessory_for.\n\n"
        'Return: {{"relationships": [{{"related_sku": "...", '
        '"relationship_type": "...", "rationale": "short explanation"}}]}}'
    ),
    "output_key": "relationships",
}

GAP_TO_PROMPT = {"D2": ENRICH_DESCRIPTION, "D3": ENRICH_QA,
                 "D5": ENRICH_RELATIONSHIPS, "D6": ENRICH_FACETS}
```

---

## 10. Validation Agent

```python
MAX_TURNS = 4

SYSTEM_PROMPT = (
    "Reasoning: medium\n\n"
    "You are a shopping assistant for an apparel retailer. "
    "Use the provided tools to search products, get details, and add to cart. "
    "NEVER invent SKUs or product attributes.\n\n"
    "Rules:\n"
    "1. Always call search_products for new queries.\n"
    "2. If search returns 0 results, retry with fewer filters.\n"
    "3. When multiple products match, show top 2-3.\n"
    "4. Call get_product_details before confirming availability.\n"
    "5. Call add_to_cart only when the user agrees.\n"
    "6. Keep answers to 3 sentences or fewer."
)

# Decision: keep a fallback parser for tool calls emitted as plain text.
# GPT-OSS-120B has native function calling, so this is defensive.
# Log every time it fires to the model behavior log.
```

Tool schemas: see v1's agent.py, convert to OpenAI `parameters` format. Three tools: search_products (with facet filter enums matching the controlled vocabulary), get_product_details (by SKU), add_to_cart (SKU + variant + quantity).

---

## 11. Checkout Intent v2

The validation agent generates a checkout intent payload after add_to_cart. Include these protocol fields:

```python
# Decision: structural protocol awareness, not live payment processing
checkout_intent = {
    "intent_version": "ria/2.0",
    "agent": {"vendor": "RIA", "model": "gpt-oss-120b"},
    "line_items": [...],  # from cart
    "ucp": {
        "version": "0.2",
        "capabilities": {"cart": True, "catalog_realtime": False, "identity_linking": False},
        "checkout_path": "dual",
        "enriched_attributes": ["agent_facets", "q_and_a", "relationships"],
    },
    "ap2": {
        "mandate_type": "bounded",
        "spending_guardrails": {"max_per_transaction": None, "approved_categories": ["apparel"]},
        "authorization_method": "cryptographic_mandate",
    },
    "payment_identity": {"wallet_integration": "google_wallet", "loyalty_linkable": False},
    "fulfillment": {"data_sufficiency": "agent_ready"},
}
```

---

## 12. Export Endpoints

Four exports at `GET /api/v1/exports/{session}/{format}`:

**ucp_supplemental** (JSON): Each entry has id (SKU), title, product_highlight (non-speculative Q&A answers), compatible_products (complementary SKUs), substitute_products, lifestyle (occasion facets), season.

**acp_feed** (JSONL): Each entry has id, title (max 150 chars), description (max 5000 chars), price (amount + currency), availability, url, eligibility (search: true, checkout: false).

**asa_readiness** (JSON): Summary with total products, ready count (Tier II+III), percentage, recommendation. Requirements coverage: structured data, Q&A, relationships, brand voice (not generated).

**enriched_csv** (CSV): All original fields plus flattened enriched columns.

---

## 13. Build Sequence

### Step 1: Scaffold + model integration

Initialize FastAPI backend + Next.js frontend. Set up Groq client. Copy audit.py and merger.py from v1. Add prompt templates. Add assign_tier() function.

**Verify:** A single enrichment call to GPT-OSS-120B via Groq returns valid JSON.

### Step 2: Pipeline API

Build all pipeline endpoints. Implement CSV ingest, audit scoring, enrichment orchestrator, merger integration.

**Verify:** POST /pipeline/start with 5 products returns audit scores with tier labels.

### Step 3: Token tracking

Add TokenTracker class. Instrument all Groq calls. Add per-product token efficiency. Add catalog-level cost summary.

**Verify:** Pipeline response includes token metrics.

### Step 4: Validation agent

Implement agent loop with GPT-OSS-120B. Port ToolExecutor and agent_index from v1. Add checkout intent v2.

**Verify:** Agent executes search -> details -> add_to_cart correctly.

### Step 5: Frontend

Build single-page pipeline view. Upload, audit results, Gate 1, enrichment results, Gate 2, validation chat, exports.

### Step 6: Exports

UCP supplemental feed, ACP feed, ASA readiness report, enriched CSV.

**Verify:** Each export produces valid, downloadable output.

### Step 7: Evals + docs

Run the 5 evals. Record results. Populate model behavior log with all entries discovered during build. Create dataset-readiness section documenting which products exercise which dimensions.

Run a validation script (`scripts/validate.py`) that executes deterministic checks: audit fixture scores match expected values, tier classification is correct, export SKUs are valid, token math sums correctly.

### Step 8: Railway deployment

Backend Dockerfile (Python 3.11, FastAPI), frontend Dockerfile (Node 20, Next.js). Set GROQ_API_KEY and MONGODB_URI.

**Verify:** Full pipeline works at Railway URL.

---

## 14. What NOT to Build

- No live payment processing. AP2 fields are structural.
- No Shopify app. CSV upload only.
- No embedding/vector search. Keyword overlap is fine for 20 products.
- No multi-model abstraction. Groq is the only provider.
- No Google Wallet mock. Acknowledge it, don't simulate it.
- No channel archetype selector. Hardcode D2C weights.
- No Qwen, Kimi K2, or Llama. They are deprecated or preview on Groq.
- No fallback model for the validation agent. GPT-OSS-20B is too small.

---

## 15. Docs Structure (Anthropic Framework)

CC should create these files during the build:

```
docs/
  goals.md                  (this file)
  model-behavior-log.md     (create at Step 1, update in real time)
  capability-bets.md        (create at Step 1, populate as discovered)
  weekly-metrics.md         (create at Step 1, update weekly)
  eval-results.md           (create at Step 7, populate with eval run results)
  token-cost-analysis.md    (create at Step 7, populate after pipeline run)
scripts/
  validate.py               (create at Step 7, automated eval checks)
```

### model-behavior-log.md template

```markdown
# Model Behavior Log - RIA v2

| FM | Prediction |
|---|---|
| FM-1 | Fabricated product attributes not in source CSV |
| FM-2 | Facet values outside controlled vocabulary |
| FM-3 | Hallucinated catalog SKUs in relationship enrichment |
| FM-4 | Agent shows only 1 result when multiple match |
| FM-5 | Negative token reduction (enrichment adds bloat) |

## Entry Template
### YYYY-MM-DD - short title
- **Step:** e.g. Step 4 (validation agent)
- **FM:** FM-? or "new"
- **What happened:**
- **What I changed:**
- **Tokens consumed:**
```

### capability-bets.md template

```markdown
# Capability Bets

Features blocked by model limitations, not missing code.

| Feature | Limitation | Model | Workaround | Status |
|---|---|---|---|---|
```

### weekly-metrics.md template

```markdown
# Weekly Metrics

| Week | Focus | Eval pass rate | Model behaviors logged | Capability bets | Features removed |
|---|---|---|---|---|---|
| 1 | Scaffold + pipeline + agent | | | | |
| 2 | Frontend + exports + deploy | | | | |
```

---

## Environment Variables

```
GROQ_API_KEY=gsk_...
MONGODB_URI=mongodb+srv://...
MONGODB_DB_NAME=ria_v2
CORS_ORIGINS=["http://localhost:3000","https://your-railway-url.up.railway.app"]
```
