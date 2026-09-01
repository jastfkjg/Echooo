from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence

from echooo.models import AudioChunk, ChatMessage, STTEvent, VoiceProfile


class SpeechToTextProvider(ABC):
    """One live transcription session."""

    @abstractmethod
    async def connect(self, *, agent_context: str = "") -> None: ...

    @abstractmethod
    async def send_audio(self, pcm16: bytes) -> None: ...

    @abstractmethod
    def events(self) -> AsyncIterator[STTEvent]: ...

    @abstractmethod
    async def update_agent_context(self, text: str) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...


class LanguageModelProvider(ABC):
    """Streams text deltas for one assistant reply."""

    @abstractmethod
    def stream_reply(
        self,
        messages: Sequence[ChatMessage],
        *,
        cancel: asyncio.Event,
    ) -> AsyncIterator[str]: ...


class TextToSpeechProvider(ABC):
    """Streams mono PCM16 audio for one text chunk."""

    @property
    @abstractmethod
    def sample_rate(self) -> int: ...

    @abstractmethod
    def configure_voice(self, profile: VoiceProfile) -> None: ...

    @abstractmethod
    def stream_audio(
        self,
        text: str,
        *,
        cancel: asyncio.Event,
    ) -> AsyncIterator[AudioChunk]: ...


class ProviderError(RuntimeError):
    pass
