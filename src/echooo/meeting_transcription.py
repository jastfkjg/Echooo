"""On-demand saved-audio repair and reconnecting live transport."""
from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import shutil
import time
import wave
from collections import defaultdict, deque

import httpx
from sqlalchemy import select

from echooo import database as db
from echooo.models import STTEventType
from echooo.meeting_live import TranscriptFeed, join_words, timed_words, label_name, invalidate, remember, segments
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


def reconcile_passages(r, result, existing, rid):
    """Refine machine fields in place; IDs, human edits and evidence survive.

    Batch labels belong to the complete recording, so this also reconciles
    labels across streaming reconnects. Ambiguous intervals stay unattributed.
    Legacy records without provenance retain their text.
    """
    sources = {s['utterance_id']: s for s in r.list(db.utterance_sources,
        db.utterance_sources.c.recording_id == rid)}
    words = []
    for passage in result.get('utterances') or []:
        words.extend({**w, 'speaker': w.get('speaker', passage.get('speaker'))}
            for w in timed_words(passage.get('words')))
    if not words:
        return []
    # A user's explicit name can anchor a batch speaker, only with clear evidence.
    votes = defaultdict(lambda: defaultdict(float))
    for u in existing:
        source = sources.get(u['id'])
        if not source or not source['state'].get('speaker_edited') or u['speaker'] == 'Unknown speaker':
            continue
        for w in words:
            overlap = min(u['end_ms'], w['end']) - max(u['start_ms'], w['start'])
            if overlap > 0 and w.get('speaker') is not None:
                votes[w['speaker']][u['speaker']] += overlap
    names = {}
    for label, counts in votes.items():
        name, count = max(counts.items(), key=lambda p: p[1])
        if count >= 500 and count / sum(counts.values()) >= .85:
            names[label] = name
    changed = []
    for u in list(existing):
        part = [w for w in words if u['start_ms'] <= (w['start'] + w['end']) / 2 < u['end_ms']]
        if not part:
            continue
        source = sources.get(u['id'])
        state = source['state'] if source else {}
        values = {}
        groups = segments(part, None)
        # Rebuild machine-only turn boundaries from final word-level attribution.
        # Keep the original ID for the first turn; new turns receive their own anchors.
        if (source and not state.get('content_edited') and not state.get('speaker_edited')
                and u['content'] == state['content'] and u['speaker'] == state['speaker'] and len(groups) > 1):
            for index, (label, group) in enumerate(groups):
                values = dict(content=join_words(group)[:6000], speaker=names.get(label) or label_name(label, rid),
                    start_ms=group[0]['start'], end_ms=group[-1]['end'])
                if index == 0:
                    r.change(db.utterances, u['id'], **values)
                    u.update(values)
                    r.change(db.utterance_sources, source['id'], state={**state, **values, 'words': group})
                    changed.append(dict(u))
                else:
                    extra = r.add(db.utterances, meeting_id=u['meeting_id'], recording_id=rid, **values)
                    remember(r, extra, words=group)
                    existing.append(extra)
                    changed.append(extra)
            continue
        if source and not state.get('content_edited') and u['content'] == state['content']:
            values['content'] = join_words(part)[:6000]
        if (source and not state.get('speaker_edited') and u['speaker'] == state['speaker']) or (not source and u['speaker'] == 'Unknown speaker'):
            counts = defaultdict(float)
            for w in part:
                counts[w.get('speaker')] += w['end'] - w['start']
            label, count = max(counts.items(), key=lambda p: p[1])
            values['speaker'] = (names.get(label) or label_name(label, rid)) if count / sum(counts.values()) >= .85 else 'Unknown speaker'
        if any(u[k] != v for k, v in values.items()):
            r.change(db.utterances, u['id'], **values)
            u.update(values)
            changed.append(dict(u))
        if source:
            r.change(db.utterance_sources, source['id'], state={**state, 'words': part,
                'content': values.get('content', state['content']), 'speaker': values.get('speaker', state['speaker'])})
    return changed


