from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from echooo.models import STTEvent, STTEventType
from echooo.providers.base import SpeechToTextProvider


class MockSTT(SpeechToTextProvider):
    def __init__(self):
        self._events: asyncio.Queue[STTEvent | None] = asyncio.Queue()

    async def connect(self, *, agent_context: str = "") -> None:
        await self._events.put(STTEvent(type=STTEventType.READY, session_id="mock-stt"))

    async def send_audio(self, pcm16: bytes) -> None:
        return None

    async def events(self) -> AsyncIterator[STTEvent]:
        while True:
            event = await self._events.get()
            if event is None:
                return
            yield event

    async def update_agent_context(self, text: str) -> None:
        return None

    async def close(self) -> None:
        await self._events.put(None)

