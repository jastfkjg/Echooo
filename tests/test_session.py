import asyncio
from typing import Any

from echooo.config import Settings
from echooo.models import ChatMessage
from echooo.orchestrator import VoiceSession
from echooo.providers.llm.mock import MockLLM
from echooo.providers.stt.mock import MockSTT
from echooo.providers.tts.mock import MockToneTTS


class RecordingWebSocket:
    def __init__(self) -> None:
        self.json_messages: list[dict[str, Any]] = []
        self.audio_chunks: list[bytes] = []

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.json_messages.append(payload)

    async def send_bytes(self, payload: bytes) -> None:
        self.audio_chunks.append(payload)


async def test_mock_session_runs_user_llm_tts_pipeline() -> None:
    websocket = RecordingWebSocket()
    session = VoiceSession(  # type: ignore[arg-type]
        websocket,
        Settings(),
        stt=MockSTT(),
        llm=MockLLM(),
        tts=MockToneTTS(),
    )

    await session.handle_final_transcript("请介绍当前管线", source="debug")
    assert session._response_task is not None
    await asyncio.wait_for(session._response_task, timeout=2)

    message_types = [message["type"] for message in websocket.json_messages]
    assert "transcript.user.final" in message_types
    assert "transcript.assistant.delta" in message_types
    assert "audio.start" in message_types
    assert "audio.end" in message_types
    assert "transcript.assistant.final" in message_types
    assert websocket.audio_chunks
    assert sum(map(len, websocket.audio_chunks)) > 1_000
    assert session.history[0] == ChatMessage(role="user", content="请介绍当前管线")
    assert session.history[-1].role == "assistant"


async def test_new_turn_cancels_in_flight_response() -> None:
    websocket = RecordingWebSocket()
    session = VoiceSession(  # type: ignore[arg-type]
        websocket,
        Settings(),
        stt=MockSTT(),
        llm=MockLLM(),
        tts=MockToneTTS(),
    )

    await session.handle_final_transcript("第一句", source="debug")
    await session.handle_final_transcript("第二句", source="debug")
    assert session._response_task is not None
    await asyncio.wait_for(session._response_task, timeout=2)

    assert any(message["type"] == "playback.stop" for message in websocket.json_messages)
    assert [message.content for message in session.history if message.role == "user"] == [
        "第一句",
        "第二句",
    ]
