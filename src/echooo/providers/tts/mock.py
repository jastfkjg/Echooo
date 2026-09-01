from __future__ import annotations

import asyncio
import math
from array import array
from collections.abc import AsyncIterator

from echooo.models import AudioChunk
from echooo.providers.base import TextToSpeechProvider


class MockToneTTS(TextToSpeechProvider):
    """Produces a quiet tone so the complete audio path can be tested without a TTS key."""

    _sample_rate = 24000

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    async def stream_audio(
        self,
        text: str,
        *,
        cancel: asyncio.Event,
    ) -> AsyncIterator[AudioChunk]:
        duration = min(0.35, max(0.12, len(text) * 0.008))
        count = int(self.sample_rate * duration)
        samples = array(
            "h",
            (
                int(1200 * math.sin(2 * math.pi * 440 * index / self.sample_rate))
                for index in range(count)
            ),
        )
        block = self.sample_rate // 10
        for offset in range(0, len(samples), block):
            if cancel.is_set():
                return
            await asyncio.sleep(0)
            yield AudioChunk(data=samples[offset : offset + block].tobytes(), sample_rate=self.sample_rate)

