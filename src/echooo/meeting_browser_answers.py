"""Capture-socket-owned answers. Stored events are history, never playback commands."""
import asyncio
import contextlib
import logging
import secrets
import time
from types import SimpleNamespace

from echooo import database as db
from echooo.meeting_debug import agent_record
from echooo.intelligence import Intelligence
from echooo.meeting_agent import MeetingAgent
from echooo.meeting_live import timed_words
from echooo.models import STTEvent, STTEventType
from echooo.meeting_retrieval import transcript_stamp
from echooo.meeting_speech import mark_speech

logger = logging.getLogger(__name__)
PENDING = {'queued', 'thinking', 'searching', 'sending', 'speaking'}
LEASE_SECONDS = 8
ECHO_TAIL_MS = 2000


def history(manager, who, mid):
    """Public browser answers, including failed delivery, without ephemeral tokens."""
    from echooo.meeting_answers import checks
    audit = checks(manager.store, who, mid)
    with manager.store.scope(who) as r:
        rows = r.list(db.meeting_agent_events, db.meeting_agent_events.c.meeting_id == mid,
            db.meeting_agent_events.c.connection_id.like('browser-recording:%'))
    return [{**{k: e[k] for k in ('id', 'audience', 'request', 'response', 'status', 'error', 'created_at')},
        'answer_check': audit.get(e['id']), 'citations': manager.knowledge.citations(who, mid, e['id'])}
        for e in sorted(rows, key=lambda e: e['created_at'])[-20:]]


class BrowserPlayback:
    """Same turn controller, with socket-owned browser synthesis as the transport."""
    def __init__(self, agent):
        self.agent = agent

    async def pause(self):
        await self.command('pause')

    async def resume(self):
        await self.command('resume')

    async def command(self, action):
        receipt = self.agent.receipt
        if receipt and receipt['started']:
            await self.agent.emit({'type': 'direct_playback', 'id': receipt['id'],
                'token': receipt['token'], 'action': action})


