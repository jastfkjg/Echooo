import asyncio
import base64
import json
import time
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

from echooo import database as db
from echooo.meeting_agent import MeetingAgent, addressed, stop_request
from echooo.meeting_bots import AttendeeClient
from echooo.models import AudioChunk, STTEvent, STTEventType
from test_meeting_bots import app, client, meeting, invite


@pytest.fixture
def agent(client, app):
    base = meeting(client)
    invite(client, base, 'https://zoom.us/j/123456789')
    manager = app.state.meeting_bots
    row = manager.rows()[0]
    manager.update(row, state='joined_recording')
    result = MeetingAgent(manager, row)
    manager.agents[row['id']] = result
    return result


def chat(key='one', text='hi', sender='1024', audience='private', **extra):
    return {'id': key, 'text': text, 'sender_uuid': sender, 'sender_name': 'Test participant',
        'to': 'everyone', 'additional_data': {'echooo_audience': audience, **extra}}


@pytest.mark.parametrize('text,voice,expected', [
    ('Echooo，总结一下', True, True), ('hey Echo, what did we decide?', True, True),
    ('我们稍后问 Echooo', True, False), ('@Echooo 总结', False, True),
    ('hi everyone', False, False), ('echolocation', False, False), ('艾可，你好', True, True),
    ('We can ask Echooo later', False, False), ('这个问题请 @Echooo 回答', False, True),
])
def test_address_policy(text, voice, expected):
    assert addressed(text, voice=voice) is expected


async def test_private_routes_only_to_sender_and_public_requires_address(agent):
    await agent.chat(chat())
    event = agent.queue.get_nowait()
    await agent.answer(event)
    assert agent.manager.client.chats[0][1] == '1024'
    assert event['audience'] == 'private' and event['status'] == 'submitted'
    await agent.chat(chat('public', 'hi everyone', audience='public'))
    assert agent.queue.empty()
    await agent.chat(chat('addressed', '@Echooo 总结一下', audience='public'))
    await agent.answer(agent.queue.get_nowait())
    assert agent.manager.client.chats[-1][1] is None
    with agent.store.scope(agent.who) as r:
        assert not r.list(db.utterances)  # Private messages never become meeting notes.


async def test_zoom_unpatched_unknown_and_self_messages_never_reply(agent):
    old = chat(); old['additional_data'] = {}
    await agent.chat(old)
    await agent.chat(chat('unknown', audience='unknown'))
    await agent.chat(chat('self', echooo_is_self=True))
    assert agent.queue.empty() and agent.events() == []
    assert 'recipient' in agent.poll_error


@pytest.mark.parametrize('sender', ['0', 'NaN', '-1', '1024suffix'])
async def test_private_sender_cannot_be_coerced_to_broadcast(agent, sender):
    await agent.chat(chat(sender=sender))
    assert agent.queue.empty()


@pytest.mark.parametrize('platform', ['google_meet', 'teams'])
async def test_adapters_without_private_delivery_never_broadcast_private_text(agent, platform):
    agent.row['platform'] = platform
    message = chat(); message['to'] = 'only_bot'
    await agent.chat(message)
    assert agent.queue.empty() and not agent.events()


async def test_durable_dedup_including_edited_messages_and_restart(agent):
    await agent.chat(chat())
    await agent.answer(agent.queue.get_nowait())
    await agent.chat(chat(text='edited text'))
    restarted = MeetingAgent(agent.manager, agent.row)
    await restarted.chat(chat())
    assert restarted.queue.empty()
    assert len(agent.manager.client.chats) == 1
    agent.manager.update(agent.row, state='ended', desired_state='left')
    saved = MeetingAgent.saved_view(agent.manager, agent.row)
    assert saved['phase'] == 'stopped' and saved['events'][0]['response']


async def test_context_filters_before_generation(agent):
    await agent.chat(chat('private-a', 'SECRET_A'))
    await agent.chat(chat('private-b', 'SECRET_B', sender='2048'))
    await agent.chat(chat('public', 'PUBLIC_INFORMATION', audience='public'))
    await agent.accept('ask', 'summarize', 'voice', '')
    events = agent.events()
    public = next(e for e in events if e['source_key'] == 'ask')
    context = json.dumps(agent.context(public))
    assert 'SECRET_' not in context and 'PUBLIC_INFORMATION' in context
    await agent.chat(chat('ask-a', 'summarize', sender='1024'))
    event = next(e for e in agent.events() if e['source_key'] == 'chat:ask-a')
    context = json.dumps(agent.context(event))
    assert 'SECRET_A' in context and 'SECRET_B' not in context


async def test_uncertain_delivery_is_not_automatically_retried(agent):
    async def fail(*_):
        raise httpx.ReadTimeout('upstream contains private diagnostic')
    agent.manager.client.send_chat = fail
    await agent.chat(chat())
    event = agent.queue.get_nowait()
    with pytest.raises(httpx.ReadTimeout):
        await agent.answer(event)
    assert event['status'] == 'uncertain'
    assert 'private diagnostic' not in event['error']
    restarted = MeetingAgent(agent.manager, agent.row)
    await restarted.chat(chat())
    assert restarted.queue.empty()


class Socket:
    def __init__(self, agent=None):
        self.packets = []
        self.agent = agent
        self.samples = 0

    async def send_json(self, packet):
        self.packets.append(packet)
        if self.agent and packet['trigger'] == 'echooo.audio':
            data = packet['data']
            if data['action'] == 'chunk':
                self.samples += len(base64.b64decode(data['chunk'])) // 2
            self.agent.playback.receive({**data, 'done': data['action'] == 'finish',
                'buffered_ms': 0, 'received_samples': self.samples, 'played_samples': self.samples})


