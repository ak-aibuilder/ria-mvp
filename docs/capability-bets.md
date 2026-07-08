# Capability Bets

Features blocked by model limitations, not missing code. Populate as discovered
during the build — each row is a bet that a model capability (or its absence)
determines whether a feature can ship.

| Feature | Limitation | Model | Workaround | Status |
|---|---|---|---|---|
| Fast concurrent catalog enrichment | Groq free tier ("on_demand") caps at 8000 tokens/min; each enrichment call reserves ~2.3k tokens (max_tokens=2048 + prompt), so ~20 concurrent calls 429 immediately | `openai/gpt-oss-120b` on Groq | Throttle to 2 products in-flight (`PRODUCT_CONCURRENCY=2`) + SDK retry-on-429 with backoff (`max_retries=6`). Trades wall-clock for reliability. Removed by upgrading to Groq Dev Tier. | Mitigated (Step 2) |
