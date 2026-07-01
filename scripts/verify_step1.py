"""Step 1 verification (goals.md §13): a single enrichment call to
GPT-OSS-120B via Groq returns valid JSON.

Runs the ENRICH_FACETS prompt on one sample product, asserts the response is a
dict containing the prompt's output_key, and prints token usage so the model
behavior log can be filled in. Loads GROQ_API_KEY from the repo-root .env.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# Make `app...` importable when run from repo root.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def _load_root_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_root_env()

from app.services.groq_client import GroqEnrichmentClient  # noqa: E402
from app.services.prompts import ENRICH_FACETS  # noqa: E402

SAMPLE = {
    "name": "Alpine Waterproof Rain Jacket",
    "description": "A lightweight breathable shell built for wet-weather hikes.",
    "category": "Outerwear > Jackets",
    "price": 149.0,
    "attributes": {"size": ["S", "M", "L"], "color": "navy"},
}


async def main() -> int:
    client = GroqEnrichmentClient()
    user = ENRICH_FACETS["user_template"].format(
        name=SAMPLE["name"],
        description=SAMPLE["description"],
        category=SAMPLE["category"],
        price=SAMPLE["price"],
        attributes_json=json.dumps(SAMPLE["attributes"]),
    )
    result = await client.call_json(system=ENRICH_FACETS["system"], user=user)

    assert isinstance(result, dict), f"expected dict, got {type(result)}"
    key = ENRICH_FACETS["output_key"]
    assert key in result, f"missing output_key {key!r}; got keys {list(result)}"

    usage = client.last_usage
    print("PASS: Groq returned valid JSON")
    print(json.dumps(result, indent=2))
    if usage is not None:
        print(
            f"tokens: prompt={usage.prompt_tokens} "
            f"completion={usage.completion_tokens} total={usage.total_tokens}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
