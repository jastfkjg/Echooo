from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import httpx

from echooo.config import Settings
from echooo.models import AudioChunk
from echooo.providers.base import ProviderError, TextToSpeechProvider


class CosyVoiceTTS(TextToSpeechProvider):
    """Adapter for CosyVoice's official runtime/python/fastapi server."""

    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def sample_rate(self) -> int:
        return self.settings.cosyvoice_sample_rate

    def _request(self, text: str) -> tuple[str, dict[str, str], dict | None]:
        mode = self.settings.cosyvoice_mode
        url = f"{self.settings.cosyvoice_base_url.rstrip('/')}/inference_{mode}"
        data: dict[str, str] = {"tts_text": text}
        files = None
        if mode == "sft":
            data["spk_id"] = self.settings.cosyvoice_speaker
        elif mode == "zero_shot":
            data["prompt_text"] = self.settings.cosyvoice_prompt_text
            files = self._prompt_file()
        elif mode == "cross_lingual":
            files = self._prompt_file()
        elif mode == "instruct":
            data["spk_id"] = self.settings.cosyvoice_speaker
            data["instruct_text"] = self.settings.cosyvoice_instruct_text
        elif mode == "instruct2":
            data["instruct_text"] = self.settings.cosyvoice_instruct_text
            files = self._prompt_file()
        else:
            raise ProviderError(f"Unsupported CosyVoice mode: {mode}")
        return url, data, files

    def _prompt_file(self) -> dict:
        path = self.settings.resolve_path(self.settings.cosyvoice_prompt_wav)
        if path is None or not path.is_file():
            raise ProviderError("CosyVoice prompt WAV is missing")
        return {"prompt_wav": (path.name, path.read_bytes(), "audio/wav")}

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

