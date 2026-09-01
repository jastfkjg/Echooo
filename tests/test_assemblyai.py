from urllib.parse import parse_qs, urlparse

from echooo.config import Settings
from echooo.models import STTEventType
from echooo.providers.stt.assemblyai import AssemblyAIStreamingSTT


def test_builds_current_v3_streaming_url() -> None:
    settings = Settings(
        assemblyai_api_key="test-key",
        assemblyai_min_turn_silence=160,
        assemblyai_max_turn_silence=2400,
    )
    provider = AssemblyAIStreamingSTT(settings)

    parsed = urlparse(provider._url("Echooo 刚刚说了你好"))
    query = parse_qs(parsed.query)

    assert parsed.scheme == "wss"
    assert query["sample_rate"] == ["16000"]
    assert query["speech_model"] == ["universal-3-5-pro"]
    assert "language_code" not in query
    assert query["agent_context"] == ["Echooo 刚刚说了你好"]


def test_maps_turn_events_to_partial_and_final() -> None:
    partial = AssemblyAIStreamingSTT.map_message(
        {"type": "Turn", "transcript": " 你好 ", "end_of_turn": False}
    )
    final = AssemblyAIStreamingSTT.map_message(
        {"type": "Turn", "transcript": "你好世界", "end_of_turn": True}
    )

    assert partial is not None and partial.type == STTEventType.PARTIAL
    assert partial.transcript == "你好"
    assert final is not None and final.type == STTEventType.FINAL
    assert final.transcript == "你好世界"


def test_maps_lifecycle_and_error_events() -> None:
    ready = AssemblyAIStreamingSTT.map_message({"type": "Begin", "id": "session-1"})
    speech = AssemblyAIStreamingSTT.map_message({"type": "SpeechStarted"})
    error = AssemblyAIStreamingSTT.map_message({"type": "Error", "error": "bad audio"})

    assert ready is not None and ready.type == STTEventType.READY
    assert ready.session_id == "session-1"
    assert speech is not None and speech.type == STTEventType.SPEECH_STARTED
    assert error is not None and error.type == STTEventType.ERROR
    assert error.error == "bad audio"
