from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from fastapi import WebSocket

from echooo.config import Settings
from echooo.models import ChatMessage, SessionPhase, STTEventType
from echooo.providers.base import LanguageModelProvider, SpeechToTextProvider, TextToSpeechProvider
from echooo.providers.factory import create_llm, create_stt, create_tts
from echooo.segmenter import SentenceSegmenter


logger = logging.getLogger(__name__)


class VoiceSession:
    def __init__(
        self,
        websocket: WebSocket,
        settings: Settings,
        *,
        stt: SpeechToTextProvider | None = None,
        llm: LanguageModelProvider | None = None,
        tts: TextToSpeechProvider | None = None,
    ):
        self.websocket = websocket
        self.settings = settings
        self.stt = stt or create_stt(settings)
        self.llm = llm or create_llm(settings)
        self.tts = tts or create_tts(settings)
        self.phase = SessionPhase.IDLE
        self.history: list[ChatMessage] = []
        self.generation_id = 0
        self._response_task: asyncio.Task | None = None
        self._stt_task: asyncio.Task | None = None
        self._cancel = asyncio.Event()
        self._send_lock = asyncio.Lock()
        self._closed = False

    async def run(self) -> None:
        await self._set_phase(SessionPhase.CONNECTING)
        try:
            await self.stt.connect()
            self._stt_task = asyncio.create_task(self._consume_stt(), name="stt-events")
            await self._send_json(
                {
                    "type": "session.ready",
                    **self.settings.public_dict(),
                }
            )
            await self._set_phase(SessionPhase.LISTENING)
            await self._consume_client()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Voice session failed")
            await self._safe_error(str(exc))
        finally:
            await self.close()

    async def _consume_client(self) -> None:
        while not self._closed:
            message = await self.websocket.receive()
            if message.get("type") == "websocket.disconnect":
                return
            if message.get("bytes") is not None:
                await self.stt.send_audio(message["bytes"])
                continue
            text = message.get("text")
            if not text:
                continue
            import json

            payload = json.loads(text)
            kind = payload.get("type")
            if kind == "session.end":
                return
            if kind == "debug.user_text":
                transcript = str(payload.get("text", "")).strip()
                if transcript:
                    await self.handle_final_transcript(transcript, source="debug")

    async def _consume_stt(self) -> None:
        async for event in self.stt.events():
            if event.type == STTEventType.READY:
                await self._send_json(
                    {"type": "stt.ready", "session_id": event.session_id}
                )
            elif event.type == STTEventType.SPEECH_STARTED:
                await self.interrupt("speech_started")
            elif event.type == STTEventType.PARTIAL:
                await self._send_json(
                    {"type": "transcript.user.partial", "text": event.transcript}
                )
            elif event.type == STTEventType.FINAL and event.transcript:
                await self.handle_final_transcript(event.transcript, source="stt")
            elif event.type == STTEventType.ERROR:
                await self._safe_error(event.error or "Speech-to-text error")

    async def handle_final_transcript(self, transcript: str, *, source: str = "stt") -> None:
        await self.interrupt("new_turn", announce=False)
        self.history.append(ChatMessage(role="user", content=transcript))
        self._trim_history()
        await self._send_json(
            {
                "type": "transcript.user.final",
                "text": transcript,
                "source": source,
                "received_at": time.time(),
            }
        )
        self.generation_id += 1
        generation = self.generation_id
        self._cancel = asyncio.Event()
        self._response_task = asyncio.create_task(
            self._respond(generation, self._cancel),
            name=f"response-{generation}",
        )

    async def _respond(self, generation: int, cancel: asyncio.Event) -> None:
        started = time.perf_counter()
        first_llm_at: float | None = None
        assistant_text = ""
        segmenter = SentenceSegmenter()
        tts_queue: asyncio.Queue[str | None] = asyncio.Queue()
        tts_task = asyncio.create_task(
            self._speak_queue(generation, cancel, tts_queue),
            name=f"tts-{generation}",
        )
        await self._set_phase(SessionPhase.THINKING)
        try:
            async for delta in self.llm.stream_reply(tuple(self.history), cancel=cancel):
                if cancel.is_set() or generation != self.generation_id:
                    return
                if first_llm_at is None:
                    first_llm_at = time.perf_counter()
                    await self._send_metric("llm_first_token_ms", (first_llm_at - started) * 1000)
                assistant_text += delta
                await self._send_json(
                    {"type": "transcript.assistant.delta", "text": delta, "generation": generation}
                )
                for sentence in segmenter.feed(delta):
                    await tts_queue.put(sentence)
            remaining = segmenter.flush()
            if remaining:
                await tts_queue.put(remaining)
            await tts_queue.put(None)
            await tts_task
            if cancel.is_set() or generation != self.generation_id:
                return
            if assistant_text.strip():
                self.history.append(ChatMessage(role="assistant", content=assistant_text.strip()))
                self._trim_history()
                await self.stt.update_agent_context(assistant_text.strip())
            await self._send_json(
                {
                    "type": "transcript.assistant.final",
                    "text": assistant_text.strip(),
                    "generation": generation,
                }
            )
            await self._set_phase(SessionPhase.LISTENING)
        except asyncio.CancelledError:
            cancel.set()
            raise
        except Exception as exc:
            cancel.set()
            logger.exception("Response generation failed")
            await self._safe_error(str(exc), recover=True)
        finally:
            if not tts_task.done():
                tts_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await tts_task

    async def _speak_queue(
        self,
        generation: int,
        cancel: asyncio.Event,
        queue: asyncio.Queue[str | None],
    ) -> None:
        audio_started = False
        tts_started = time.perf_counter()
        while not cancel.is_set():
            text = await queue.get()
            if text is None:
                break
            async for chunk in self.tts.stream_audio(text, cancel=cancel):
                if cancel.is_set() or generation != self.generation_id:
                    return
                if not audio_started:
                    audio_started = True
                    await self._set_phase(SessionPhase.SPEAKING)
                    await self._send_json(
                        {
                            "type": "audio.start",
                            "sample_rate": chunk.sample_rate,
                            "encoding": chunk.encoding,
                            "channels": chunk.channels,
                            "generation": generation,
                        }
                    )
                    await self._send_metric(
                        "tts_first_audio_ms", (time.perf_counter() - tts_started) * 1000
                    )
                await self._send_bytes(chunk.data)
        if audio_started and not cancel.is_set():
            await self._send_json({"type": "audio.end", "generation": generation})

    async def interrupt(self, reason: str, *, announce: bool = True) -> None:
        if self._response_task is None or self._response_task.done():
            return
        self.generation_id += 1
        self._cancel.set()
        if announce:
            await self._set_phase(SessionPhase.INTERRUPTING)
        await self._send_json({"type": "playback.stop", "reason": reason})
        self._response_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._response_task
        self._response_task = None
        if announce:
            await self._set_phase(SessionPhase.LISTENING)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self.interrupt("session_closed", announce=False)
        if self._stt_task and not self._stt_task.done():
            self._stt_task.cancel()
        await self.stt.close()
        if self._stt_task:
            with contextlib.suppress(asyncio.CancelledError):
                await self._stt_task
        self.phase = SessionPhase.CLOSED

    def _trim_history(self) -> None:
        if len(self.history) > self.settings.history_limit:
            self.history = self.history[-self.settings.history_limit :]

    async def _set_phase(self, phase: SessionPhase) -> None:
        self.phase = phase
        await self._send_json({"type": "session.state", "state": phase.value})

    async def _send_metric(self, name: str, value: float) -> None:
        await self._send_json({"type": "metric", "name": name, "value": round(value, 1)})

    async def _safe_error(self, message: str, *, recover: bool = False) -> None:
        with contextlib.suppress(Exception):
            await self._send_json({"type": "session.error", "message": message, "recoverable": recover})
            await self._set_phase(SessionPhase.LISTENING if recover else SessionPhase.ERROR)

    async def _send_json(self, payload: dict) -> None:
        async with self._send_lock:
            await self.websocket.send_json(payload)

    async def _send_bytes(self, payload: bytes) -> None:
        async with self._send_lock:
            await self.websocket.send_bytes(payload)
