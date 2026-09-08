import json
import wave
from io import BytesIO

import httpx
import pytest

from echooo.config import Settings
from echooo.providers.tts.dashscope_voices import (
    DashScopeVoiceManager, validate_voice_sample,
)


def settings(**changes):
    return Settings(**{
        "stt_provider": "mock", "llm_provider": "mock", "tts_provider": "dashscope",
        "dashscope_api_key": "test-key", "dashscope_tts_model": "qwen-audio-3.0-tts-plus",
        "dashscope_voice_api_key": "",
        "dashscope_tts_voice": "longanlingxin",
        "dashscope_tts_url": "wss://workspace.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference",
        "dashscope_tts_timeout_seconds": 1, **changes,
    })


def wav(seconds=5, rate=16_000, width=2):
    output = BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(width)
        audio.setframerate(rate)
        audio.writeframes(b"\0" * rate * seconds * width)
    return output.getvalue()


async def test_lists_only_voices_bound_to_configured_model():
    async def handler(request):
        assert request.headers["Authorization"] == "Bearer test-key"
        assert request.url.path.endswith("/audio/tts/customization")
        payload = json.loads(await request.aread())
        assert payload == {"model": "voice-enrollment", "input": {
            "action": "list_voice", "page_index": 0, "page_size": 100}}
        return httpx.Response(200, json={"output": {"voice_list": [
            {"voice_id": "qwen-audio-3.0-tts-plus-mine-123", "status": "OK",
                "gmt_create": "2026-09-07 12:00:00"},
            {"voice_id": "other-model-voice", "status": "OK", "target_model": "other-model"},
        ]}})

    manager = DashScopeVoiceManager(settings(), transport=httpx.MockTransport(handler))
    voices = await manager.list_voices()
    assert [voice["id"] for voice in voices] == ["qwen-audio-3.0-tts-plus-mine-123"]
    assert voices[0]["name"] == "mine"
    assert voices[0]["managed"] is True
    assert manager.known_voice_ids == {"qwen-audio-3.0-tts-plus-mine-123"}


async def test_uploads_sample_then_creates_voice_with_oss_resolution_header():
    requests = []

    async def handler(request):
        body = await request.aread()
        requests.append((request, body))
        if request.method == "GET":
            assert dict(request.url.params) == {"action": "getPolicy", "model": "voice-enrollment"}
            return httpx.Response(200, json={"data": {
                "policy": "policy", "signature": "signature", "upload_dir": "temporary/path",
                "upload_host": "https://bucket.oss-cn-beijing.aliyuncs.com",
                "oss_access_key_id": "access", "x_oss_object_acl": "private",
                "x_oss_forbid_overwrite": "true",
            }})
        if request.url.host.startswith("bucket."):
            assert b'name="file"' in body and b'name="key"' in body
            assert b"temporary/path/" in body
            return httpx.Response(200)
        payload = json.loads(body)
        assert payload["model"] == "voice-enrollment"
        if payload["input"]["action"] == "query_voice":
            return httpx.Response(200, json={"output": {"status": "OK",
                "target_model": "qwen-audio-3.0-tts-plus", "gmt_create": "2026-09-07 12:00:00"}})
        assert request.headers["X-DashScope-OssResourceResolve"] == "enable"
        assert payload["input"]["action"] == "create_voice"
        assert payload["input"]["target_model"] == "qwen-audio-3.0-tts-plus"
        assert payload["input"]["url"].startswith("oss://temporary/path/")
        assert payload["input"]["language_hints"] == ["zh"]
        return httpx.Response(200, json={"output": {"voice_id": "qwen-audio-3.0-tts-plus-mine-123"}})

    manager = DashScopeVoiceManager(settings(), transport=httpx.MockTransport(handler))
    voice = await manager.create_voice(prefix="mine", language="zh", filename="sample.wav",
        data=wav(), enable_preprocess=True)
    assert voice["id"] in manager.known_voice_ids
    assert voice["name"] == "mine"
    assert voice["status"] == "OK"
    assert len(requests) == 4


@pytest.mark.parametrize("filename,data,message", [
    ("voice.txt", b"hello", "WAV, MP3, or M4A"),
    ("voice.wav", b"not-wave", "valid WAV"),
    ("voice.wav", wav(seconds=4), "between 5 and 60"),
    ("voice.wav", wav(rate=8_000), "at least 16 kHz"),
    ("voice.wav", wav(width=1), "16-bit"),
])
def test_rejects_invalid_samples_before_upload(filename, data, message):
    with pytest.raises(ValueError, match=message):
        validate_voice_sample(filename, data)


async def test_rejects_untrusted_upload_destination():
    async def handler(request):
        return httpx.Response(200, json={"data": {
            "policy": "policy", "signature": "signature", "upload_dir": "temporary/path",
            "upload_host": "https://attacker.example/upload", "oss_access_key_id": "access",
            "x_oss_object_acl": "private", "x_oss_forbid_overwrite": "true",
        }})

    manager = DashScopeVoiceManager(settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match="invalid upload destination"):
        await manager.create_voice(prefix="mine", language="zh", filename="sample.wav", data=wav())


async def test_upload_key_failure_explains_the_required_configuration():
    async def handler(request):
        return httpx.Response(401, json={"code": "InvalidApiKey", "message": "rejected"})

    manager = DashScopeVoiceManager(settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match="DASHSCOPE_VOICE_API_KEY"):
        await manager.create_voice(prefix="mine", language="zh", filename="sample.wav", data=wav())


async def test_missing_voice_enrollment_service_explains_endpoint_requirement():
    async def handler(request):
        return httpx.Response(404, json={"code": "InvalidParameter", "message": "Model not exist."})

    manager = DashScopeVoiceManager(settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match="DASHSCOPE_TTS_CUSTOMIZATION_URL"):
        await manager.list_voices()
