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
        reply = f"收到。你刚才说的是：{user}。当前运行在零凭据演示模式，接入真实模型后这里会返回模型回答。"
        for piece in (reply[:18], reply[18:42], reply[42:]):
            if cancel.is_set():
                return
            if piece:
                await asyncio.sleep(0)
                yield piece

