"""Self-hosted Attendee transport and explicitly addressed meeting assistance.

Creation is durable before network I/O; uncertain requests are reconciled by the
provider deduplication key, never retried by creating another participant.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import re
import secrets
import time
from dataclasses import replace
from datetime import datetime, timezone
from urllib.parse import urlsplit, parse_qs

import httpx
from fastapi import Request, WebSocket, WebSocketDisconnect
from pydantic import Field, field_validator
from sqlalchemy import select

from echooo import database as db
from echooo.contracts import Input
from echooo.meeting_transcription import LiveTranscription
from echooo.meeting_agent import MeetingAgent
from echooo.models import STTEventType
from echooo.meeting_live import TranscriptWriter
from echooo.providers.factory import create_stt
from echooo.service import Problem, need

logger = logging.getLogger(__name__)
TERMINAL = {'ended', 'fatal_error', 'data_deleted', 'not_created'}
PROVIDER_STATES = TERMINAL | {'ready', 'joining', 'waiting_room', 'joined_not_recording',
    'joined_recording', 'joined_recording_paused', 'joined_recording_permission_denied',
    'leaving', 'post_processing', 'joining_breakout_room', 'leaving_breakout_room'}
RATE = 16000


class MediaTokenFilter(logging.Filter):
    def filter(self, record):
        # Uvicorn logs accepted WebSocket URLs, including bearer query tokens.
        if isinstance(record.args, tuple):
            record.args = tuple(re.sub(r'(/ws/meeting-bots/[^?\s\"\']+)\?[^\s\"\']+', r'\1?[redacted]', value)
                if isinstance(value, str) else value for value in record.args)
        return True


def meeting_platform(value: str) -> str:
    try:
        if any(ord(c) < 33 for c in value):
            raise ValueError()
        url = urlsplit(value)
        host = (url.hostname or '').lower()
        if url.scheme != 'https' or url.username or url.password or url.port not in {None, 443} or url.fragment:
            raise ValueError()
        if host == 'meet.google.com' and re.fullmatch(r'/[a-z]{3}-[a-z]{4}-[a-z]{3}/?', url.path):
            return 'google_meet'
        if (host == 'zoom.us' or host.endswith('.zoom.us') or host == 'zoom.com' or host.endswith('.zoom.com')) and re.fullmatch(r'/(?:j|s)/[0-9]+/?', url.path):
            return 'zoom'
        if host in {'teams.microsoft.com', 'teams.live.com', 'teams.cloud.microsoft'} and url.path.startswith(('/l/meetup-join/', '/meet/')):
            return 'teams'
    except ValueError:
        pass
    raise ValueError('Use a direct HTTPS Google Meet, Zoom, or Microsoft Teams meeting link.')


class JoinMeeting(Input):
    meeting_url: str = Field(min_length=1, max_length=2048)
    bot_name: str = Field(default='Echooo AI', min_length=1, max_length=60)

    @field_validator('meeting_url')
    @classmethod
    def url(cls, value):
        value = value.strip()
        meeting_platform(value)
        return value

    @field_validator('bot_name')
    @classmethod
    def name(cls, value):
        value = value.strip()
        if not value or any(ord(c) < 32 for c in value):
            raise ValueError('Enter a participant name.')
        return value if re.search(r'\bAI\b', value, re.I) else value + ' · AI'


class AgentSettings(Input):
    chat_enabled: bool
    voice_enabled: bool


class AttendeeClient:
    def __init__(self, settings):
        self.settings = settings

    async def request(self, method, path, **kwargs):
        async with httpx.AsyncClient(base_url=self.settings.attendee_base_url.rstrip('/') + '/',
                headers={'Authorization': 'Token ' + self.settings.attendee_api_key},
                timeout=20, follow_redirects=False) as client:
            response = await client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json() if response.content else {}

    async def create(self, payload):
        return await self.request('POST', 'bots', json=payload)

    async def get(self, provider_id):
        return await self.request('GET', 'bots/' + provider_id)

    async def find(self, key):
        result = await self.request('GET', 'bots', params={'deduplication_key': key})
        rows = result if isinstance(result, list) else result.get('results', [])
        return rows[0] if rows else None

    async def leave(self, provider_id):
        return await self.request('POST', 'bots/' + provider_id + '/leave')

    async def chat_messages(self, provider_id, after):
        params = {'updated_after': datetime.fromtimestamp(after, timezone.utc).isoformat()}
        messages, seen = [], set()
        for _ in range(40):
            page = await self.request('GET', 'bots/' + provider_id + '/chat_messages', params=params)
            if isinstance(page, list):
                return messages + page
            messages.extend(page['results'])
            if not page.get('next'):
                return messages
            # Never follow a provider-supplied URL with the connector bearer token.
            cursor = parse_qs(urlsplit(page['next']).query).get('cursor', [''])[0]
            if not cursor or cursor in seen:
                raise ValueError('Invalid chat pagination')
            seen.add(cursor)
            params['cursor'] = cursor
        raise ValueError('Too many chat pages')

    async def send_chat(self, provider_id, text, recipient=None):
        # The provider rejects non-BMP characters. Recipient selection is application policy.
        text = ''.join(c for c in text if ord(c) <= 0xffff)
        payload = {'message': text, 'to': 'specific_user' if recipient else 'everyone'}
        if recipient:
            payload['to_user_uuid'] = recipient
        return await self.request('POST', 'bots/' + provider_id + '/send_chat_message', json=payload)


def rejection_message(response):
    if response.status_code in {401, 403}:
        return 'Echooo could not authenticate to Attendee. Check ATTENDEE_API_KEY and its project access.'
    try:
        detail = response.json()
    except ValueError:
        detail = {}
    if isinstance(detail, dict):
        error = detail.get('error', '')
        if isinstance(error, str) and error.startswith('Zoom App credentials are required'):
            return ('Zoom App credentials are missing in the Attendee project. Open Attendee Settings → Credentials '
                'and add the Client ID and Client Secret of a Zoom General App with Meeting SDK enabled. '
                'For meetings hosted outside that Zoom account, app review and user authorization are also required. See docs/ATTENDEE.md.')
        if 'meeting_url' in detail:
            return 'Attendee did not accept this meeting link. Paste the full direct invitation URL, including its passcode if present.'
    return 'Attendee rejected the join request. Check the meeting link, platform permissions and connector configuration in the Attendee dashboard.'


class BotRecording:
    """One recording per connection (or 30-minute segment), keeping gaps explicit."""
    def __init__(self, manager, row):
        self.manager, self.row = manager, row
        self.who, self.mid = row['owner_id'], row['meeting_id']
        self.samples, self.sequence, self.last_end = 0, 0, 0
        self.seen = set()
        self.pending = bytearray()
        with manager.store.scope(self.who) as r:
            self.rec = r.add(db.recordings, meeting_id=self.mid, sample_rate=RATE, samples=0)
        manager.transcriptions.state(self.who, self.mid, self.rec['id'], phase='connecting' if manager.settings.stt_provider != 'mock' else 'unverified', message='')
        self.writer = TranscriptWriter(manager.store, self.who, self.mid, self.rec['id'], manager.transcriptions.feed)
        agent = manager.agents.get(row['id'])
        if agent:
            agent.recording_id = self.rec['id']
        self.live = None
        if manager.settings.stt_provider != 'mock':
            stt_settings = replace(manager.settings, assemblyai_sample_rate=RATE)
            self.live = LiveTranscription(lambda: create_stt(stt_settings), RATE, self.consume, self.state,
                agent_context='')
            self.live.start()

    async def state(self, phase, message):
        self.manager.transcriptions.state(self.who, self.mid, self.rec['id'], phase=phase, message=message)
        if phase != 'live':
            self.writer.clear()

    async def consume(self, event, offset_ms, session):
        from echooo.answer_timing import stt_anchor
        if event.type == STTEventType.FINAL:
            event.raw['_answer_timing'] = stt_anchor(event, self.rec['id'], offset_ms, round(self.samples * 1000 / RATE))
        rows = self.writer.consume(event, offset_ms, session, round(self.samples * 1000 / RATE))
        agent = self.manager.agents.get(self.row['id'])
        if agent and (event.type == STTEventType.PARTIAL or event.type == STTEventType.FINAL and rows):
            await agent.transcript(event, f'{self.rec["id"]}:{session}:{event.raw.get("turn_order", self.samples)}', rows)

    def feed(self, pcm):
        self.samples += len(pcm) // 2
        with self.manager.store.scope(self.who) as r:
            r.add(db.audio_parts, meeting_id=self.mid, recording_id=self.rec['id'], sequence=self.sequence, pcm=pcm)
            r.change(db.recordings, self.rec['id'], samples=self.samples)
        self.sequence += 1
        if self.live:
            # Browser adapters send very small chunks. Coalesce before STT,
            # whose minimum-frame padding would otherwise expand every chunk.
            self.pending.extend(pcm)
            frame_bytes = RATE // 10 * 2
            while len(self.pending) >= frame_bytes:
                frame = bytes(self.pending[:frame_bytes])
                del self.pending[:frame_bytes]
                self.live.feed(frame, self.samples - len(self.pending) // 2)

    async def finish(self):
        if self.live:
            if self.pending:
                self.live.feed(bytes(self.pending), self.samples)
                self.pending.clear()
            await self.live.finish()
        self.writer.clear()
        await self.manager.transcriptions.finish_recording(self.who, self.mid, self.rec['id'], self.live)


class MeetingBots:
    def __init__(self, store, settings, transcriptions, captures):
        self.store, self.settings, self.transcriptions, self.captures = store, settings, transcriptions, captures
        self.client = AttendeeClient(settings)
        self.lock = asyncio.Lock()
        self.sockets = {}
        self.last_audio = {}
        self.agents = {}
        self.task = None
        self.closed = False

    @property
    def configured(self):
        return bool(self.settings.attendee_base_url and self.settings.attendee_api_key and self.settings.attendee_callback_url)

    def rows(self):
        # Trusted lifecycle/authentication lookup; browser routes always use owner scope.
        with self.store.engine.connect() as c:
            return [dict(row) for row in c.execute(select(db.meeting_bots)).mappings()]

    def row(self, who, mid):
        with self.store.scope(who) as r:
            return next(iter(r.list(db.meeting_bots, db.meeting_bots.c.meeting_id == mid)), None)

    def update(self, row, **values):
        with self.store.scope(row['owner_id']) as r:
            r.change(db.meeting_bots, row['id'], **values, updated_at=time.time())
        row.update(values)

    def active(self, who, mid):
        row = self.row(who, mid)
        return bool(row and row['state'] not in TERMINAL)

    def require_detached(self, who, mid):
        if self.active(who, mid):
            raise Problem('Let Echooo AI leave the online meeting before recording locally, ending, or deleting it.', 409)

    def view(self, who, mid):
        row = self.row(who, mid)
        return {'configured': self.configured, 'bot': None if not row else {
            key: row[key] for key in ('id', 'meeting_url', 'platform', 'bot_name', 'state', 'desired_state', 'error', 'updated_at', 'deadline')
        }, 'audio_connected': bool(row and row['id'] in self.sockets),
            'last_audio_at': self.last_audio.get(row['id']) if row else None,
            'agent': (self.agents[row['id']].view() if row['id'] in self.agents else MeetingAgent.saved_view(self, row)) if row else None}

    def ensure_agent(self, row):
        if row['id'] not in self.agents and row['state'] == 'joined_recording' and row['desired_state'] == 'joined':
            agent = self.agents[row['id']] = MeetingAgent(self, row)
            agent.start()
        return self.agents.get(row['id'])

    def start(self):
        self.closed = False
        self.task = asyncio.create_task(self.monitor())

    async def join(self, who, mid, data):
        if not self.configured:
            raise Problem('The meeting connector is not configured. Follow docs/ATTENDEE.md to start self-hosted Attendee.', 503)
        async with self.lock:
            with self.store.scope(who) as r:
                meeting = need(r.get(db.meetings, mid), 'Meeting')
                if meeting['status'] != 'active' or mid in self.captures:
                    raise Problem('Use an active meeting without a local recording.', 409)
            # The bundled worker is intentionally single-meeting; prevent audio sharing.
            if any(row['state'] not in TERMINAL for row in self.rows()):
                raise Problem('A meeting participant is already active. Let it leave before joining another meeting.', 409)
            token = secrets.token_urlsafe(32)
            old = self.row(who, mid)
            with self.store.scope(who) as r:
                if old:
                    r.remove(db.meeting_bots, old['id'])
                row = r.add(db.meeting_bots, meeting_id=mid, meeting_url=data.meeting_url,
                    platform=meeting_platform(data.meeting_url), bot_name=data.bot_name, provider_id=None,
                    state='creating', desired_state='joined', callback_hash=db.token_hash(token), error='',
                    deadline=time.time() + self.settings.attendee_max_seconds, updated_at=time.time())
            payload = {'meeting_url': data.meeting_url, 'bot_name': data.bot_name,
                'deduplication_key': row['id'], 'metadata': {'echooo_connection': row['id']},
                'recording_settings': {'format': 'none', 'record_participant_speech_start_stop_events': True},
                'transcription_settings': {'meeting_closed_captions': {}},
                'websocket_settings': {'audio': {'url': self.settings.attendee_callback_url.rstrip('/') + '/ws/meeting-bots/' + row['id'] + '?token=' + token, 'sample_rate': RATE}},
                'automatic_leave_settings': {'max_uptime_seconds': self.settings.attendee_max_seconds,
                    'waiting_room_timeout_seconds': 600, 'wait_for_host_to_start_meeting_timeout_seconds': 600,
                    'only_participant_in_meeting_timeout_seconds': 60}}
            # Native Zoom defaults to a second paid STT provider. Use its web adapter
            # with platform captions; Echooo transcribes the streamed audio itself.
            if row['platform'] == 'zoom':
                payload['zoom_settings'] = {'sdk': 'web'}
            try:
                result = await self.client.create(payload)
                self.apply_result(row, result)
            except httpx.HTTPStatusError as exc:
                if 400 <= exc.response.status_code < 500 and exc.response.status_code != 409:
                    message = rejection_message(exc.response)
                    self.update(row, state='not_created', desired_state='left', error=message)
                else:
                    self.update(row, state='unknown', error='Join status is uncertain. Checking Attendee before allowing another request.')
            except httpx.ConnectError:
                self.update(row, state='not_created', desired_state='left', error='Cannot connect to Attendee. Start the connector, then try again.')
            except (httpx.HTTPError, ValueError, KeyError):
                self.update(row, state='unknown', error='Join status is uncertain. Checking Attendee before allowing another request.')
            return self.view(who, mid)

    def apply_result(self, row, result):
        provider_id = result.get('id')
        state = result.get('state')
        if not isinstance(provider_id, str) or not re.fullmatch(r'bot_[A-Za-z0-9]+', provider_id) or state not in PROVIDER_STATES:
            raise ValueError('Invalid Attendee status')
        error = ''
        if state == 'fatal_error':
            error = 'Attendee could not continue. Check admission, sign-in and platform permissions in the connector dashboard.'
        if state == 'joined_recording_permission_denied':
            error = 'The host has not allowed audio capture. Grant permission in the meeting or let Echooo leave.'
        self.update(row, provider_id=provider_id, state=state, error=error,
            **({'desired_state': 'left'} if state in TERMINAL else {}))

    async def leave(self, who, mid):
        async with self.lock:
            row = self.row(who, mid)
            if not row:
                raise Problem('No meeting participant to remove.', 404)
            if row['state'] in TERMINAL:
                return self.view(who, mid)
            # Revoke media immediately, even when the upstream leave request fails.
            self.update(row, desired_state='left', error='')
            await self.disconnect(row['id'])
            await self.reconcile(row)
            return self.view(who, mid)

    async def disconnect(self, row_id):
        agent = self.agents.pop(row_id, None)
        if agent:
            await agent.close()
        ws = self.sockets.get(row_id)
        if ws:
            with contextlib.suppress(Exception):
                await ws.close(code=1000)

    async def reconcile(self, row):
        try:
            result = await self.client.get(row['provider_id']) if row['provider_id'] else await self.client.find(row['id'])
            if result is None:
                # Don't assume an eventually consistent empty list means no bot exists.
                self.update(row, state='unknown', error='Attendee has not confirmed this request. Check the connector dashboard; another bot will not be created.')
                return
            self.apply_result(row, result)
            if row['state'] in TERMINAL:
                await self.disconnect(row['id'])
                return
            if row['state'] != 'joined_recording' and row['id'] in self.agents:
                await self.agents[row['id']].stop(all_replies=True)
            if row['desired_state'] == 'joined' and time.time() < row['deadline']:
                self.ensure_agent(row)
            if row['desired_state'] == 'left' or time.time() >= row['deadline']:
                self.update(row, desired_state='left')
                await self.disconnect(row['id'])
                await self.client.leave(row['provider_id'])
                self.update(row, state='leaving', error='')
        except (httpx.HTTPError, ValueError, KeyError):
            self.update(row, error='Cannot confirm Attendee status. Reconnecting; if needed, remove Echooo AI directly from the meeting.')

    async def monitor(self):
        while not self.closed:
            if self.configured:
                async with self.lock:
                    for row in self.rows():
                        if row['state'] not in TERMINAL:
                            await self.reconcile(row)
            await asyncio.sleep(5)

    async def close(self):
        self.closed = True
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
        for row in self.rows():
            if row['state'] not in TERMINAL:
                self.update(row, desired_state='left')
                await self.disconnect(row['id'])
                if self.configured:
                    await self.reconcile(row)

    async def media(self, ws, row_id):
        token = ws.query_params.get('token', '')
        row = next((r for r in self.rows() if r['id'] == row_id and secrets.compare_digest(r['callback_hash'], db.token_hash(token))), None)
        if not token or not row or row['state'] in TERMINAL or row['desired_state'] != 'joined' or time.time() >= row['deadline'] or row_id in self.sockets:
            await ws.close(code=1008)
            return
        who, mid = row['owner_id'], row['meeting_id']
        with self.store.scope(who) as r:
            meeting = r.get(db.meetings, mid)
        if not meeting or meeting['status'] != 'active' or mid in self.captures:
            await ws.close(code=1008)
            return
        self.sockets[row_id] = ws
        self.captures.add(mid)
        sink = None
        try:
            await ws.accept()
            while True:
                packet = await asyncio.wait_for(ws.receive(), 30)
                if packet['type'] == 'websocket.disconnect':
                    break
                row = self.row(who, mid)
                if row and not row['provider_id']:
                    # The media connection can arrive before the create response.
                    async with self.lock:
                        row = self.row(who, mid)
                        if row and not row['provider_id']:
                            await self.reconcile(row)
                if not row or row['id'] != row_id or row['desired_state'] != 'joined' or row['state'] in TERMINAL or time.time() >= row['deadline']:
                    break
                text = packet.get('text') or ''
                if len(text) > 100000:
                    raise ValueError('Oversize frame')
                data = json.loads(text)
                if data.get('trigger') in {'echooo.audio_status', 'echooo.speaker'}:
                    if data.get('bot_id') != row['provider_id'] or not isinstance(data.get('data'), dict):
                        raise ValueError('Wrong stream identity')
                    agent = self.ensure_agent(row)
                    if agent:
                        if data['trigger'] == 'echooo.audio_status':
                            agent.playback.receive(data['data'])
                        else:
                            agent.speaker_event(data['data'])
                    continue
                if data.get('trigger') != 'realtime_audio.mixed' or data.get('bot_id') != row['provider_id']:
                    raise ValueError('Wrong stream identity')
                audio = data['data']
                if audio.get('sample_rate') != RATE or not isinstance(audio.get('chunk'), str):
                    raise ValueError('Invalid PCM format')
                pcm = base64.b64decode(audio['chunk'], validate=True)
                if not pcm or len(pcm) > RATE * 4 or len(pcm) % 2:
                    raise ValueError('Invalid PCM frame')
                if sink and sink.samples + len(pcm) // 2 > RATE * 1800:
                    await sink.finish()
                    sink = None
                if sink is None:
                    self.ensure_agent(row)
                    sink = BotRecording(self, row)
                sink.feed(pcm)
                self.last_audio[row_id] = time.time()
        except (ValueError, KeyError, TypeError, TimeoutError, WebSocketDisconnect, RuntimeError):
            logger.warning('Meeting bot media disconnected: connection=%s', row_id)
        finally:
            try:
                if row_id in self.agents:
                    await self.agents[row_id].stop()
                if sink:
                    await sink.finish()
            finally:
                self.sockets.pop(row_id, None)
                self.captures.discard(mid)
                with contextlib.suppress(Exception):
                    await ws.close()


def install_meeting_bots(app, store, settings, transcriptions, captures, owner):
    for name in ('uvicorn.access', 'uvicorn.error'):
        access = logging.getLogger(name)
        if not any(isinstance(f, MediaTokenFilter) for f in access.filters):
            access.addFilter(MediaTokenFilter())
    manager = MeetingBots(store, settings, transcriptions, captures)
    app.state.meeting_bots = manager

    @app.post('/api/meetings/{mid}/bot', status_code=202)
    async def join(request: Request, mid: str, data: JoinMeeting):
        return await manager.join(owner(request), mid, data)

    @app.get('/api/meetings/{mid}/bot')
    async def status(request: Request, mid: str):
        who = owner(request)
        with store.scope(who) as r:
            need(r.get(db.meetings, mid), 'Meeting')
        return manager.view(who, mid)

    @app.post('/api/meetings/{mid}/bot/leave', status_code=202)
    async def leave(request: Request, mid: str):
        return await manager.leave(owner(request), mid)

    def owned_agent(request, mid):
        who = owner(request)
        with store.scope(who) as r:
            need(r.get(db.meetings, mid), 'Meeting')
        row = manager.row(who, mid)
        agent = manager.agents.get(row['id']) if row else None
        if not agent:
            raise Problem('Wait until Echooo has joined the meeting.', 409)
        return who, agent

    @app.patch('/api/meetings/{mid}/bot/agent')
    async def agent_settings(request: Request, mid: str, data: AgentSettings):
        who, agent = owned_agent(request, mid)
        await agent.configure(data.chat_enabled, data.voice_enabled)
        return manager.view(who, mid)

    @app.post('/api/meetings/{mid}/bot/stop')
    async def stop_speaking(request: Request, mid: str):
        who, agent = owned_agent(request, mid)
        await agent.stop()
        return manager.view(who, mid)

    @app.websocket('/ws/meeting-bots/{row_id}')
    async def media(ws: WebSocket, row_id: str):
        await manager.media(ws, row_id)

    return manager
