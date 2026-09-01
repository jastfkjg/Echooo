from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence

from echooo.models import ChatMessage
from echooo.providers.base import LanguageModelProvider


class MockLLM(LanguageModelProvider):
    async def stream_reply(
        self,
        messages: Sequence[ChatMessage],
        *,
        cancel: asyncio.Event,
    ) -> AsyncIterator[str]:
        user = next((item.content for item in reversed(messages) if item.role == "user"), "")
        reply = (
            f"Received. You said: {user}. "
            "This is the zero-credential demo; a connected model will answer here."
        )
        for piece in (reply[:18], reply[18:42], reply[42:]):
            if cancel.is_set():
                return
            if piece:
                await asyncio.sleep(0)
                yield piece
