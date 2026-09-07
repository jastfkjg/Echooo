"""Exercise the cloud protocol over real local WebSockets; no paid API calls."""
import asyncio
import json
from contextlib import asynccontextmanager

import pytest
from websockets.asyncio.server import serve

from echooo.config import Settings
from echooo.models import VoiceProfile
from echooo.providers.base import ProviderError
from echooo.providers.factory import create_tts
from echooo.providers.tts.dashscope import DashScopeTTS


def settings(**changes):
    return Settings(**{
        "stt_provider": "mock", "llm_provider": "mock", "tts_provider": "dashscope",
        "dashscope_api_key": "test-key", "dashscope_tts_model": "cosyvoice-v3-flash",
        "dashscope_tts_voice": "longanyang", "dashscope_tts_sample_rate": 24000,
        "dashscope_tts_url": "wss://dashscope.aliyuncs.com/api-ws/v1/inference",
        "dashscope_tts_timeout_seconds": 1, **changes,
    })


@asynccontextmanager
async def local_provider(handler, **changes):
    errors = []

    async def checked_handler(ws):
        try:
            await handler(ws)
        except Exception as exc:
            errors.append(exc)

    async with asyncio.timeout(5):
        async with serve(checked_handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            # Only tests use ws://; Settings.validate requires wss:// in the app.
            yield DashScopeTTS(settings(dashscope_tts_url=f"ws://127.0.0.1:{port}", **changes))
    if errors:
        raise errors[0]


async def event(ws, task_id, name, **header):
    await ws.send(json.dumps({"header": {"task_id": task_id, "event": name, **header}, "payload": {}}))


async def start(ws):
    run = json.loads(await ws.recv())
    task_id = run["header"]["task_id"]
    await event(ws, task_id, "task-started")
    continued = json.loads(await ws.recv())
    finished = json.loads(await ws.recv())
    assert continued["header"] == {"action": "continue-task", "task_id": task_id, "streaming": "duplex"}
    assert finished == {"header": {"action": "finish-task", "task_id": task_id, "streaming": "duplex"}, "payload": {"input": {}}}
    return task_id, run, continued


async def collect(provider, cancel=None):
    return [chunk async for chunk in provider.stream_audio("你好，Echooo。", cancel=cancel or asyncio.Event())]


def test_factory_configuration_and_public_secrets():
    config = settings(dashscope_tts_custom_voices=("my_voice_01",),
        dashscope_voice_api_key="voice-secret")
    config.validate()
    assert isinstance(create_tts(config), DashScopeTTS)
    public = config.public_dict()
    assert public["providers"]["tts"] == "dashscope"
    assert public["tts"]["default_voice"] == "longanyang"
    assert public["tts"]["custom_voice_management"] is True
    assert {voice["id"] for voice in public["tts"]["voices"]} >= {
        "longanyang", "longanhuan", "longanwen_v3", "my_voice_01"}
    assert next(voice for voice in public["tts"]["voices"]
        if voice["id"] == "my_voice_01")["custom"] is True
    assert "test-key" not in json.dumps(public)
    assert "voice-secret" not in json.dumps(public)
    assert "dashscope_api_key" not in public
    workspace = settings(dashscope_tts_url="wss://space.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference")
    assert workspace.dashscope_customization_url() == \
        "https://space.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/tts/customization"


@pytest.mark.parametrize("changes, field", [
    ({"dashscope_api_key": " "}, "DASHSCOPE_API_KEY"),
    ({"dashscope_tts_model": ""}, "DASHSCOPE_TTS_MODEL"),
    ({"dashscope_tts_voice": ""}, "DASHSCOPE_TTS_VOICE"),
    ({"dashscope_tts_url": "ws://example.com"}, "DASHSCOPE_TTS_URL"),
    ({"dashscope_tts_url": "wss://user:secret@example.com"}, "DASHSCOPE_TTS_URL"),
    ({"dashscope_tts_sample_rate": 12345}, "DASHSCOPE_TTS_SAMPLE_RATE"),
    ({"dashscope_tts_timeout_seconds": 0}, "DASHSCOPE_TTS_TIMEOUT_SECONDS"),
    ({"dashscope_tts_timeout_seconds": float("nan")}, "DASHSCOPE_TTS_TIMEOUT_SECONDS"),
    ({"dashscope_tts_custom_voices": ("bad voice",)}, "voice IDs"),
    ({"dashscope_tts_customization_url": "http://example.com/custom"}, "DASHSCOPE_TTS_CUSTOMIZATION_URL"),
    ({"dashscope_upload_url": "https://user:secret@example.com/uploads"}, "DASHSCOPE_UPLOAD_URL"),
])
def test_invalid_cloud_configuration_fails_at_startup(changes, field):
    with pytest.raises(ValueError, match=field):
        settings(**changes).validate()


async def test_streams_before_task_finishes_and_drains_buffered_audio():
    first_played = asyncio.Event()
    closed = asyncio.Event()

    async def handler(ws):
        assert ws.request.headers["Authorization"] == "Bearer test-key"
        task_id, run, continued = await start(ws)
        assert run["header"]["action"] == "run-task"
        assert run["payload"] == {
            "task_group": "audio", "task": "tts", "function": "SpeechSynthesizer",
            "model": "cosyvoice-v3-flash", "parameters": {
                "text_type": "PlainText", "voice": "longanhuan", "format": "pcm", "sample_rate": 24000},
            "input": {},
        }
        assert continued["payload"] == {"input": {"text": "你好，Echooo。"}}
        await event(ws, task_id, "result-generated")
        await ws.send(b"\x01\x00\x02")
        await first_played.wait()  # Fails if the adapter buffers until task-finished.
        await ws.send(b"\x00")
        for _ in range(10):
            await ws.send(b"\x03\x00")
        await event(ws, task_id, "task-finished")
        await ws.wait_closed()
        closed.set()

    async with local_provider(handler) as provider:
        provider.configure_voice(VoiceProfile(speaker_id="longanhuan"))
        chunks = []
        async for chunk in provider.stream_audio("你好，Echooo。", cancel=asyncio.Event()):
            chunks.append(chunk)
            first_played.set()
        assert b"".join(c.data for c in chunks) == b"\x01\x00\x02\x00" + b"\x03\x00" * 10
        assert all(c.sample_rate == 24000 and c.encoding == "pcm_s16le" and c.channels == 1 for c in chunks)
        await closed.wait()


@pytest.mark.parametrize("failure", ["rejected", "disconnect", "wrong_task", "malformed", "empty", "odd"])
async def test_failure_never_looks_like_success(failure):
    async def handler(ws):
        task_id, _, _ = await start(ws)
        if failure == "rejected":
            await event(ws, task_id, "task-failed", error_code="InvalidParameter", error_message="SECRET-TEXT")
        elif failure == "disconnect":
            await ws.send(b"\0\0")
            await ws.close()
        elif failure == "wrong_task":
            await event(ws, "unrelated", "task-finished")
        elif failure == "malformed":
            await ws.send("[]")
        else:
            if failure == "odd":
                await ws.send(b"\0")
            await event(ws, task_id, "task-finished")

    async with local_provider(handler) as provider:
        with pytest.raises(ProviderError) as caught:
            await collect(provider)
        assert "SECRET-TEXT" not in str(caught.value)


async def test_rejected_model_before_started():
    async def handler(ws):
        run = json.loads(await ws.recv())
        await event(ws, run["header"]["task_id"], "task-failed", error_message="SECRET")
        await ws.wait_closed()

    async with local_provider(handler) as provider:
        with pytest.raises(ProviderError, match="synthesis failed"):
            await collect(provider)


async def test_authentication_failure_is_sanitized():
    def deny(connection, request):
        return connection.respond(401, "SECRET-TOKEN")

    async with serve(lambda ws: ws.wait_closed(), "127.0.0.1", 0, process_request=deny) as server:
        port = server.sockets[0].getsockname()[1]
        provider = DashScopeTTS(settings(dashscope_tts_url=f"ws://127.0.0.1:{port}"))
        with pytest.raises(ProviderError, match="connection failed") as caught:
            await collect(provider)
        assert "SECRET-TOKEN" not in str(caught.value)


@pytest.mark.parametrize("stage", ["starting", "audio"])
async def test_idle_timeout_closes_connection(stage):
    closed = asyncio.Event()

    async def handler(ws):
        if stage == "audio":
            await start(ws)
        else:
            await ws.recv()
        await ws.wait_closed()
        closed.set()

    async with local_provider(handler, dashscope_tts_timeout_seconds=0.1) as provider:
        with pytest.raises(ProviderError, match="timed out"):
            await collect(provider)
        await closed.wait()


@pytest.mark.parametrize("stage", ["starting", "audio"])
@pytest.mark.parametrize("method", ["event", "task"])
async def test_cancellation_closes_stalled_connection(stage, method):
    ready, closed, cancel = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def handler(ws):
        if stage == "audio":
            await start(ws)
        else:
            await ws.recv()
        ready.set()
        await ws.wait_closed()
        closed.set()

    async with local_provider(handler, dashscope_tts_timeout_seconds=60) as provider:
        task = asyncio.create_task(collect(provider, cancel))
        await ready.wait()
        if method == "event":
            cancel.set()
            assert await asyncio.wait_for(task, 2) == []
        else:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        await asyncio.wait_for(closed.wait(), 2)


async def test_closing_generator_cancels_producer():
    closed = asyncio.Event()

    async def handler(ws):
        await start(ws)
        await ws.send(b"\0\0")
        await ws.wait_closed()
        closed.set()

    async with local_provider(handler) as provider:
        stream = provider.stream_audio("hello", cancel=asyncio.Event())
        assert (await anext(stream)).data == b"\0\0"
        await stream.aclose()
        await closed.wait()


async def test_empty_or_precancelled_input_does_not_connect(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("Must not connect")

    monkeypatch.setattr("echooo.providers.tts.dashscope.connect", unexpected)
    provider = DashScopeTTS(settings())
    assert [c async for c in provider.stream_audio(" ", cancel=asyncio.Event())] == []
    cancelled = asyncio.Event()
    cancelled.set()
    assert await collect(provider, cancelled) == []
