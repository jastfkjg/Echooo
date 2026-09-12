"""Durable verification of saved meeting audio and reconnecting live transport."""
from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import shutil
import time
import wave
from collections import defaultdict

import httpx
from sqlalchemy import select

from echooo import database as db
from echooo.models import STTEventType
from echooo.service import Problem

logger = logging.getLogger(__name__)
POLL_SECONDS = 3
RECONNECT_SECONDS = 1
FINAL_TIMEOUT = 8


def missing_passages(result, existing, duration_ms, recording_id):
    """Fill uncovered word intervals, retaining existing IDs, text and corrections.

    Batch diarization labels are local to that job. Reuse a live label only when
    overlapping speech unambiguously supports it; otherwise distinguish it.
    """
    utterances = result.get('utterances') or []
    if not utterances and result.get('words'):
        utterances = [{'speaker': None, 'words': result['words']}]
    if result.get('text') and not utterances:
        raise ValueError('Transcription returned text without timed words')
    intervals = [(u['start_ms'], u['end_ms']) for u in existing]
    votes = defaultdict(lambda: defaultdict(float))
    for u in utterances:
        for w in u.get('words') or []:
            for old in existing:
                overlap = min(w['end'], old['end_ms']) - max(w['start'], old['start_ms'])
                if overlap > 0 and old['speaker'] != 'Unknown speaker':
                    votes[u.get('speaker')][old['speaker']] += overlap
    names = {}
    for speaker, scores in votes.items():
        name, score = max(scores.items(), key=lambda item: item[1])
        if score / sum(scores.values()) >= .85:
            names[speaker] = name
    additions = []
    for u in utterances:
        label = u.get('speaker')
        speaker = names.get(label) or (f'Recovered speaker {str(label)[:20]} · {recording_id[:4]}' if label is not None else 'Unknown speaker')
        current = None
        for w in u.get('words') or []:
            start, end, text = w.get('start'), w.get('end'), w.get('text', '')
            if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or not isinstance(text, str):
                raise ValueError('Invalid word timestamps')
            start, end = max(0, round(start)), min(duration_ms, round(end))
            if end <= start or not text.strip():
                continue
            midpoint = (start + end) / 2
            if any(a <= midpoint < b for a, b in intervals):
                current = None
                continue
            if current and start - current['end_ms'] < 2000 and len(current['content']) + len(text) < 600:
                current['content'] += ' ' + text.strip()
                current['end_ms'] = end
            else:
                current = dict(speaker=speaker, content=text.strip(), start_ms=start, end_ms=end)
                additions.append(current)
    return additions


