from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence

import httpx

from echooo.config import Settings
from echooo.models import ChatMessage
from echooo.providers.base import LanguageModelProvider, ProviderError


class OpenAICompatibleLLM(LanguageModelProvider):
    """Minimal SSE adapter for OpenAI-compatible chat completion servers."""

    def __init__(self, settings: Settings):
        self.settings = settings

    async def stream_reply(
        self,
        messages: Sequence[ChatMessage],
        *,
        cancel: asyncio.Event,
    ) -> AsyncIterator[str]:
        headers = {"Content-Type": "application/json"}
        if self.settings.llm_api_key:
            headers["Authorization"] = f"Bearer {self.settings.llm_api_key}"
        payload = {
            "model": self.settings.llm_model,
            "messages": [
                {"role": "system", "content": self.settings.llm_system_prompt},
                *[{"role": item.role, "content": item.content} for item in messages],
            ],
            "temperature": self.settings.llm_temperature,
            "stream": True,
        }
        url = self.settings.llm_base_url.rstrip("/") + "/chat/completions"
        timeout = httpx.Timeout(self.settings.llm_timeout_seconds, connect=15)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if cancel.is_set():
                            return
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if not data or data == "[DONE]":
                            if data == "[DONE]":
                                return
                            continue
                        try:
                            message = json.loads(data)
                            delta = message["choices"][0].get("delta", {}).get("content")
                        except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                            continue
                        if delta:
                            yield str(delta)
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:500]
            raise ProviderError(f"LLM request failed ({exc.response.status_code}): {body}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"LLM connection failed: {exc}") from exc

