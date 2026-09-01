from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import httpx

from echooo.config import Settings
from echooo.models import AudioChunk, VoiceProfile
from echooo.providers.base import ProviderError, TextToSpeechProvider


class CosyVoiceTTS(TextToSpeechProvider):
    """Adapter for CosyVoice's official runtime/python/fastapi server."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.voice = VoiceProfile()

    @property
    def sample_rate(self) -> int:
        return self.settings.cosyvoice_sample_rate

    def configure_voice(self, profile: VoiceProfile) -> None:
        if profile.mode == "sft" and not profile.speaker_id:
            raise ProviderError("A preset speaker ID is required for SFT mode")
        if profile.mode == "zero_shot":
            if not profile.reference_audio:
                raise ProviderError("A reference audio sample is required for zero-shot mode")
            if not profile.reference_text:
                raise ProviderError("A reference transcript is required for zero-shot mode")
        if profile.mode == "cross_lingual" and not profile.reference_audio:
            raise ProviderError("A reference audio sample is required for cross-lingual mode")
        if profile.mode == "instruct":
            if not profile.speaker_id or not profile.instruction:
                raise ProviderError("A speaker ID and instruction are required for instruct mode")
        if profile.mode == "instruct2":
            if not profile.reference_audio or not profile.instruction:
                raise ProviderError("A reference sample and instruction are required for instruct2 mode")
        if profile.mode not in {"sft", "zero_shot", "cross_lingual", "instruct", "instruct2"}:
            raise ProviderError(f"Unsupported CosyVoice mode: {profile.mode}")
        self.voice = profile

    def _request(self, text: str) -> tuple[str, dict[str, str], dict | None]:
        mode = self.voice.mode
        url = f"{self.settings.cosyvoice_base_url.rstrip('/')}/inference_{mode}"
        data: dict[str, str] = {"tts_text": text}
        files = None
        if mode == "sft":
            data["spk_id"] = self.voice.speaker_id
        elif mode == "zero_shot":
            data["prompt_text"] = self.voice.reference_text
            files = self._prompt_file()
        elif mode == "cross_lingual":
            files = self._prompt_file()
        elif mode == "instruct":
            data["spk_id"] = self.voice.speaker_id
            data["instruct_text"] = self.voice.instruction
        elif mode == "instruct2":
            data["instruct_text"] = self.voice.instruction
            files = self._prompt_file()
        else:
            raise ProviderError(f"Unsupported CosyVoice mode: {mode}")
        return url, data, files

    def _prompt_file(self) -> dict:
        if not self.voice.reference_audio:
            raise ProviderError("CosyVoice prompt WAV is missing")
        return {
            "prompt_wav": (
                self.voice.reference_filename,
                self.voice.reference_audio,
                self.voice.reference_content_type,
            )
        }

    async def stream_audio(
        self,
        text: str,
        *,
        cancel: asyncio.Event,
    ) -> AsyncIterator[AudioChunk]:
        if not text.strip():
            return
        url, data, files = self._request(text)
        timeout = httpx.Timeout(self.settings.cosyvoice_timeout_seconds, connect=15)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, data=data, files=files) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes(16_000):
                        if cancel.is_set():
                            return
                        if chunk:
                            yield AudioChunk(data=chunk, sample_rate=self.sample_rate)
        except httpx.HTTPStatusError as exc:
            body = (await exc.response.aread()).decode(errors="replace")[:500]
            raise ProviderError(
                f"CosyVoice request failed ({exc.response.status_code}): {body}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"CosyVoice connection failed: {exc}") from exc
