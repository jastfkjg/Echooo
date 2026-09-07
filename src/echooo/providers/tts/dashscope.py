from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from collections.abc import AsyncIterator

from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from echooo.config import Settings
from echooo.models import AudioChunk, VoiceProfile
from echooo.providers.base import ProviderError, TextToSpeechProvider


class DashScopeTTS(TextToSpeechProvider):
    """CosyVoice's DashScope duplex protocol, yielding raw mono PCM16.

    A connection belongs to one checked reply. Closing it on cancellation also
    works in regions that don't support the finish-task cancel directive.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.voice = settings.dashscope_tts_voice

    @property
    def sample_rate(self) -> int:
        return self.settings.dashscope_tts_sample_rate

    def configure_voice(self, profile: VoiceProfile) -> None:
        # "sft" is the application's preset voice mode, not a DashScope API mode.
        if profile.mode != "sft" or profile.reference_audio is not None:
            raise ProviderError("DashScope TTS requires a registered voice ID")
        self.voice = profile.speaker_id or self.settings.dashscope_tts_voice
        if not self.voice.strip():
            raise ProviderError("DashScope TTS voice is required")

    @staticmethod
    def _command(task_id: str, action: str, payload: dict) -> str:
        return json.dumps({
            "header": {"action": action, "task_id": task_id, "streaming": "duplex"},
            "payload": payload,
        }, ensure_ascii=False)

    @staticmethod
    def _event(raw: str, task_id: str) -> str:
        try:
            message = json.loads(raw)
            header = message["header"]
            if header["task_id"] != task_id:
                raise ProviderError("DashScope returned an unrelated task")
            event = header["event"]
            if event == "task-failed":
                # Vendor messages may echo submitted text. Don't expose them.
                raise ProviderError("DashScope synthesis failed; check model, voice, region and quota")
            if event not in {"task-started", "result-generated", "task-finished"}:
                raise ProviderError("Unexpected DashScope event")
            return event
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderError("Invalid DashScope response") from exc

    async def _synthesize(self, text: str, queue: asyncio.Queue) -> None:
        """Produce audio with bounded buffering; cancellation covers every await."""
        task_id = uuid.uuid4().hex
        timeout = self.settings.dashscope_tts_timeout_seconds
        async with connect(
            self.settings.dashscope_tts_url,
            additional_headers={"Authorization": f"Bearer {self.settings.dashscope_api_key}"},
            open_timeout=min(timeout, 15), close_timeout=1,
            max_size=2**22, max_queue=4, compression=None,
        ) as ws:
            async with asyncio.timeout(timeout):
                await ws.send(self._command(task_id, "run-task", {
                    "task_group": "audio", "task": "tts", "function": "SpeechSynthesizer",
                    "model": self.settings.dashscope_tts_model,
                    "parameters": {"text_type": "PlainText", "voice": self.voice,
                        "format": "pcm", "sample_rate": self.sample_rate},
                    "input": {},
                }))
                first = await ws.recv()
                if not isinstance(first, str) or self._event(first, task_id) != "task-started":
                    raise ProviderError("DashScope did not start the synthesis task")
                # The API limits each continue-task to 20,000 characters.
                for offset in range(0, len(text), 20_000):
                    await ws.send(self._command(task_id, "continue-task", {
                        "input": {"text": text[offset:offset + 20_000]},
                    }))
                await ws.send(self._command(task_id, "finish-task", {"input": {}}))
            byte_count = 0
            while True:
                # This is an idle timeout, not a limit on spoken reply duration.
                raw = await asyncio.wait_for(ws.recv(), timeout)
                if isinstance(raw, bytes):
                    if raw:
                        byte_count += len(raw)
                        await queue.put(AudioChunk(raw, self.sample_rate))
                    continue
                event = self._event(raw, task_id)
                if event == "task-finished":
                    if not byte_count or byte_count % 2:
                        raise ProviderError("DashScope returned empty or incomplete PCM audio")
                    return
                if event != "result-generated":
                    raise ProviderError("Unexpected DashScope synthesis state")

    async def stream_audio(self, text: str, *, cancel: asyncio.Event) -> AsyncIterator[AudioChunk]:
        if not text.strip() or cancel.is_set():
            return
        if not self.settings.dashscope_api_key.strip():
            raise ProviderError("DASHSCOPE_API_KEY is required")
        if len(text) > 200_000:
            raise ProviderError("DashScope synthesis text exceeds 200,000 characters")
        queue: asyncio.Queue[AudioChunk] = asyncio.Queue(maxsize=4)
        producer = asyncio.create_task(self._synthesize(text, queue))
        cancelled = asyncio.create_task(cancel.wait())
        pending = None
        try:
            while True:
                if cancel.is_set():
                    return
                if producer.done():
                    producer.result()
                    while not queue.empty():
                        if cancel.is_set():
                            return
                        yield queue.get_nowait()
                    return
                pending = asyncio.create_task(queue.get())
                done, _ = await asyncio.wait(
                    {pending, producer, cancelled}, return_when=asyncio.FIRST_COMPLETED)
                if cancelled in done:
                    return
                if producer in done:
                    producer.result()  # Propagate failures before publishing queued audio.
                if pending in done:
                    chunk = pending.result()
                    pending = None
                    yield chunk
                elif producer in done:
                    return
        except TimeoutError as exc:
            raise ProviderError("DashScope synthesis timed out") from exc
        except (WebSocketException, OSError) as exc:
            raise ProviderError("DashScope connection failed; check endpoint, credentials and network") from exc
        finally:
            tasks = [task for task in (pending, producer, cancelled) if task is not None]
            for task in tasks:
                task.cancel()
            # Await connection closure on interrupt, mute, generator close or error.
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.gather(*tasks, return_exceptions=True)