class BatchTranscriber:
    def __init__(self, settings):
        self.settings = settings

    def client(self):
        return httpx.AsyncClient(base_url=self.settings.assemblyai_api_url.rstrip('/'),
            headers={'Authorization': self.settings.assemblyai_api_key}, timeout=httpx.Timeout(60, write=300))

    async def submit(self, audio, *, upload_url=None, checkpoint=lambda **changes: None):
        # Lossless compression makes long recordings practical on slower uplinks.
        # WAV remains supported on installations without ffmpeg.
        if not upload_url and len(audio) > 1024 * 1024 and shutil.which('ffmpeg'):
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
            if not upload_url:
                checkpoint(stage='uploading')
                response = await client.post('/v2/upload', content=chunks(), headers={
                    'Content-Type': 'application/octet-stream', 'Content-Length': str(len(audio))})
                response.raise_for_status()
                upload_url = response.json()['upload_url']
                checkpoint(upload_url=upload_url)
            # A lost POST response is ambiguous: never silently create a second paid job.
            checkpoint(stage='submitting', submission_uncertain=True)
            try:
                response = await client.post('/v2/transcript', json={
                    'audio_url': upload_url,
                    'speech_models': ['universal-3-pro', 'universal-2'],
                    'speaker_labels': True, 'language_detection': True})
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if 400 <= exc.response.status_code < 500:
                    checkpoint(submission_uncertain=False)
                raise
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
        self.feed = TranscriptFeed()

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

    async def finish_recording(self, who, mid, rid, live):
        """Only observed transport/finalization failures request saved-audio repair."""
        bounds = live.repair_bounds() if live else None
        self.state(who, mid, rid, phase='live_ready' if live else 'unverified',
            message='', summary_phase='building')
        if bounds and self.available:
            self.state(who, mid, rid, phase='unverified', summary_phase='pending', mode='repair', repair_start_ms=bounds[0], repair_end_ms=bounds[1])
            self.start(who, mid, rid)
        else:
            if bounds:
                self.state(who, mid, rid, phase='interrupted', message='Live transcription was interrupted. Existing transcript is available.')
            self.schedule_summary(who, mid, rid)

    def schedule_summary(self, who, mid, rid):
        if rid in self.tasks:
            return
        self.state(who, mid, rid, summary_phase='building', summary_error='')
        task = asyncio.create_task(self.update_summary(who, mid, rid))
        self.tasks[rid] = task
        task.add_done_callback(lambda _: self.tasks.pop(rid, None))

    def start(self, who, mid, rid, *, retry=False, full=False):
        if rid in self.tasks:
            return
        state = self.state(who, mid, rid)
        if not full and state['phase'] in {'complete', 'live_ready', 'unverified', 'interrupted'} and state.get('summary_phase') in {'building', 'error'}:
            self.schedule_summary(who, mid, rid)
            return
        if not self.available:
            raise Problem('Configure AssemblyAI to repair saved audio.', 503)
        if full:
            state = self.state(who, mid, rid, phase='unverified', mode='full', job_id=None,
                upload_url=None, submission_uncertain=False, provider_failed=False,
                repair_start_ms=None, repair_end_ms=None, summary_phase='pending')
        if state.get('submission_uncertain') and not state.get('job_id'):
            self.state(who, mid, rid, phase='error', message='Transcription submission is unconfirmed. Use full reprocessing only if you accept a possible duplicate charge.')
            return
        if state['phase'] in {'complete', 'live_ready'} and state.get('summary_phase') != 'building' and not (retry and state.get('summary_phase') == 'error'):
            return
        changes = {'phase': state['phase'] if state['phase'] in {'complete', 'live_ready'} else 'verifying', 'message': '', 'summary_error': ''}
        if state['phase'] in {'complete', 'live_ready'}:
            changes['summary_phase'] = 'building'
        if retry and state.get('provider_failed'):
            changes.update(job_id=None, provider_failed=False, submission_uncertain=False)
        self.state(who, mid, rid, **changes)
        task = asyncio.create_task(self.run(who, mid, rid))
        self.tasks[rid] = task
        task.add_done_callback(lambda _: self.tasks.pop(rid, None))

    async def run(self, who, mid, rid):
        try:
            state = self.state(who, mid, rid)
            if state['phase'] in {'complete', 'live_ready'}:
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
            start_ms = state.get('repair_start_ms') or 0
            end_ms = state.get('repair_end_ms') or round(rec['samples'] * 1000 / rec['sample_rate'])
            if not job_id:
                self.state(who, mid, rid, stage='preparing')
                if [p['sequence'] for p in parts] != list(range(len(parts))) or sum(len(p['pcm']) for p in parts) != rec['samples'] * 2:
                    raise ValueError('Saved audio has missing parts')
                buffer = io.BytesIO()
                with wave.open(buffer, 'wb') as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(rec['sample_rate'])
                    pcm = b''.join(p['pcm'] for p in parts)
                    wav.writeframesraw(pcm[round(start_ms * rec['sample_rate'] / 1000)*2:round(end_ms * rec['sample_rate'] / 1000)*2])
                job_id = await asyncio.wait_for(self.provider.submit(buffer.getvalue(),
                    upload_url=state.get('upload_url'),
                    checkpoint=lambda **changes: self.state(who, mid, rid, **changes)), 900)
                self.state(who, mid, rid, job_id=job_id, submission_uncertain=False)
            self.state(who, mid, rid, stage='polling')
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
                    if isinstance(duration, (int, float)) and duration + 2 < (end_ms - start_ms) / 1000:
                        self.state(who, mid, rid, provider_failed=True)
                        raise ValueError('Provider processed only part of the saved audio')
                    break
                if result.get('status') == 'error':
                    self.state(who, mid, rid, provider_failed=True)
                    raise ValueError('Audio transcription provider could not process the recording')
                if time.monotonic() > deadline:
                    raise TimeoutError('Audio verification timed out')
                await asyncio.sleep(POLL_SECONDS)
            # Range jobs return relative timestamps. Offset before merging; never
            # overwrite a live utterance with only its clipped boundary words.
            if start_ms:
                for passage in result.get('utterances') or []:
                    for w in passage.get('words') or []:
                        w['start'] += start_ms
                        w['end'] += start_ms
                for w in result.get('words') or []:
                    w['start'] += start_ms
                    w['end'] += start_ms
            self.state(who, mid, rid, stage='applying')
            # Applying additions and invalidating summaries is one owner-scoped transaction.
            async with self.locks[mid]:
                with self.store.scope(who) as r:
                    rec = r.get(db.recordings, rid)
                    if not rec:
                        return
                    existing = r.list(db.utterances, db.utterances.c.recording_id == rid)
                    changed = [] if state.get('mode') == 'repair' else reconcile_passages(r, result, existing, rid)
                    additions = missing_passages(result, existing, round(rec['samples'] / rec['sample_rate'] * 1000), rid)
                    for values in additions:
                        values['speaker'] = values['speaker'].replace('Recovered speaker ', 'Speaker ', 1)
                        values['content'] = join_words([{'text': values['content']}])
                        u = r.add(db.utterances, meeting_id=mid, recording_id=rid, **values)
                        remember(r, u, batch=True)
                        changed.append(u)
                    if changed:
                        invalidate(r, mid)
                    row = r.list(db.recording_transcriptions, db.recording_transcriptions.c.recording_id == rid)[0]
                    r.change(db.recording_transcriptions, row['id'], state={**row['state'],
                        'phase': 'complete', 'stage': 'complete', 'upload_url': None,
                        'verified_samples': rec['samples'] if state.get('mode') != 'repair' else 0, 'recovered_passages': len(additions),
                        'corrected_passages': len(changed) - len(additions),
                        'message': '', 'summary_phase': 'building', 'updated_at': time.time()})
                    r.log('meeting.transcript_verified', meeting_id=mid, recording_id=rid, recovered_passages=len(additions))
            for u in changed:
                self.feed.publish(who, mid, {'type': 'utterance', 'utterance': u})
            self.feed.publish(who, mid, {'type': 'resync'})
            with contextlib.suppress(Exception):
                await self.provider.delete(job_id)
            await self.update_summary(who, mid, rid)
        except asyncio.CancelledError:
            raise  # Persist the job ID so a subsequent visit resumes polling.
        except Exception as exc:
            stage = self.state(who, mid, rid).get('stage', 'preparing')
            logger.warning('Meeting transcript repair failed: recording=%s stage=%s type=%s status=%s', rid, stage, type(exc).__name__, exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None)
            code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            message = ('Transcription access was denied. Check the AssemblyAI key.' if code in {401, 403} else
                'Transcription quota or rate limit reached. Retry later.' if code == 429 else
                'Audio upload or verification timed out. Retry to continue.' if isinstance(exc, (TimeoutError, httpx.TimeoutException)) else
                f'Audio and existing transcript are available. Repair failed during {stage}.')
            if self.state(who, mid, rid).get('submission_uncertain'):
                message = 'Transcription submission is unconfirmed. Existing transcript is available. Full reprocessing may cause a duplicate charge.'
            with contextlib.suppress(Problem):
                self.state(who, mid, rid, phase='error', message=message, error_stage=stage, error_type=type(exc).__name__, error_status=code)

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
        with self.store.engine.connect() as connection:
            rows = list(connection.execute(select(db.recording_transcriptions)).mappings())
        for row in rows:
            state = row['state']
            if state['phase'] in {'connecting', 'live', 'reconnecting'}:
                self.state(row['owner_id'], row['meeting_id'], row['recording_id'], phase='interrupted',
                    message='Recording was interrupted. Saved audio and the existing transcript are available.')
            elif state['phase'] == 'verifying' and self.available:
                self.start(row['owner_id'], row['meeting_id'], row['recording_id'])
            elif state.get('summary_phase') == 'building' and state['phase'] in {'complete', 'live_ready', 'unverified', 'interrupted'}:
                self.schedule_summary(row['owner_id'], row['meeting_id'], row['recording_id'])

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
        self.audio_arrivals = deque(maxlen=600)
        self.stopping = False
        self.task = None
        self.provider = None
        self.agent_context = agent_context
        self.session = 0
        self.last_final_sample = 0
        self.gap_start = None
        self.gap_end = 0
        self.terminated = False
        self.pending_partial = False

    def annotate_final_timing(self, event, offset_ms):
        received = event.raw['_received_monotonic'] = time.monotonic()
        if event.type != STTEventType.FINAL:
            return
        words = timed_words(event.raw.get('words'), offset_ms)
        if not words:
            return
        end_sample = round(words[-1]['end'] * self.rate / 1000)
        frame = next((item for item in self.audio_arrivals if item[0] < end_sample <= item[1]), None)
        if frame:
            event.raw['_stt_finalization_ms'] = max(0, round((received - frame[2]) * 1000))
            event.raw['_stt_frame_ms'] = round((frame[1] - frame[0]) * 1000 / self.rate)

    def mark_gap(self):
        self.gap_start = min(self.gap_start, self.last_final_sample) if self.gap_start is not None else self.last_final_sample
        self.gap_end = self.samples

    def repair_bounds(self):
        if self.gap_start is None or not self.samples:
            return None
        return (max(0, round(self.gap_start * 1000 / self.rate) - 5000),
            min(round(self.samples * 1000 / self.rate), round(self.gap_end * 1000 / self.rate) + 5000))

    def feed(self, pcm, samples):
        start = samples - len(pcm) // 2
        self.audio_arrivals.append((start, samples, time.monotonic()))
        self.samples = samples
        # Providers accept 50–1000 ms. Always send <=100 ms, including buffered stop frames.
        frame_bytes = self.rate // 10 * 2
        if self.queue.qsize() + (len(pcm) + frame_bytes - 1) // frame_bytes > self.queue.maxsize:
            self.mark_gap()
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
                if self.gap_start is not None:
                    self.gap_end = max(self.gap_end, base_sample)
                self.session += 1
                session = self.session
                self.provider = self.factory()
                if hasattr(self.provider, 'speaker_labels'):
                    self.provider.speaker_labels = True
                await asyncio.wait_for(self.provider.connect(**({'agent_context': self.agent_context} if self.agent_context else {})), 10)
                await self.on_state('live', 'Live transcription reconnected. Missing audio will be repaired when recording stops.' if session > 1 else '')
                offset_ms = round(base_sample * 1000 / self.rate)
                connected_at = time.monotonic()
                first_partial = True

                async def receive():
                    nonlocal first_partial
                    async for event in self.provider.events():
                        self.annotate_final_timing(event, offset_ms)
                        if event.type in {STTEventType.ERROR, STTEventType.TERMINATED}:
                            if self.stopping and event.type == STTEventType.TERMINATED:
                                self.terminated = True
                                return
                            raise ConnectionError('Transcription stream ended')
                        if event.type == STTEventType.FINAL or event.type == STTEventType.PARTIAL and first_partial:
                            words = timed_words(event.raw.get('words'))
                            lag = max(0, round(self.samples * 1000 / self.rate) - offset_ms - words[-1]['end']) if words else None
                            logger.info('STT delivery: session=%s event=%s since_connect_ms=%s audio_behind_ms=%s queued_frames=%s',
                                session, event.type.value, round((time.monotonic() - connected_at) * 1000), lag, self.queue.qsize())
                            if event.type == STTEventType.PARTIAL:
                                first_partial = False
                        if event.type == STTEventType.PARTIAL:
                            self.pending_partial = bool(event.transcript)
                        elif event.type == STTEventType.FINAL:
                            self.pending_partial = False
                        await self.on_event(event, offset_ms, session)
                        if event.type == STTEventType.FINAL:
                            words = timed_words(event.raw.get('words'))
                            if words:
                                self.last_final_sample = max(self.last_final_sample, base_sample + round(words[-1]['end'] * self.rate / 1000))
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
                self.mark_gap()
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
        if self.stopping:
            return
        self.stopping = True
        if self.task:
            try:
                await asyncio.wait_for(self.queue.put(None), 2)
                await asyncio.wait_for(self.task, FINAL_TIMEOUT + 4)
            except (TimeoutError, asyncio.CancelledError):
                self.task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self.task

        if self.samples and (not self.terminated or self.pending_partial):
            self.mark_gap()
