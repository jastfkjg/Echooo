"""Read-only transcript projection of completed, public speech.

Keep assistant output outside human utterances: audio repair and memory extraction
must not relabel it or promote it to human evidence. Older replies have estimated
anchors; new replies use the active recording's sample clock.
"""
from __future__ import annotations

import time

from echooo import database as db


def mark_speech(agent, event, *, complete=False):
    with agent.store.scope(agent.who) as r:
        anchors = r.list(db.meeting_speech, db.meeting_speech.c.event_id == event['id'])
        if complete:
            if anchors:
                anchor = anchors[0]
                rec = r.get(db.recordings, anchor['recording_id']) if anchor['recording_id'] else None
                end = round(rec['samples'] * 1000 / rec['sample_rate']) if rec else anchor['timing']['start_ms']
                r.change(db.meeting_speech, anchor['id'], timing={**anchor['timing'],
                    'end_ms': max(anchor['timing']['start_ms'], end), 'completed_at': time.time()})
            return
        if anchors:
            return
        rid = getattr(agent, 'recording_id', None)
        rec = r.get(db.recordings, rid) if rid else None
        start = round(rec['samples'] * 1000 / rec['sample_rate']) if rec else 0
        r.add(db.meeting_speech, meeting_id=agent.mid, event_id=event['id'],
            recording_id=rec['id'] if rec else None, timing={'start_ms': start, 'end_ms': start,
                'had_recording': bool(rec), 'started_at': time.time()})


def speech_transcript(r, mid, recordings):
    records = {x['id']: x for x in recordings}
    anchors = {x['event_id']: x for x in r.list(db.meeting_speech, db.meeting_speech.c.meeting_id == mid)}
    sourced = {x['event_id'] for x in r.list(db.meeting_answer_sources,
        db.meeting_answer_sources.c.meeting_id == mid) if x['citations']}
    result = []
    for event in r.list(db.meeting_agent_events, db.meeting_agent_events.c.meeting_id == mid,
            db.meeting_agent_events.c.audience == 'voice', db.meeting_agent_events.c.status == 'spoken'):
        if not event['response']:
            continue
        anchor = anchors.get(event['id'])
        if anchor:
            timing, rid = anchor['timing'], anchor['recording_id']
            if timing.get('had_recording') and rid not in records:
                continue  # Deleting a recording must not resurrect its replies as notes.
            start, end, estimated = timing['start_ms'], timing['end_ms'], False
            created = timing['started_at']
        else:
            # Before speech anchors existed, source_key identified the recording that
            # supplied the question. Do not attach a deleted recording to a newer one.
            parts = event['source_key'].split(':')
            rid = parts[1] if len(parts) >= 4 and parts[0] == 'voice' else None
            if rid and rid not in records:
                continue
            rec = records.get(rid)
            if rec:
                duration = round(rec['samples'] * 1000 / rec['sample_rate'])
                start = min(duration, max(0, round((event['created_at'] - rec['created_at']) * 1000)))
            else:
                start = 0
            end, estimated, created = start, True, event['created_at']
        result.append({'id': 'assistant-' + event['id'], 'meeting_id': mid, 'recording_id': rid,
            'speaker': 'Echooo AI', 'content': event['response'], 'start_ms': start, 'end_ms': end,
            'created_at': created, 'assistant': True, 'event_id': event['id'],
            'has_sources': event['id'] in sourced, 'timing_estimated': estimated})
    return result