class BatchTranscriber:
    def __init__(self, settings):
        self.settings = settings

    def client(self):
        return httpx.AsyncClient(base_url=self.settings.assemblyai_api_url.rstrip('/'),
            headers={'Authorization': self.settings.assemblyai_api_key}, timeout=httpx.Timeout(60, write=300))

    async def submit(self, audio):
        # Lossless compression makes long recordings practical on slower uplinks.
        # WAV remains supported on installations without ffmpeg.
        if len(audio) > 1024 * 1024 and shutil.which('ffmpeg'):
            process = await asyncio.create_subprocess_exec('ffmpeg', '-hide_banner', '-loglevel', 'error',
                '-i', 'pipe:0', '-f', 'flac', 'pipe:1', stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            try:
                compressed, _ = await asyncio.wait_for(process.communicate(audio), 60)
                if process.returncode == 0 and compressed:
                    audio = compressed
            except TimeoutError:
                pass
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
        async def chunks():
            for offset in range(0, len(audio), 65536):
                yield audio[offset:offset + 65536]

        async with self.client() as client:
            response = await client.post('/v2/upload', content=chunks(), headers={
                'Content-Type': 'application/octet-stream', 'Content-Length': str(len(audio))})
            response.raise_for_status()
            response = await client.post('/v2/transcript', json={
                'audio_url': response.json()['upload_url'],
                'speech_models': ['universal-3-pro', 'universal-2'],
                'speaker_labels': True, 'language_detection': True})
            response.raise_for_status()
            return response.json()['id']

    async def result(self, job_id):
        async with self.client() as client:
            response = await client.get(f'/v2/transcript/{job_id}')
            response.raise_for_status()
            return response.json()

    async def delete(self, job_id):
        async with self.client() as client:
            response = await client.delete(f'/v2/transcript/{job_id}')
            response.raise_for_status()


class RecordingTranscriptions:
    def __init__(self, store, settings, locks):
        self.store, self.settings, self.locks = store, settings, locks
        self.tasks = {}
        self.provider = BatchTranscriber(settings)
        self.on_complete = None

    @property
    def available(self):
        return self.settings.stt_provider == 'assemblyai' and bool(self.settings.assemblyai_api_key)

    def state(self, who, mid, rid, **changes):
        with self.store.scope(who) as r:
            rec = r.get(db.recordings, rid)
            if not rec or rec['meeting_id'] != mid:
                raise Problem('Recording not found.', 404)
            rows = r.list(db.recording_transcriptions, db.recording_transcriptions.c.recording_id == rid)
            value = dict(rows[0]['state']) if rows else {'phase': 'unverified', 'verified_samples': 0}
            if changes:
                value.update(changes, updated_at=time.time())
                if rows:
                    r.change(db.recording_transcriptions, rows[0]['id'], state=value)
                else:
                    r.add(db.recording_transcriptions, meeting_id=mid, recording_id=rid, state=value)
            return value

    def start(self, who, mid, rid, *, retry=False):
        if not self.available:
            raise Problem('Configure AssemblyAI to verify saved audio.', 503)
        if rid in self.tasks:
            return
        state = self.state(who, mid, rid)
        if state['phase'] == 'complete' and state.get('summary_phase') != 'building' and not (retry and state.get('summary_phase') == 'error'):
            return
        changes = {'phase': 'complete' if state['phase'] == 'complete' else 'verifying', 'message': '', 'summary_error': ''}
        if state['phase'] == 'complete':
            changes['summary_phase'] = 'building'
        if retry and state.get('provider_failed'):
            changes.update(job_id=None, provider_failed=False)
        self.state(who, mid, rid, **changes)
        task = asyncio.create_task(self.run(who, mid, rid))
        self.tasks[rid] = task
        task.add_done_callback(lambda _: self.tasks.pop(rid, None))

    async def run(self, who, mid, rid):
        try:
            state = self.state(who, mid, rid)
            if state['phase'] == 'complete':
                await self.update_summary(who, mid, rid)
                return
            job_id = state.get('job_id')
            with self.store.scope(who) as r:
                rec = r.get(db.recordings, rid)
                if not rec:
                    return
                parts = sorted(r.list(db.audio_parts, db.audio_parts.c.recording_id == rid), key=lambda p: p['sequence']) if not job_id else []
            if not rec['samples']:
                self.state(who, mid, rid, phase='complete', verified_samples=0)
                return
            if not job_id:
                if [p['sequence'] for p in parts] != list(range(len(parts))) or sum(len(p['pcm']) for p in parts) != rec['samples'] * 2:
                    raise ValueError('Saved audio has missing parts')
                buffer = io.BytesIO()
                with wave.open(buffer, 'wb') as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(rec['sample_rate'])
                    for p in parts:
                        wav.writeframesraw(p['pcm'])
                job_id = await asyncio.wait_for(self.provider.submit(buffer.getvalue()), 900)
                self.state(who, mid, rid, job_id=job_id)
            deadline = time.monotonic() + 1800
            failures = 0
            while True:
                try:
                    result = await self.provider.result(job_id)
                    failures = 0
                except (httpx.TimeoutException, httpx.NetworkError):
                    failures += 1
                    if failures >= 5:
                        raise
                    await asyncio.sleep(POLL_SECONDS)
                    continue
                if result.get('status') == 'completed':
                    duration = result.get('audio_duration')
                    if isinstance(duration, (int, float)) and duration + 2 < rec['samples'] / rec['sample_rate']:
                        self.state(who, mid, rid, provider_failed=True)
                        raise ValueError('Provider processed only part of the saved audio')
                    break
                if result.get('status') == 'error':
                    self.state(who, mid, rid, provider_failed=True)
                    raise ValueError('Audio transcription provider could not process the recording')
                if time.monotonic() > deadline:
                    raise TimeoutError('Audio verification timed out')
                await asyncio.sleep(POLL_SECONDS)
            # Applying additions and invalidating summaries is one owner-scoped transaction.
            async with self.locks[mid]:
                with self.store.scope(who) as r:
                    rec = r.get(db.recordings, rid)
                    if not rec:
                        return
                    existing = r.list(db.utterances, db.utterances.c.recording_id == rid)
                    additions = missing_passages(result, existing, round(rec['samples'] / rec['sample_rate'] * 1000), rid)
                    for values in additions:
                        r.add(db.utterances, meeting_id=mid, recording_id=rid, **values)
                    if additions:
                        meeting = r.get(db.meetings, mid)
                        r.change(db.meetings, mid, revision=meeting['revision'] + 1)
                        for section in r.list(db.meeting_sections, db.meeting_sections.c.meeting_id == mid):
                            r.change(db.meeting_sections, section['id'], status='stale')
                    row = r.list(db.recording_transcriptions, db.recording_transcriptions.c.recording_id == rid)[0]
                    r.change(db.recording_transcriptions, row['id'], state={**row['state'],
                        'phase': 'complete', 'verified_samples': rec['samples'], 'recovered_passages': len(additions),
                        'message': '', 'summary_phase': 'building', 'updated_at': time.time()})
                    r.log('meeting.transcript_verified', meeting_id=mid, recording_id=rid, recovered_passages=len(additions))
            with contextlib.suppress(Exception):
                await self.provider.delete(job_id)
            await self.update_summary(who, mid, rid)
        except asyncio.CancelledError:
            raise  # Persist the job ID so a subsequent visit resumes polling.
        except Exception as exc:
            logger.warning('Meeting audio verification failed: recording=%s type=%s', rid, type(exc).__name__)
            code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            message = ('Transcription access was denied. Check the AssemblyAI key.' if code in {401, 403} else
                'Transcription quota or rate limit reached. Retry later.' if code == 429 else
                'Audio upload or verification timed out. Retry to continue.' if isinstance(exc, (TimeoutError, httpx.TimeoutException)) else
                'Audio is saved. Verification failed; retry to continue.')
            with contextlib.suppress(Problem):
                self.state(who, mid, rid, phase='error', message=message)

    async def update_summary(self, who, mid, rid):
        try:
            if self.on_complete:
                await self.on_complete(who, mid, rid)
            self.state(who, mid, rid, summary_phase='complete', summary_error='')
        except asyncio.CancelledError:
            raise
        except Exception:
            self.state(who, mid, rid, summary_phase='error', summary_error='Transcript is ready. Retry updating the summary.')

    def resume(self):
        """Startup recovery: enumerate durable jobs, then operate in each owner scope."""
        if not self.available:
            return
        with self.store.engine.connect() as connection:
            rows = list(connection.execute(select(db.recording_transcriptions)).mappings())
        for row in rows:
            state = row['state']
            if state['phase'] in {'verifying', 'connecting', 'live', 'reconnecting'} or state.get('summary_phase') == 'building':
                self.start(row['owner_id'], row['meeting_id'], row['recording_id'])

    async def cancel(self, rid):
        task = self.tasks.get(rid)
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def close(self):
        for rid in list(self.tasks):
            await self.cancel(rid)


class LiveTranscription:
    """Bounded transport independent of audio persistence; gaps are repaired later."""
    def __init__(self, factory, rate, on_event, on_state, *, agent_context=''):
        self.factory, self.rate = factory, rate
        self.on_event, self.on_state = on_event, on_state
        self.queue = asyncio.Queue(maxsize=150)  # 15 seconds at the normal 100 ms frame size.
        self.samples = 0
        self.stopping = False
        self.task = None
        self.provider = None
        self.agent_context = agent_context
        self.session = 0

    def feed(self, pcm, samples):
        start = samples - len(pcm) // 2
        self.samples = samples
        # Providers accept 50–1000 ms. Always send <=100 ms, including buffered stop frames.
        frame_bytes = self.rate // 10 * 2
        if self.queue.qsize() + (len(pcm) + frame_bytes - 1) // frame_bytes > self.queue.maxsize:
            while not self.queue.empty():
                self.queue.get_nowait()
            self.queue.put_nowait(None)  # Reconnect using the next frame's absolute offset.
        for offset in range(0, len(pcm), frame_bytes):
            if not self.queue.full():
                self.queue.put_nowait((start + offset // 2, pcm[offset:offset + frame_bytes]))

    def start(self):
        self.task = asyncio.create_task(self.run())

    async def run(self):
        attempts = 0
        while not self.stopping or not self.queue.empty():
            receiver = sender = None
            try:
                first = await self.queue.get()
                if first is None:
                    continue
                base_sample, pcm = first
                self.session += 1
                session = self.session
                self.provider = self.factory()
                if hasattr(self.provider, 'speaker_labels'):
                    self.provider.speaker_labels = True
                await asyncio.wait_for(self.provider.connect(**({'agent_context': self.agent_context} if self.agent_context else {})), 10)
                await self.on_state('live', 'Live transcription reconnected. Saved audio will be checked when recording stops.' if session > 1 else '')
                offset_ms = round(base_sample * 1000 / self.rate)

                async def receive():
                    async for event in self.provider.events():
                        if event.type in {STTEventType.ERROR, STTEventType.TERMINATED}:
                            if self.stopping and event.type == STTEventType.TERMINATED:
                                return
                            raise ConnectionError('Transcription stream ended')
                        await self.on_event(event, offset_ms, session)
                    if not self.stopping:
                        raise ConnectionError('Transcription stream closed')

                async def transmit():
                    item = first
                    while True:
                        if item is None:
                            if self.stopping:
                                if hasattr(self.provider, 'finish'):
                                    await self.provider.finish()
                                else:
                                    await self.provider.send_audio(bytes(self.rate * 2))
                                return
                            raise ConnectionError('Transcription fell behind')
                        pcm = item[1]
                        # A worklet flush may contain <50 ms. Pad only the STT
                        # transport; saved samples and transcript anchors stay exact.
                        minimum_bytes = self.rate // 20 * 2
                        if len(pcm) < minimum_bytes:
                            pcm += bytes(minimum_bytes - len(pcm))
                        await asyncio.wait_for(self.provider.send_audio(pcm), 3)
                        item = await self.queue.get()

                receiver = asyncio.create_task(receive())
                sender = asyncio.create_task(transmit())
                done, _ = await asyncio.wait([receiver, sender], return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
                if self.stopping:
                    if not receiver.done():
                        await asyncio.wait_for(receiver, FINAL_TIMEOUT if hasattr(self.provider, 'finish') else 1)
                    return
                raise ConnectionError('Transcription transport stopped')
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self.stopping:
                    return
                attempts += 1
                logger.warning('Live transcription reconnect: session=%s type=%s', self.session, type(exc).__name__)
                await self.on_state('reconnecting', 'Audio is saving. Reconnecting transcription…')
                # Start fresh near real time; saved audio is the durable backlog.
                while not self.queue.empty():
                    self.queue.get_nowait()
                await asyncio.sleep(min(RECONNECT_SECONDS * 2 ** min(attempts - 1, 4), 15))
            finally:
                for task in (receiver, sender):
                    if task:
                        task.cancel()
                        with contextlib.suppress(asyncio.CancelledError, Exception):
                            await task
                if self.provider:
                    with contextlib.suppress(Exception):
                        await asyncio.wait_for(self.provider.close(), 2)
                self.provider = None

    async def finish(self):
        self.stopping = True
        if self.task:
            try:
                await asyncio.wait_for(self.queue.put(None), 2)
                await asyncio.wait_for(self.task, FINAL_TIMEOUT + 4)
            except (TimeoutError, asyncio.CancelledError):
                self.task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self.task