class BrowserMeetingAnswers:
    context = MeetingAgent.context
    is_echo = MeetingAgent.is_echo
    conversation_active = MeetingAgent.conversation_active
    end_conversation = MeetingAgent.end_conversation
    invalidate_decision = MeetingAgent.invalidate_decision
    decide_turn = MeetingAgent.decide_turn
    speaker_for = MeetingAgent.speaker_for
    resume_speech = MeetingAgent.resume_speech
    tentative_interrupt = MeetingAgent.tentative_interrupt

    def __init__(self, manager, who, mid, recording_id, send, validate):
        self.manager, self.store, self.settings = manager, manager.store, manager.settings
        self.who, self.mid, self.recording_id = who, mid, recording_id
        self.cid = 'browser-recording:' + recording_id
        self.send, self.validate = send, validate
        self.intelligence = Intelligence(self.settings)
        self.enabled = self.closed = False
        self.cancel = asyncio.Event()
        self.phase, self.error = 'listening', ''
        self.task = self.current_event = self.receipt = self.retired = None
        self.notifications = set()
        self.blocked_until_ms = -1
        self.guard_until = 0
        self.external = False
        self.prefs = {'voice_enabled': True}
        self.conversation_until = self.echo_until = self.last_speech = 0
        self.conversation_speaker = None
        self.last_spoken = ''
        self.speakers = []
        self.barge_task = self.decision_task = None
        self.barge_started = self.barge_updated = 0
        self.barge_text = ''
        self.barge_speaker = None
        self.turn_revision = 0
        self.turn_decision = None
        self.playback_start_ms = None
        self.speech_windows = []
        self.playback = BrowserPlayback(self)
        # A new recorder cannot resume any older recorder's pending output.
        with self.store.scope(who) as r:
            for e in r.list(db.meeting_agent_events, db.meeting_agent_events.c.meeting_id == mid,
                    db.meeting_agent_events.c.connection_id.like('browser-recording:%')):
                if e['status'] in PENDING:
                    r.change(db.meeting_agent_events, e['id'], status='interrupted',
                        error='Recording disconnected; this reply was not replayed.')
                    for check in r.list(db.meeting_answer_checks, db.meeting_answer_checks.c.event_id == e['id']):
                        if check['detail'].get('support') == 'pending':
                            r.change(db.meeting_answer_checks, check['id'],
                                detail={**check['detail'], 'support': 'unavailable', 'failure': 'restart'})
        self.watchdog = asyncio.create_task(self.watch())

    def valid(self):
        if self.closed or not self.enabled:
            return False
        try:
            self.validate()
            with self.store.scope(self.who) as r:
                rec = r.get(db.recordings, self.recording_id)
            return bool(rec and rec['meeting_id'] == self.mid)
        except Exception:
            return False

    async def emit(self, packet):
        if packet.get('type') in {'direct_playback', 'direct_ack', 'direct_cancel'}:
            agent_record(self, 'playback', **{k: packet[k] for k in
                ('type', 'id', 'action', 'status', 'playback') if k in packet})
        with contextlib.suppress(Exception):
            await self.send(packet)

    def change(self, event, **values):
        with self.store.scope(self.who) as r:
            if not r.get(db.meeting_agent_events, event['id']):
                return
            r.change(db.meeting_agent_events, event['id'], **values)
        event.update(values)
        agent_record(self, 'delivery', answer_id=event['id'], **values)
        job = asyncio.create_task(self.emit({'type': 'direct_status', 'id': event['id'],
            'status': event['status'], 'response': event['response'], 'error': event['error']}))
        self.notifications.add(job)
        job.add_done_callback(self.notifications.discard)
        self.manager.transcriptions.feed.publish(self.who, self.mid, {'type': 'answer_activity'})

    def guard(self):
        """Audio-clock watermark also rejects STT results delayed beyond playback."""
        with self.store.scope(self.who) as r:
            rec = r.get(db.recordings, self.recording_id)
        if rec:
            self.blocked_until_ms = max(self.blocked_until_ms,
                round(rec['samples'] * 1000 / rec['sample_rate']) + ECHO_TAIL_MS)

    def audio_clock(self):
        with self.store.scope(self.who) as r:
            rec = r.get(db.recordings, self.recording_id)
        return round(rec['samples'] * 1000 / rec['sample_rate']) if rec else 0

    def finish_window(self):
        if self.speech_windows and self.speech_windows[-1]['end'] is None:
            self.speech_windows[-1]['end'] = self.audio_clock() + ECHO_TAIL_MS

    def playback_echo(self, text, start):
        # Audio time remains valid when STT arrives after the wall-clock echo tail.
        return any(start >= w['start'] and (w['end'] is None or start <= w['end']) and
            MeetingAgent.is_echo(SimpleNamespace(last_spoken=w['text'], echo_until=float('inf')), text)
            for w in self.speech_windows)

    async def transcript(self, event, rows, offset_ms=0):
        if not self.valid():
            return
        # Approved suggestions retain their independent host-controlled lifecycle.
        if self.external:
            self.guard()
            return
        if event.type == STTEventType.PARTIAL:
            words = timed_words(event.raw.get('words'), offset_ms)
            start = words[0]['start'] if words else None
            # Untimed partials cannot establish that speech began during playback.
            if self.receipt and self.receipt['started'] and (
                    start is None or start < self.playback_start_ms):
                return
            if start is not None and start <= self.blocked_until_ms:
                return
            if self.is_echo(event.transcript) or (start is not None and self.playback_echo(event.transcript, start)):
                return
            await MeetingAgent.transcript(self, event, self.recording_id + ':partial')
            return
        for u in rows:
            if u['start_ms'] <= self.blocked_until_ms:
                continue
            if self.receipt and self.receipt['started'] and u['start_ms'] < self.playback_start_ms:
                continue
            if self.is_echo(u['content']) or self.playback_echo(u['content'], u['start_ms']):
                agent_record(self, 'trigger', decision='echo', text=u['content'][:2000], source_id=u['id'])
                continue
            final = STTEvent(STTEventType.FINAL, u['content'], raw={'speaker_label': u['speaker']})
            await MeetingAgent.transcript(self, final, self.recording_id + ':' + u['id'])

    async def accept(self, key, text, audience, sender):
        if not self.valid():
            return
        with self.store.scope(self.who) as r:
            if r.list(db.meeting_agent_events, db.meeting_agent_events.c.connection_id == self.cid,
                    db.meeting_agent_events.c.source_key == key):
                return
            e = r.add(db.meeting_agent_events, meeting_id=self.mid, connection_id=self.cid,
                source_key=key, audience=audience, sender=sender, request=text,
                response='', status='queued', error='')
        self.current_event = e
        self.cancel = asyncio.Event()
        self.task = asyncio.create_task(self.answer(e))

    async def answer(self, event):
        try:
            await MeetingAgent.answer(self, event)
        except asyncio.CancelledError:
            self.change(event, status='interrupted', error=self.error or 'Reply stopped; not replayed automatically.')
        except Exception as exc:
            logger.warning('Browser answer failed meeting=%s type=%s', self.mid, type(exc).__name__)
            await self.emit({'type': 'direct_cancel', 'id': event['id']})
            self.change(event, status='error', error=self.error or 'Unable to complete this reply. Please ask again.')
        finally:
            if self.current_event is event:
                self.current_event = None
                self.phase = 'listening'

    async def speak(self, text, event):
        if not self.valid() or self.cancel.is_set() or self.external:
            raise asyncio.CancelledError()
        done = asyncio.get_running_loop().create_future()
        receipt = {'id': event['id'], 'token': secrets.token_urlsafe(32), 'started': False,
            'expires': time.monotonic() + LEASE_SECONDS, 'done': done, 'event': event}
        self.receipt = receipt
        self.change(event, status='sending')
        await self.emit({'type': 'direct_offer', 'id': event['id'], 'token': receipt['token']})
        try:
            await asyncio.wait_for(done, 120)
            mark_speech(self, event, complete=True)
            self.echo_until = time.monotonic() + 2
            if self.conversation_until:
                self.conversation_until = time.monotonic() + 15
        finally:
            if self.receipt is receipt:
                self.finish_window()
                self.receipt = None

    async def stop(self, reason='Reply stopped; not replayed automatically.', *, end_conversation=True):
        self.invalidate_decision()
        if end_conversation:
            self.end_conversation()
        if self.barge_task and self.barge_task is not asyncio.current_task():
            self.barge_task.cancel()
            await asyncio.gather(self.barge_task, return_exceptions=True)
            self.barge_task = None
        self.error = reason
        self.cancel.set()
        if self.receipt:
            self.retired = self.receipt
            if self.receipt['started']:
                self.echo_until = time.monotonic() + 2
            await self.emit({'type': 'direct_cancel', 'id': self.receipt['id']})
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        if self.current_event and self.current_event['status'] in PENDING:
            self.change(self.current_event, status='interrupted', error=reason)
            self.current_event = None
        self.task = None
        self.phase = 'listening'

    async def control(self, packet):
        """Only called from the same authenticated capture socket; no replay API."""
        request_id = packet.get('request_id')
        try:
            action = packet.get('action')
            if packet['type'] == 'direct_config':
                self.enabled = packet.get('enabled') is True
                aec = packet.get('echo_cancellation')
                if aec is None or isinstance(aec, bool) or aec in ('all', 'remote-only'):
                    logger.info('Browser microphone settings: recording=%s echo_cancellation=%s', self.recording_id, aec)
                if not self.enabled:
                    self.guard()
                    await self.stop()
                return
            if packet['type'] == 'direct_stop':
                self.guard()
                await self.stop()
                return
            if packet['type'] == 'local_speech_guard':
                self.external = packet.get('active') is True
                self.guard()
                self.guard_until = max(self.guard_until, time.monotonic() + LEASE_SECONDS) if self.external else (self.receipt['expires'] if self.receipt else 0)
                if self.external:
                    await self.stop()
                await self.emit({'type': 'direct_ack', 'request_id': request_id, 'ok': True})
                return
            if (self.retired and action in {'cancelled', 'failed'} and
                    packet.get('id') == self.retired['id'] and packet.get('token') == self.retired['token']):
                if not self.receipt and not self.external:
                    self.guard_until = 0
                self.retired = None
                await self.emit({'type': 'direct_ack', 'request_id': request_id, 'ok': True})
                return
            receipt = self.receipt
            if (not self.valid() or not receipt or packet.get('id') != receipt['id'] or
                    not isinstance(packet.get('token'), str) or
                    not secrets.compare_digest(packet['token'], receipt['token']) or
                    time.monotonic() >= receipt['expires']):
                raise ValueError('Playback is no longer current.')
            if action == 'start':
                if receipt['started'] or self.external:
                    raise ValueError('Playback already started.')
                if (self.answer_stamp is not None and
                        transcript_stamp(self.store, self.who, self.mid) != self.answer_stamp):
                    raise ValueError('Discussion changed before playback.')
                if not self.manager.knowledge.valid(self.who, self.mid, self.speech_scope):
                    raise ValueError('Knowledge changed before playback.')
                receipt['started'] = True
                with self.store.scope(self.who) as r:
                    rec = r.get(db.recordings, self.recording_id)
                self.playback_start_ms = round(rec['samples'] * 1000 / rec['sample_rate'])
                self.last_spoken = receipt['event']['response']
                self.speech_windows.append({'start': self.playback_start_ms, 'end': None, 'text': self.last_spoken})
                self.echo_until = time.monotonic() + 125
                self.phase = 'speaking'
                mark_speech(self, receipt['event'])
                self.change(receipt['event'], status='speaking')
            elif action not in {'heartbeat', 'spoken', 'cancelled', 'failed'}:
                raise ValueError('Invalid playback action.')
            elif not receipt['started'] and action in {'heartbeat', 'spoken'}:
                raise ValueError('Playback has not started.')
            if action in {'start', 'heartbeat'}:
                if not self.manager.knowledge.valid(self.who, self.mid, self.speech_scope):
                    raise ValueError('Knowledge changed during playback.')
                receipt['expires'] = time.monotonic() + LEASE_SECONDS
                self.guard_until = receipt['expires']
            else:
                self.guard_until = 0
                if receipt['done'].done():
                    raise ValueError('Playback already finished.')
                if action == 'spoken':
                    receipt['done'].set_result(None)
                elif action == 'failed':
                    self.error = 'Browser playback failed. Check sound permissions, then ask again.'
                    receipt['done'].set_exception(ValueError('Browser playback failed.'))
                else:
                    await self.stop()
            await self.emit({'type': 'direct_ack', 'request_id': request_id, 'ok': True,
                'playback': self.phase,
                **({'question': receipt['event']['response']} if action == 'start' else {})})
        except (ValueError, KeyError):
            await self.emit({'type': 'direct_ack', 'request_id': request_id, 'ok': False,
                'error': 'Playback is no longer current. Please ask again.'})

    async def watch(self):
        while not self.closed:
            await asyncio.sleep(.25)
            if self.external and time.monotonic() >= self.guard_until:
                self.guard()
                self.external = False
            if self.external:
                self.guard()
            if self.task and not self.task.done():
                expired = self.receipt and time.monotonic() >= self.receipt['expires']
                if not self.valid() or expired:
                    await self.stop('Recording or playback disconnected; this reply was not replayed.')

    async def close(self):
        self.closed = True
        await self.stop('Recording ended; this reply was not replayed.')
        self.watchdog.cancel()
        await asyncio.gather(self.watchdog, *([self.decision_task] if self.decision_task else []),
            *self.notifications, return_exceptions=True)
