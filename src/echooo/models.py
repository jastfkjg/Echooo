from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class STTEventType(StrEnum):
    READY = "ready"
    SPEECH_STARTED = "speech_started"
    PARTIAL = "partial"
    FINAL = "final"
    SPEAKER_REVISION = "speaker_revision"
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
class AudioChunk:
    data: bytes
    sample_rate: int
    encoding: str = "pcm_s16le"
    channels: int = 1


@dataclass(frozen=True, slots=True)
class VoiceProfile:
    """Per-session synthesis voice selected by the user."""

    mode: str = "sft"
    speaker_id: str = ""
    reference_audio: bytes | None = None
    reference_filename: str = "reference.wav"
    reference_content_type: str = "audio/wav"
    reference_text: str = ""
    instruction: str = ""
