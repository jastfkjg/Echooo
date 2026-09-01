from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile


MAX_VOICE_SAMPLE_BYTES = 10 * 1024 * 1024
MAX_STORED_SAMPLES = 32
ALLOWED_SUFFIXES = {".wav", ".mp3", ".flac", ".m4a", ".ogg"}


class VoiceSampleError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class VoiceSample:
    id: str
    filename: str
    content_type: str
    data: bytes


class VoiceSampleStore:
    """Small process-local store; uploaded voice biometrics are never written to disk."""

    def __init__(self) -> None:
        self._samples: OrderedDict[str, VoiceSample] = OrderedDict()
        self._lock = asyncio.Lock()

    async def save_upload(self, upload: UploadFile) -> VoiceSample:
        filename = Path(upload.filename or "reference.wav").name
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise VoiceSampleError("Upload WAV, MP3, FLAC, M4A, or OGG audio")
        data = await upload.read(MAX_VOICE_SAMPLE_BYTES + 1)
        if not data:
            raise VoiceSampleError("The uploaded audio file is empty")
        if len(data) > MAX_VOICE_SAMPLE_BYTES:
            raise VoiceSampleError("Voice samples must be 10 MB or smaller")
        sample = VoiceSample(
            id=uuid4().hex,
            filename=filename,
            content_type=upload.content_type or "application/octet-stream",
            data=data,
        )
        async with self._lock:
            self._samples[sample.id] = sample
            while len(self._samples) > MAX_STORED_SAMPLES:
                self._samples.popitem(last=False)
        return sample

    async def get(self, sample_id: str) -> VoiceSample:
        async with self._lock:
            sample = self._samples.get(sample_id)
            if sample is None:
                raise VoiceSampleError("The voice sample has expired; upload it again")
            self._samples.move_to_end(sample_id)
            return sample

    async def delete(self, sample_id: str) -> None:
        async with self._lock:
            self._samples.pop(sample_id, None)
