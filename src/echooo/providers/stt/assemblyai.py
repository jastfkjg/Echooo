from __future__ import annotations

import json
from collections.abc import AsyncIterator
from urllib.parse import urlencode

import websockets
from websockets.exceptions import ConnectionClosed

from echooo.config import Settings
from echooo.models import STTEvent, STTEventType
from echooo.providers.base import ProviderError, SpeechToTextProvider


class AssemblyAIStreamingSTT(SpeechToTextProvider):
    """Raw v3 WebSocket adapter for Universal-3.5 Pro Realtime."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._ws = None
        self._closed = False
        self.speaker_labels = False

    def _url(self, agent_context: str = "") -> str:
        params: dict[str, object] = {
            "sample_rate": self.settings.assemblyai_sample_rate,
            "speech_model": self.settings.assemblyai_speech_model,
            "mode": self.settings.assemblyai_mode,
        }
        if self.speaker_labels:
            params["speaker_labels"] = "true"
        params["include_partial_turns"] = "true"
        if self.settings.assemblyai_speech_model == "universal-3-5-pro":
            params["continuous_partials"] = "true"
            params["interruption_delay"] = self.settings.assemblyai_interruption_delay
            if self.settings.assemblyai_language_codes:
                params["language_codes"] = json.dumps(self.settings.assemblyai_language_codes)
            if self.settings.assemblyai_prompt:
                params["prompt"] = self.settings.assemblyai_prompt
        if self.settings.assemblyai_keyterms:
            params["keyterms_prompt"] = json.dumps(self.settings.assemblyai_keyterms, ensure_ascii=False)
        if self.settings.assemblyai_min_turn_silence is not None:
            params["min_turn_silence"] = self.settings.assemblyai_min_turn_silence
        if self.settings.assemblyai_max_turn_silence is not None:
            params["max_turn_silence"] = self.settings.assemblyai_max_turn_silence
        if agent_context:
            params["agent_context"] = agent_context
        return f"{self.settings.assemblyai_streaming_url}?{urlencode(params)}"

    async def connect(self, *, agent_context: str = "") -> None:
        if not self.settings.assemblyai_api_key:
            raise ProviderError("Missing ASSEMBLYAI_API_KEY")
        self._closed = False
        self._ws = await websockets.connect(
            self._url(agent_context),
            additional_headers={"Authorization": self.settings.assemblyai_api_key},
            max_size=2**22,
            ping_interval=20,
            ping_timeout=20,
        )

    async def send_audio(self, pcm16: bytes) -> None:
        if self._ws is None or self._closed:
            return
        await self._ws.send(pcm16)

    async def events(self) -> AsyncIterator[STTEvent]:
        if self._ws is None:
            raise ProviderError("AssemblyAI STT is not connected")
        try:
            async for raw in self._ws:
                if isinstance(raw, bytes):
                    continue
                message = json.loads(raw)
                event = self.map_message(message)
                if event is not None:
                    yield event
                    if event.type == STTEventType.TERMINATED:
                        return
        except ConnectionClosed as exc:
            if not self._closed:
                yield STTEvent(type=STTEventType.ERROR, error=f"AssemblyAI connection closed: {exc}")
        except (json.JSONDecodeError, OSError) as exc:
            yield STTEvent(type=STTEventType.ERROR, error=f"AssemblyAI stream error: {exc}")

    @staticmethod
    def map_message(message: dict) -> STTEvent | None:
        kind = message.get("type")
        if kind == "Begin":
            return STTEvent(
                type=STTEventType.READY,
                session_id=str(message.get("id", "")),
                raw=message,
            )
        if kind == "SpeechStarted":
            return STTEvent(type=STTEventType.SPEECH_STARTED, raw=message)
        if kind == "Turn":
            transcript = str(message.get("transcript", "")).strip()
            return STTEvent(
                type=STTEventType.FINAL if message.get("end_of_turn") else STTEventType.PARTIAL,
                transcript=transcript,
                raw=message,
            )
        if kind == "Termination":
            return STTEvent(type=STTEventType.TERMINATED, raw=message)
        if kind == "SpeakerRevision":
            return STTEvent(type=STTEventType.SPEAKER_REVISION, raw=message)
        if kind in {"Error", "SessionError"}:
            return STTEvent(
                type=STTEventType.ERROR,
                error=str(message.get("error") or message.get("message") or message),
                raw=message,
            )
        return None

    async def update_agent_context(self, text: str) -> None:
        if self._ws is None or self._closed or not text:
            return
        await self._ws.send(json.dumps({"type": "UpdateConfiguration", "agent_context": text}))

    async def finish(self) -> None:
        """Flush the last turn; keep receiving until the server acknowledges termination."""
        if self._ws is not None and not self._closed:
            await self._ws.send(json.dumps({"type": "Terminate"}))

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._ws is None:
            return
        try:
            await self._ws.send(json.dumps({"type": "Terminate"}))
        except ConnectionClosed:
            pass
        finally:
            await self._ws.close()
            self._ws = None
