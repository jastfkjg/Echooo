"""Meeting-scoped live delivery and durable provenance for STT corrections."""
from __future__ import annotations

import asyncio
import math
import re
import time
from collections import defaultdict

from echooo import database as db
from echooo.meeting_debug import record
from echooo.models import STTEventType


class TranscriptFeed:
    """Slow viewers never block audio. Overflow/reconnect reloads durable state."""
    def __init__(self):
        self.listeners = defaultdict(set)
        self.drafts = {}
        self.on_utterance = None

    def subscribe(self, who, mid):
        queue = asyncio.Queue(maxsize=64)
        self.listeners[who, mid].add(queue)
        return queue

    def unsubscribe(self, who, mid, queue):
        listeners = self.listeners.get((who, mid), set())
        listeners.discard(queue)
        if not listeners:
            self.listeners.pop((who, mid), None)

    def publish(self, who, mid, event):
        if event['type'] == 'utterance' and self.on_utterance:
            self.on_utterance(who, mid, event['utterance'])
        if event['type'] in {'partial', 'utterance'}:
            item = event.get('utterance', event)
            record(who, mid, 'transcript', recording_id=item.get('recording_id'),
                kind=event['type'], text=item.get('content', item.get('text', ''))[:6000],
                source_id=item.get('id'), start_ms=item.get('start_ms'), end_ms=item.get('end_ms'))
        key = (who, mid)
        event = {**event, 'emitted_at': time.time()}
        if event['type'] == 'partial':
            if event.get('text'):
                self.drafts[key] = event
            else:
                self.drafts.pop(key, None)
        for queue in self.listeners.get(key, ()):
            if queue.full():
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait({'type': 'resync'})
            queue.put_nowait(event)


def label_name(label, rid, session=1):
    if label is None or str(label).upper() in {'', 'PENDING', 'UNKNOWN'}:
        return 'Unknown speaker'
    suffix = f' (connection {session})' if session > 1 else ''
    return f'Speaker {str(label)[:20]}{suffix} · {rid[:4]}'


def join_words(words):
    """Respect CJK text and punctuation without concatenating Latin words."""
    text = ' '.join(w['text'].strip() for w in words if w.get('text', '').strip())
    text = re.sub(r'\s+([，。！？、；：,.!?;:])', r'\1', text)
    return re.sub(r'(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])', '', text)


def timed_words(raw, offset=0):
    words = []
    for w in raw or []:
        if not isinstance(w, dict) or not isinstance(w.get('text'), str):
            continue
        a, b = w.get('start'), w.get('end')
        if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in (a, b)) or b <= a:
            continue
        words.append({**w, 'start': round(a) + offset, 'end': round(b) + offset})
    return words


def segments(words, fallback):
    groups = []
    for w in words:
        label = w.get('speaker', fallback)
        # PENDING is uncertainty, never a new person or an inferred neighbour.
        if label is None or str(label).upper() in {'PENDING', 'UNKNOWN', ''}:
            label = None
        if groups and groups[-1][0] == label:
            groups[-1][1].append(w)
        else:
            groups.append((label, [w]))
    return groups


def invalidate(r, mid):
    meeting = r.get(db.meetings, mid)
    r.change(db.meetings, mid, revision=meeting['revision'] + 1)
    for section in r.list(db.meeting_sections, db.meeting_sections.c.meeting_id == mid):
        r.change(db.meeting_sections, section['id'], status='stale')


def remember(r, u, **state):
    return r.add(db.utterance_sources, meeting_id=u['meeting_id'], recording_id=u['recording_id'],
        utterance_id=u['id'], state={**state, 'content': u['content'], 'speaker': u['speaker']})