async def test_voice_final_only_echo_suppression_pcm_format_and_tail(agent):
    agent.settings = replace(agent.settings, tts_provider='dashscope')
    class TTS:
        async def stream_audio(self, text, *, cancel):
            yield AudioChunk(b'\x01\x00' * 2500, 24000)
    agent.tts_factory = TTS
    socket = agent.manager.sockets[agent.cid] = Socket(agent)
    await agent.transcript(STTEvent(STTEventType.PARTIAL, 'Echooo 总结'), 'one')
    assert agent.queue.empty()
    await agent.transcript(STTEvent(STTEventType.FINAL, 'Echooo 总结'), 'one')
    event = agent.queue.get_nowait()
    agent.last_speech = 0
    await agent.answer(event)
    assert event['status'] == 'spoken'
    assert socket.packets[0]['data']['sample_rate'] == 24000
    packets = [p for p in socket.packets if p['data']['action'] == 'chunk']
    assert len(packets) == 1
    pcm = b''.join(base64.b64decode(p['data']['chunk']) for p in packets)
    assert pcm == b'\x01\x00' * 2500  # Tail is drained exactly, without padded silence.
    await agent.transcript(STTEvent(STTEventType.FINAL, agent.last_spoken), 'self')
    assert agent.queue.empty()
    agent.manager.sockets.pop(agent.cid)


async def test_stop_cancels_generation_and_pending_voice_not_private_chat(agent):
    entered = asyncio.Event()
    async def slow(event):
        agent.phase = 'thinking'
        entered.set()
        await asyncio.Future()
    agent.answer = slow
    socket = agent.manager.sockets[agent.cid] = Socket(agent)
    await agent.playback.start(24000)
    await agent.accept('voice:1', 'Echooo 总结', 'voice', '')
    work = asyncio.create_task(agent.work())
    await entered.wait()
    await agent.accept('voice:2', 'Echooo 总结', 'voice', '')
    await agent.chat(chat('private'))
    await agent.stop()
    assert socket.packets[-1]['data']['action'] == 'stop'
    statuses = {e['source_key']: e['status'] for e in agent.events()}
    assert statuses['voice:1'] == statuses['voice:2'] == 'interrupted'
    assert statuses['chat:private'] in {'queued', 'thinking'}
    agent.closed = True
    work.cancel()
    await asyncio.gather(work, return_exceptions=True)
    agent.manager.sockets.pop(agent.cid)


async def test_disabled_voice_and_chat_do_not_generate(agent):
    await agent.configure(False, False)
    await agent.chat(chat())
    await agent.transcript(STTEvent(STTEventType.FINAL, 'Echooo 总结'), 'a')
    assert agent.queue.empty()
    restored = MeetingAgent(agent.manager, agent.row)
    assert not restored.prefs['voice_enabled'] and not restored.prefs['chat_enabled']


async def test_leave_revokes_pending_response_before_send(agent):
    await agent.chat(chat())
    event = agent.queue.get_nowait()
    agent.manager.update(agent.row, desired_state='left')
    with pytest.raises(asyncio.CancelledError):
        await agent.answer(event)
    assert not agent.manager.client.chats


def test_controls_require_owner_and_validate_preferences(agent, client, app):
    base = '/api/meetings/' + agent.mid + '/bot'
    outsider = TestClient(app)
    assert outsider.post(base + '/stop').status_code == 401
    assert client.patch(base + '/agent', json={'chat_enabled': True, 'voice_enabled': False}).status_code == 200
    assert client.post(base + '/stop').status_code == 200
    assert client.patch(base + '/agent', json={'recipient': 'everyone'}).status_code == 422


async def test_pagination_never_follows_untrusted_url_and_private_payload(agent):
    connector = AttendeeClient(agent.settings)
    calls = []
    async def request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == 'POST':
            return {}
        return {'results': [{'id': str(len(calls))}], 'next':
            'https://attacker.invalid/steal?cursor=two' if len(calls) == 1 else None}
    connector.request = request
    assert len(await connector.chat_messages('bot_Test', time.time())) == 2
    assert all(c[1] == 'bots/bot_Test/chat_messages' for c in calls)
    await connector.send_chat('bot_Test', 'hello', '1024')
    assert calls[-1][2]['json'] == {'message': 'hello', 'to': 'specific_user', 'to_user_uuid': '1024'}


@pytest.mark.parametrize('text', ['Echooo，停止', 'stop', '停一下', 'Echo, please stop'])
def test_stop_phrases(text):
    assert stop_request(text)


@pytest.mark.parametrize('generated,expected', [(False, 'generate a reply'), (True, 'Could not speak')])
async def test_failure_reports_generation_separately_from_speech(agent, generated, expected, caplog):
    async def fail(event):
        if generated:
            agent.change(event, response='Generated answer')
        raise ValueError('PRIVATE_PROVIDER_DIAGNOSTIC')
    agent.answer = fail
    await agent.accept('voice:failure', 'Echooo，你好', 'voice', '')
    worker = asyncio.create_task(agent.work())
    try:
        async with asyncio.timeout(2):
            while not agent.error:
                await asyncio.sleep(.01)
        assert expected in agent.error
        assert 'PRIVATE_PROVIDER_DIAGNOSTIC' not in caplog.text + agent.error
        assert 'error_type=ValueError' in caplog.text
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
