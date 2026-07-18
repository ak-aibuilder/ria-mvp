"""TokenTracker — Step 3 (goals.md §13: "Pipeline response includes token metrics").

Accumulates per-call LLM token usage read from GroqEnrichmentClient.last_usage.
The client already stores the OpenAI usage object on every call, so we hook that
rather than restructuring the client. Each call is tagged along two axes:

  phase  — "enrichment" | "validation"
  index  — "pre" | "post" | None   (which catalog a validation query ran
           against: the raw pre-enrichment catalog vs the enriched post one)

The HEADLINE demo metric is the per-query before/after comparison
(`query_comparison`): total tokens an agent burns answering a question against
the raw catalog vs the enriched catalog. That is populated in Step 4 when the
validation agent is instrumented the same way enrichment is here.

The SECONDARY metric is enrichment cost itself (`enrichment_summary` /
`enrichment_by_sku`): "it cost $X to enrich this catalog, and each subsequent
query is Y% cheaper."

Pricing per 1M tokens, goals.md §5 (as of June 2026):
  gpt-oss-120b: $0.15 in / $0.60 out
  gpt-oss-20b:  $0.075 in / $0.30 out
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import tiktoken

from app.core.config import get_settings

# Tokenizer for measuring *data-size* token counts of raw/enriched product text
# (goals.md §5: o200k_base). This is distinct from live-call usage above: it
# powers the "before" baseline for the per-query cost comparison and Eval 4.
_ENCODING_NAME = "o200k_base"
_encoder: Any | None = None


def _get_encoder() -> Any:
    global _encoder
    if _encoder is None:
        _encoder = tiktoken.get_encoding(_ENCODING_NAME)
    return _encoder


def count_tokens(text: str) -> int:
    if not text:
        return 0
    return len(_get_encoder().encode(text))


def raw_product_prose(product: dict) -> str:
    """The product's raw agent-facing text: description + attributes as prose.

    This is the data-size representation an agent must read per product from the
    unenriched catalog — the "before" number for the per-query cost story.
    """
    parts: list[str] = []
    desc = (product.get("description") or "").strip()
    if desc:
        parts.append(desc)
    attrs = product.get("attributes") or {}
    if isinstance(attrs, dict) and attrs:
        parts.append("; ".join(f"{k}: {v}" for k, v in attrs.items()))
    return "\n".join(parts)

PHASE_ENRICHMENT = "enrichment"
PHASE_VALIDATION = "validation"
INDEX_PRE = "pre"
INDEX_POST = "post"

# USD per 1,000,000 tokens.
PRICING: dict[str, dict[str, float]] = {
    "openai/gpt-oss-120b": {"input": 0.15, "output": 0.60},
    "openai/gpt-oss-20b": {"input": 0.075, "output": 0.30},
}
_DEFAULT_PRICE_MODEL = "openai/gpt-oss-120b"


def call_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """USD cost of one call. Unknown models fall back to primary-model pricing so
    a cost is always produced; the real model name is kept on the record."""
    price = PRICING.get(model, PRICING[_DEFAULT_PRICE_MODEL])
    return (
        prompt_tokens / 1_000_000 * price["input"]
        + completion_tokens / 1_000_000 * price["output"]
    )


@dataclass
class CallRecord:
    phase: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    index: str | None = None
    label: str | None = None

    @property
    def cost_usd(self) -> float:
        return call_cost(self.model, self.prompt_tokens, self.completion_tokens)


def _aggregate(records: Iterable[CallRecord]) -> dict[str, Any]:
    calls = prompt = completion = total = 0
    cost = 0.0
    for r in records:
        calls += 1
        prompt += r.prompt_tokens
        completion += r.completion_tokens
        total += r.total_tokens
        cost += r.cost_usd
    return {
        "calls": calls,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "cost_usd": round(cost, 6),
    }


def _reduction_pct(before: float, after: float) -> float:
    """Percent drop from before -> after (positive = cheaper). 0 if no baseline."""
    if before <= 0:
        return 0.0
    return round((before - after) / before * 100, 1)


class TokenTracker:
    def __init__(self, model: str | None = None) -> None:
        self.records: list[CallRecord] = []
        # Enrichment and the validation agent both run on the primary model; a
        # per-record model override is still supported for the fallback model.
        self._default_model = model or get_settings().GROQ_MODEL

    # --- recording -------------------------------------------------------
    def record(
        self,
        usage: Any,
        *,
        phase: str,
        index: str | None = None,
        model: str | None = None,
        label: str | None = None,
    ) -> None:
        """Append one call's usage. `usage` is an OpenAI usage object; None
        (e.g. a failed call that never returned usage) is silently skipped."""
        if usage is None:
            return
        prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion = int(getattr(usage, "completion_tokens", 0) or 0)
        total = int(
            getattr(usage, "total_tokens", prompt + completion) or (prompt + completion)
        )
        self.records.append(
            CallRecord(
                phase=phase,
                model=model or self._default_model,
                prompt_tokens=prompt,
                completion_tokens=completion,
                total_tokens=total,
                index=index,
                label=label,
            )
        )

    def record_last(
        self,
        client: Any,
        *,
        phase: str,
        index: str | None = None,
        label: str | None = None,
    ) -> None:
        """Record the client's most recent call.

        Call this synchronously immediately after `await client.call_json(...)`.
        With no await between that call returning and this read, the shared
        `last_usage` still reflects this coroutine's own final raw call, so it is
        safe under the concurrent per-dimension enrichment fan-out.

        Caveat: on a JSON-retry `call_json` makes two raw calls and `last_usage`
        holds only the second, so a retried call's first attempt is undercounted.
        Retries are rare under response_format=json_object; accepted per the
        "hook last_usage, don't restructure the client" constraint.
        """
        self.record(
            getattr(client, "last_usage", None), phase=phase, index=index, label=label
        )

    # --- reporting -------------------------------------------------------
    def _filter(self, *, phase=None, index=None) -> list[CallRecord]:
        return [
            r
            for r in self.records
            if (phase is None or r.phase == phase)
            and (index is None or r.index == index)
        ]

    def enrichment_summary(self) -> dict[str, Any]:
        """Catalog-level enrichment cost (secondary metric)."""
        return _aggregate(self._filter(phase=PHASE_ENRICHMENT))

    def enrichment_by_sku(self) -> dict[str, dict[str, Any]]:
        """Per-product enrichment token efficiency, keyed by the record label
        (the SKU set at instrumentation time)."""
        groups: dict[str, list[CallRecord]] = {}
        for r in self._filter(phase=PHASE_ENRICHMENT):
            groups.setdefault(r.label or "(unlabeled)", []).append(r)
        return {sku: _aggregate(recs) for sku, recs in groups.items()}

    def query_comparison(self) -> dict[str, Any]:
        """Headline metric: tokens + cost an agent spends per query against the
        raw (pre) vs enriched (post) catalog, and the reduction between them."""
        pre = _aggregate(self._filter(phase=PHASE_VALIDATION, index=INDEX_PRE))
        post = _aggregate(self._filter(phase=PHASE_VALIDATION, index=INDEX_POST))
        return {
            "pre": pre,
            "post": post,
            "token_reduction_pct": _reduction_pct(
                pre["total_tokens"], post["total_tokens"]
            ),
            "cost_reduction_pct": _reduction_pct(pre["cost_usd"], post["cost_usd"]),
        }

    def summary(self) -> dict[str, Any]:
        return {
            "enrichment": self.enrichment_summary(),
            "query_comparison": self.query_comparison(),
        }
