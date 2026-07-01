"""Enrichment prompt templates for RIA v2, adapted for GPT-OSS-120B via Groq.

Per goals.md §6: do NOT copy v1's prompts.py (those target Claude). These are
the adapted templates from goals.md §9. Each template is a dict with:
  - "system":       system prompt (first line is the Groq reasoning-effort hint)
  - "user_template": .format(**product_fields) -> user message
  - "output_key":    the top-level JSON key the merger reads

GAP_TO_PROMPT maps an audit gap dimension to the prompt that fills it.
"""
from __future__ import annotations

# Controlled vocabulary — every enrichment prompt references this (goals.md §9).
# Kept here as the single source of truth for the prompt text below; the merger
# enforces it independently in FACET_VOCAB.
CONTROLLED_VOCAB = {
    "occasion": ["casual", "work", "formal", "athletic", "loungewear", "wedding", "vacation"],
    "weather": ["hot", "warm", "mild", "cool", "cold", "rain", "snow"],
    "fit": ["slim", "regular", "relaxed", "oversized"],
    "care": ["machine_wash", "hand_wash", "dry_clean"],
    "season": ["spring", "summer", "fall", "winter"],
    "price_band": ["under_50", "50_100", "100_200", "200_plus"],
    "relationship_type": ["often_bought_with", "substitute", "complementary", "accessory_for"],
}


# Q&A enrichment (D3)
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


# Facet enrichment (D6)
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


# Description enrichment (D2)
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


# Relationship enrichment (D5)
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


GAP_TO_PROMPT = {
    "D2": ENRICH_DESCRIPTION,
    "D3": ENRICH_QA,
    "D5": ENRICH_RELATIONSHIPS,
    "D6": ENRICH_FACETS,
}
