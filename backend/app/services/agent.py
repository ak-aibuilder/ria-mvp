"""ValidationAgent — Step 4 (goals.md §10-11).

Ported from v1's Claude tool-use loop (goals.md §6: extract TOOL_DEFS +
ToolExecutor, convert Anthropic format -> OpenAI/Groq function-calling format,
drop the Anthropic run_agent). The same agent runs against a pre-enrichment and
a post-enrichment index; what changes between the two demo runs is the data, not
the agent. Token usage per turn is recorded via TokenTracker (phase=validation,
index=pre|post) — the pre/post total is the headline metric.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from app.services.agent_index import EnrichedProductIndex
from app.services.groq_client import EnrichmentError, GroqEnrichmentClient
from app.services.token_tracker import PHASE_VALIDATION, TokenTracker, count_tokens

logger = logging.getLogger(__name__)

# goals.md §10 specifies 4, but the full search -> details -> add_to_cart ->
# summary flow (plus one exploratory retry) truncates at 4 before checkout. Bumped
# to 6 empirically; see model-behavior-log 2026-07-08 and goals §5/§10.
MAX_TURNS = 6

SYSTEM_PROMPT = (
    "Reasoning: medium\n\n"
    "You are a shopping assistant for an apparel retailer. "
    "Use the provided tools to search products, get details, and add to cart. "
    "NEVER invent SKUs or product attributes.\n\n"
    "Rules:\n"
    "1. Call search_products ONCE with the best filters for the request. Only "
    "search again if the first result was empty (then drop a filter). Never run "
    "more than two searches.\n"
    "2. Prefer structured facet filters (occasion, weather, season, price_max) "
    "over broad keyword queries when the request mentions them.\n"
    "3. When multiple products match, show top 2-3.\n"
    "4. Call get_product_details on your top candidate before confirming.\n"
    "5. When the shopper asks to buy or add an item, complete the flow "
    "decisively: search -> get_product_details -> add_to_cart, then confirm in "
    "one sentence. Do not ask follow-up questions for a clear buy request.\n"
    "6. Keep answers to 3 sentences or fewer."
)

# OpenAI/Groq function-calling format (converted from v1's Anthropic input_schema
# format). Closed-vocab enums mirror the controlled vocabulary (goals.md §9).
TOOL_DEFS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": (
                "Search the catalog by natural-language query and optional structured "
                "facet filters. Closed-vocab filters (occasion, weather, fit, care, "
                "season) MUST use one of the listed enum values exactly."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural-language search query."},
                    "filters": {
                        "type": "object",
                        "properties": {
                            "price_max": {"type": "number"},
                            "size": {"type": "string", "description": "Free-form (e.g. S, M, L, XL)."},
                            "color": {"type": "string", "description": "Free-form (e.g. black, navy, red)."},
                            "occasion": {"type": "string", "enum": ["casual", "work", "formal", "athletic", "loungewear", "wedding", "vacation"]},
                            "weather": {"type": "string", "enum": ["hot", "warm", "mild", "cool", "cold", "rain", "snow"]},
                            "season": {"type": "string", "enum": ["spring", "summer", "fall", "winter"]},
                            "fit": {"type": "string", "enum": ["slim", "regular", "relaxed", "oversized"]},
                            "care": {"type": "string", "enum": ["machine_wash", "hand_wash", "dry_clean"]},
                            "category": {"type": "string"},
                        },
                        "additionalProperties": False,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_details",
            "description": "Fetch the full enriched record for a single SKU.",
            "parameters": {
                "type": "object",
                "properties": {"sku": {"type": "string"}},
                "required": ["sku"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_to_cart",
            "description": "Stage a product in the cart for checkout.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sku": {"type": "string"},
                    "variant": {
                        "type": "object",
                        "properties": {"size": {"type": "string"}, "color": {"type": "string"}},
                    },
                    "quantity": {"type": "integer", "minimum": 1, "default": 1},
                },
                "required": ["sku"],
            },
        },
    },
]


def _flatten_attr(value) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {value.lower()}
    if isinstance(value, list):
        return {str(v).lower() for v in value if v}
    if isinstance(value, dict):
        return {str(k).lower() for k in value.keys()}
    return set()


def _project_search_match(p: dict) -> dict:
    return {
        "sku": p["sku"],
        "name": p.get("name"),
        "price": p.get("price"),
        "category": p.get("category"),
        "readiness_score": (p.get("score") or {}).get("readiness_score"),
    }


def _project_full(p: dict) -> dict:
    """Agent-facing product detail. Enrichment's value is that the agent can
    decide from compact structured facets instead of reading marketing prose, so
    we surface agent_facets and trim the (possibly 150-250 word enriched)
    description — reading full prose per product would erase the token win that
    facet filtering buys (FM-5 at query level). q_and_a/relationships are
    summarized to counts to keep a single read bounded."""
    desc = p.get("description") or ""
    return {
        "sku": p["sku"],
        "name": p.get("name"),
        "description": desc if len(desc) <= 240 else desc[:240] + "…",
        "price": p.get("price"),
        "category": p.get("category"),
        "brand": p.get("brand"),
        "attributes": p.get("attributes"),
        "agent_facets": p.get("agent_facets"),
        "q_and_a_count": len(p.get("q_and_a") or []),
        "relationship_count": len(p.get("relationship_type") or []),
    }


class ToolExecutor:
    """Pure-function toolkit. Holds an in-memory cart per agent run."""

    def __init__(self, index: EnrichedProductIndex) -> None:
        self.index = index
        self.cart: list[dict] = []

    def execute(self, name: str, payload: dict) -> dict:
        if name == "search_products":
            matches = self.index.search(
                query=payload.get("query", ""),
                filters=payload.get("filters") or {},
                limit=8,
            )
            return {
                "matches": [_project_search_match(p) for p in matches],
                "result_count": len(matches),
            }

        if name == "get_product_details":
            sku = payload.get("sku")
            if not sku or sku not in self.index.by_sku:
                return {"error": "sku_not_found", "sku": sku}
            return _project_full(self.index.by_sku[sku])

        if name == "add_to_cart":
            sku = payload.get("sku")
            qty = int(payload.get("quantity") or 1)
            variant = payload.get("variant") or {}
            if not sku or sku not in self.index.by_sku:
                return {"status": "sku_not_found", "sku": sku, "cart_preview": self.cart}
            product = self.index.by_sku[sku]
            attrs = product.get("attributes") or {}
            allowed_sizes = _flatten_attr(attrs.get("size"))
            allowed_colors = _flatten_attr(attrs.get("color"))
            if variant.get("size") and allowed_sizes and variant["size"].lower() not in allowed_sizes:
                return {"status": "invalid_variant", "reason": f"size {variant['size']!r} not in {sorted(allowed_sizes)}", "cart_preview": self.cart}
            if variant.get("color") and allowed_colors and variant["color"].lower() not in allowed_colors:
                return {"status": "invalid_variant", "reason": f"color {variant['color']!r} not in {sorted(allowed_colors)}", "cart_preview": self.cart}
            warnings: list[str] = []
            if variant.get("size") and not allowed_sizes:
                warnings.append(f"product carries no size attribute; size {variant['size']!r} is unverified")
            if variant.get("color") and not allowed_colors:
                warnings.append(f"product carries no color attribute; color {variant['color']!r} is unverified")
            cart_item = {
                "cart_item_id": str(uuid.uuid4()),
                "sku": sku,
                "name": product.get("name"),
                "unit_price": product.get("price"),
                "variant": variant,
                "quantity": qty,
            }
            self.cart.append(cart_item)
            return {
                "status": "added_unverified_variant" if warnings else "added",
                "cart_item_id": cart_item["cart_item_id"],
                "warnings": warnings or None,
                "cart_preview": self.cart,
            }

        return {"error": "unknown_tool", "tool": name}


def build_checkout_intent(*, cart: list[dict], index: EnrichedProductIndex, is_enriched: bool) -> dict | None:
    """Checkout intent v2 (goals.md §11). Structural protocol awareness (UCP/AP2),
    not live payment. Richer on the enriched side: line items carry agent_facets
    and the UCP block lists which enriched attributes are present."""
    if not cart:
        return None

    line_items: list[dict] = []
    enriched_present: set[str] = set()
    for item in cart:
        product = index.by_sku.get(item["sku"], {})
        li: dict = {
            "sku": item["sku"],
            "name": item["name"],
            "variant": item.get("variant") or {},
            "quantity": item.get("quantity", 1),
            "unit_price": item.get("unit_price") or 0.0,
            "currency": "USD",
        }
        if is_enriched:
            facets = product.get("agent_facets") or {}
            if facets:
                li["agent_facets"] = facets
                enriched_present.add("agent_facets")
            if product.get("q_and_a"):
                enriched_present.add("q_and_a")
            if product.get("relationship_type"):
                enriched_present.add("relationships")
        line_items.append(li)

    return {
        "intent_version": "ria/2.0",
        "agent": {"vendor": "RIA", "model": "gpt-oss-120b"},
        "line_items": line_items,
        "ucp": {
            "version": "0.2",
            "capabilities": {"cart": True, "catalog_realtime": False, "identity_linking": False},
            "checkout_path": "dual",
            "enriched_attributes": sorted(enriched_present),
        },
        "ap2": {
            "mandate_type": "bounded",
            "spending_guardrails": {"max_per_transaction": None, "approved_categories": ["apparel"]},
            "authorization_method": "cryptographic_mandate",
        },
        "payment_identity": {"wallet_integration": "google_wallet", "loyalty_linkable": False},
        "fulfillment": {"data_sufficiency": "agent_ready" if is_enriched else "human_review_recommended"},
    }


# Defensive fallback (goals.md §10 decision): GPT-OSS-120B has native function
# calling, but if a turn emits a tool call as plain-text JSON instead, parse it.
# Log every fire to the model behavior log.
_TOOL_JSON_RE = re.compile(r'\{[^{}]*"(?:tool|name)"\s*:\s*"(search_products|get_product_details|add_to_cart)".*?\}', re.DOTALL)


def _parse_text_tool_call(text: str) -> tuple[str, dict] | None:
    if not text:
        return None
    m = _TOOL_JSON_RE.search(text)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    name = obj.get("tool") or obj.get("name")
    args = obj.get("arguments") or obj.get("input") or obj.get("parameters") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    if name in {"search_products", "get_product_details", "add_to_cart"}:
        return name, args if isinstance(args, dict) else {}
    return None


async def run_agent(
    *,
    query: str,
    index: EnrichedProductIndex,
    index_label: str,
    client: GroqEnrichmentClient,
    tracker: TokenTracker | None = None,
) -> dict:
    """One Groq tool-use loop. index_label is "pre" or "post" — it tags the
    validation token usage so TokenTracker.query_comparison() can compare them."""
    toolkit = ToolExecutor(index)
    tool_calls: list[dict] = []
    turn_log: list[dict] = []  # per-turn usage + emitted tool + result-payload size
    fallback_fired = False
    search_count = 0

    def _log_turn(emitted: list[str], result_tokens: int) -> None:
        u = getattr(client, "last_usage", None)
        turn_log.append({
            "emitted": emitted,
            "prompt_tokens": int(getattr(u, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(u, "completion_tokens", 0) or 0),
            "result_tokens": result_tokens,  # o200k_base size of tool results this turn
        })

    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": query},
    ]
    final_text = ""
    turns_used = 0
    terminator = "max_turns"

    for turn in range(MAX_TURNS):
        turns_used = turn + 1
        message = await client.chat(messages=messages, tools=TOOL_DEFS, tool_choice="auto")
        # Record usage synchronously right after the await (sequential loop, but
        # keep the same last_usage pattern as enrichment).
        if tracker is not None:
            tracker.record_last(client, phase=PHASE_VALIDATION, index=index_label)

        native_calls = getattr(message, "tool_calls", None) or []

        # Native function calling path.
        if native_calls:
            messages.append({
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [
                    {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in native_calls
                ],
            })
            emitted: list[str] = []
            result_tokens = 0
            for tc in native_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                # Enforce the "at most 2 searches" workflow rule in the harness
                # (gpt-oss doesn't reliably self-limit, and re-searching is the
                # main per-query token-noise source). Keep the tool in the request
                # — removing it makes the model call a tool not in request.tools,
                # which Groq 400s — and instead return a stop-searching nudge.
                if tc.function.name == "search_products" and search_count >= 2:
                    result = {"error": "search_limit_reached",
                              "hint": "Enough searching. Pick from earlier results, "
                                      "call get_product_details, then add_to_cart."}
                else:
                    if tc.function.name == "search_products":
                        search_count += 1
                    result = toolkit.execute(tc.function.name, args if isinstance(args, dict) else {})
                result_json = json.dumps(result)
                tool_calls.append({"name": tc.function.name, "args": args, "result": result})
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_json})
                emitted.append(tc.function.name)
                result_tokens += count_tokens(result_json)
            _log_turn(emitted, result_tokens)
            continue

        # Fallback: tool call emitted as plain text.
        parsed = _parse_text_tool_call(message.content or "")
        if parsed:
            fallback_fired = True
            name, args = parsed
            logger.warning("agent text-tool-call fallback fired (index=%s): %s %s", index_label, name, args)
            result = toolkit.execute(name, args)
            result_json = json.dumps(result)
            tool_calls.append({"name": name, "args": args, "result": result, "via": "text_fallback"})
            messages.append({"role": "assistant", "content": message.content or ""})
            messages.append({"role": "user", "content": f"tool_result for {name}: {result_json}"})
            _log_turn([name], count_tokens(result_json))
            continue

        # No tool calls -> natural completion.
        final_text = (message.content or "").strip()
        terminator = "natural"
        _log_turn(["final"], 0)
        break
    else:
        # Hard turn cap reached mid-tool-use (goals §10). Force one no-tool
        # summary turn so the shopper always gets an answer instead of silence.
        try:
            summary = await client.chat(
                messages=messages
                + [{
                    "role": "user",
                    "content": "Tool budget reached. Give your best final answer "
                    "for the shopper in 3 sentences or fewer. Do not call tools.",
                }],
                tools=None,
            )
            if tracker is not None:
                tracker.record_last(client, phase=PHASE_VALIDATION, index=index_label)
            _log_turn(["final"], 0)
            final_text = (summary.content or "").strip()
        except EnrichmentError:
            final_text = final_text or "I couldn't finish within the tool budget."

    return {
        "index_type": index_label,
        "query_text": query,
        "tool_calls": tool_calls,
        "turn_log": turn_log,
        "agent_response": final_text or "(no response)",
        "turns_used": turns_used,
        "terminator": terminator,
        "fallback_fired": fallback_fired,
        "cart_preview": toolkit.cart,
        "checkout_intent": build_checkout_intent(
            cart=toolkit.cart, index=index, is_enriched=(index_label == "post")
        ),
    }
