from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class SessionPhase(StrEnum):
    IDLE = "idle"
    CONNECTING = "connecting"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    INTERRUPTING = "interrupting"
    ERROR = "error"
    CLOSED = "closed"


class STTEventType(StrEnum):
    READY = "ready"
    SPEECH_STARTED = "speech_started"
    PARTIAL = "partial"
    FINAL = "final"
    TERMINATED = "terminated"
    ERROR = "error"


@dataclass(slots=True)
class STTEvent:
    type: STTEventType
    transcript: str = ""
    session_id: str = ""
    error: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ChatMessage:
    role: str
    content: str


@dataclass(slots=True)
class AudioChunk:
    data: bytes
    sample_rate: int
    encoding: str = "pcm_s16le"
    channels: int = 1