class TranscriptWriter:
    def __init__(self, store, who, mid, rid, feed):
        self.store, self.who, self.mid, self.rid, self.feed = store, who, mid, rid, feed
        self.last_end = 0
        self.seen = set()

    def clear(self):
        self.feed.publish(self.who, self.mid, {'type': 'partial', 'text': '', 'recording_id': self.rid})

    def consume(self, event, offset, session, duration):
        raw = event.raw
        if event.type == STTEventType.PARTIAL:
            self.feed.publish(self.who, self.mid, {'type': 'partial', 'text': event.transcript,
                'speaker': label_name(raw.get('speaker_label'), self.rid, session), 'recording_id': self.rid})
            return []
        if event.type == STTEventType.SPEAKER_REVISION:
            return self.revise(raw.get('revisions') or [], session)
        if event.type != STTEventType.FINAL or not event.transcript:
            return []
        turn = raw.get('turn_order')
        if turn is not None and (session, turn) in self.seen:
            return []
        words = timed_words(raw.get('words'), offset)
        anchors = words or timed_words([{**w, 'text': ''} for w in raw.get('words', []) if isinstance(w, dict)], offset)
        groups = segments(words, raw.get('speaker_label'))
        if not groups:
            groups = [(raw.get('speaker_label'), [])]
        rows = []
        with self.store.scope(self.who) as r:
            if not r.get(db.recordings, self.rid):
                return []
            for label, part in groups:
                bounds = part or anchors
                start = min(duration, max(0, bounds[0]['start'])) if bounds else min(duration, max(self.last_end, offset))
                end = min(duration, bounds[-1]['end']) if bounds else duration
                content = event.transcript if len(groups) == 1 else join_words(part)
                u = r.add(db.utterances, meeting_id=self.mid, recording_id=self.rid,
                    speaker=label_name(label, self.rid, session), content=content[:6000],
                    start_ms=start, end_ms=max(start, end))
                remember(r, u, session=session, turn=turn, offset=offset, words=part)
                rows.append(u)
        self.last_end = max(u['end_ms'] for u in rows)
        if turn is not None:
            self.seen.add((session, turn))
        self.clear()
        self.deliver(rows)
        return rows

    def deliver(self, rows):
        for u in rows:
            self.feed.publish(self.who, self.mid, {'type': 'utterance', 'utterance': u})

    def revise(self, revisions, session):
        changed = []
        with self.store.scope(self.who) as r:
            sources = r.list(db.utterance_sources, db.utterance_sources.c.recording_id == self.rid)
            for revision in revisions:
                if not isinstance(revision, dict) or revision.get('turn_order') is None:
                    continue
                for source in sources:
                    state = source['state']
                    if state.get('session') != session or state.get('turn') != revision['turn_order']:
                        continue
                    u = r.get(db.utterances, source['utterance_id'])
                    if not u or state.get('speaker_edited') or u['speaker'] != state['speaker']:
                        continue
                    words = timed_words(revision.get('words'), state.get('offset', 0))
                    part = [w for w in words if u['start_ms'] <= (w['start'] + w['end']) / 2 < u['end_ms']]
                    groups = segments(part, revision.get('speaker_label'))
                    if not groups:
                        groups = [(revision.get('speaker_label'), [])]
                    if len(groups) > 1 and (state.get('content_edited') or u['content'] != state['content']):
                        # Preserve human text and its anchors; mixed attribution stays uncertain.
                        groups = [(None, part)]
                    for index, (label, group) in enumerate(groups):
                        values = {'speaker': label_name(label, self.rid, session)}
                        if len(groups) > 1:
                            values.update(content=join_words(group), start_ms=group[0]['start'], end_ms=group[-1]['end'])
                        if index == 0:
                            if any(u[k] != v for k, v in values.items()):
                                r.change(db.utterances, u['id'], **values)
                                u = {**u, **values}
                                changed.append(u)
                            r.change(db.utterance_sources, source['id'], state={**state,
                                'speaker': u['speaker'], 'content': state['content'] if state.get('content_edited') else u['content'],
                                'words': group or state.get('words', [])})
                        else:
                            extra = r.add(db.utterances, meeting_id=self.mid, recording_id=self.rid, **values)
                            remember(r, extra, session=session, turn=state['turn'], offset=state['offset'], words=group)
                            changed.append(extra)
            if changed:
                invalidate(r, self.mid)
        self.deliver(changed)
        if changed:
            self.feed.publish(self.who, self.mid, {'type': 'resync'})
        return changed
