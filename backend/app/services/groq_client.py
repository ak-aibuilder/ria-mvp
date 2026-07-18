"""GroqEnrichmentClient — async wrapper around Groq's OpenAI-compatible API.

Adapted from v1's ClaudeEnrichmentClient (goals.md §6: convert to the
OpenAI-compatible SDK targeting Groq). Enrichment model config per goals.md §5:
temperature 0.3, max_tokens 2048, response_format json_object. The reasoning
hint ("Reasoning: low") is the first line of each enrichment system prompt.

response_format=json_object makes the model emit valid JSON, so _extract_json
is a defensive safety net rather than the primary path; the retry-once-on-bad-
JSON behavior from v1 is preserved for robustness.
"""
from __future__ import annotations

import json
import re
from typing import Any

from openai import AsyncOpenAI, APIError

from app.core.config import get_settings


class EnrichmentError(Exception):
    pass


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_json(text: str) -> dict[str, Any]:
    """Best-effort JSON extraction. Tolerates code fences and leading prose."""
    candidates: list[str] = []
    for match in _JSON_FENCE_RE.findall(text):
        candidates.append(match)
    candidates.append(text.strip())
    # Last resort: find first { ... matching final } by brace depth.
    if "{" in text and "}" in text:
        start = text.find("{")
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start : i + 1])
                    break

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue
    raise EnrichmentError("Groq response is not valid JSON")


class GroqEnrichmentClient:
    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self._api_key = api_key or settings.GROQ_API_KEY
        if not self._api_key:
            raise EnrichmentError("GROQ_API_KEY is not set; enrichment cannot run")
        # PROBLEM (Step 2 verify): Groq's free tier caps at 8000 tokens/min.
        # Concurrent enrichment bursts hit HTTP 429 (rate_limit_exceeded).
        # FIX: let the SDK auto-retry on 429/5xx — it honors the server's
        # retry-after hint with exponential backoff. Paired with the reduced
        # PRODUCT_CONCURRENCY in enrich.py, this makes enrichment self-heal
        # instead of dropping dimensions. See docs/capability-bets.md.
        self._client = AsyncOpenAI(
            api_key=self._api_key,
            base_url=settings.GROQ_BASE_URL,
            max_retries=6,
        )
        self._model = model or settings.GROQ_MODEL
        # last_usage holds the OpenAI usage object from the most recent call so
        # the Step 3 TokenTracker can read prompt/completion tokens per request.
        self.last_usage: Any | None = None

    async def call_json(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 2048,
        temperature: float = 0.3,
    ) -> dict[str, Any]:
        """Issue a chat completion and return the parsed JSON dict.

        Retries once with a JSON reminder if the first response fails to parse.
        """
        first_text = await self._raw_call(
            system=system, user=user, max_tokens=max_tokens, temperature=temperature
        )
        try:
            return _extract_json(first_text)
        except EnrichmentError:
            pass

        reminder = (
            user
            + "\n\nIMPORTANT: respond with valid JSON only. No prose, no code fences."
        )
        second_text = await self._raw_call(
            system=system, user=reminder, max_tokens=max_tokens, temperature=temperature
        )
        return _extract_json(second_text)

    async def chat(
        self,
        *,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str = "auto",
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> Any:
        """Raw tool-enabled chat completion for the validation agent (Step 4).

        Returns the OpenAI message object (has .content and .tool_calls). Sets
        last_usage like the enrichment path so the TokenTracker instruments
        validation the same way (record_last after each turn).
        """
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice
        try:
            resp = await self._client.chat.completions.create(**kwargs)
        except APIError as exc:
            raise EnrichmentError(f"Groq API error: {exc}") from exc
        self.last_usage = getattr(resp, "usage", None)
        return resp.choices[0].message

    @property
    def model_name(self) -> str:
        return self._model

    async def _raw_call(
        self, *, system: str, user: str, max_tokens: int, temperature: float
    ) -> str:
        try:
            resp = await self._client.chat.completions.create(
                model=self._model,
                max_tokens=max_tokens,
                temperature=temperature,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
        except APIError as exc:
            raise EnrichmentError(f"Groq API error: {exc}") from exc

        self.last_usage = getattr(resp, "usage", None)
        return (resp.choices[0].message.content or "").strip()
