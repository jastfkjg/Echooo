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
    assert query['continuous_partials'] == ['true']
    assert query['include_partial_turns'] == ['true']
    assert query['interruption_delay'] == ['0']


def test_diarization_keeps_partials_and_passes_language_hints_and_keyterms():
    import json
    provider = AssemblyAIStreamingSTT(Settings(assemblyai_language_codes=('zh', 'en'),
        assemblyai_keyterms=('Echooo', '艾可'), assemblyai_prompt='A product meeting.'))
    provider.speaker_labels = True
    query = parse_qs(urlparse(provider._url()).query)
    assert query['speaker_labels'] == ['true']
    assert query['continuous_partials'] == ['true']
    assert json.loads(query['language_codes'][0]) == ['zh', 'en']
    assert json.loads(query['keyterms_prompt'][0]) == ['Echooo', '艾可']
    assert query['prompt'] == ['A product meeting.']


def test_speaker_revision_is_not_discarded():
    raw = {'type': 'SpeakerRevision', 'revisions': [{'turn_order': 3, 'speaker_label': 'B'}]}
    event = AssemblyAIStreamingSTT.map_message(raw)
    assert event.type == STTEventType.SPEAKER_REVISION
    assert event.raw == raw


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
