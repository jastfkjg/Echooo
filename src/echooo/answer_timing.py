"""Durable answer timings. Durations never subtract clocks from different hosts."""
import math
import time

from echooo import database as db
from echooo.meeting_live import timed_words


def stt_anchor(event, recording_id, offset_ms, audio_ms):
    words = timed_words(event.raw.get('words'), offset_ms)
    return {'received': event.raw.get('_received_monotonic', time.monotonic()),
        'recording_id': recording_id, 'question_end_ms': words[-1]['end'] if words else None,
        'stt_audio_lag_ms': max(0, audio_ms - words[-1]['end']) if words else None,
        'stt_finalization_ms': event.raw.get('_stt_finalization_ms'),
        'stt_frame_ms': event.raw.get('_stt_frame_ms')}


def begin(agent, event, anchor=None):
    anchor = anchor or {}
    event['_timing_origin'] = anchor.get('received', time.monotonic())
    timing = {'version': 1, 'clock': 'server_monotonic', 'stages': {},
        'input': {k: v for k, v in anchor.items() if k != 'received'}}
    if anchor:
        timing['stages']['stt_final_received'] = 0
    with agent.store.scope(agent.who) as r:
        r.add(db.meeting_answer_traces, meeting_id=agent.mid, event_id=event['id'],
            detail={'version': 1, 'calls': [], 'timing': timing})
    mark(agent, event, 'queued')


def mark(agent, event, stage, **values):
    if '_timing_origin' not in event:
        return
    with agent.store.scope(agent.who) as r:
        rows = r.list(db.meeting_answer_traces, db.meeting_answer_traces.c.event_id == event['id'])
        if not rows:
            return  # A deleted meeting must not be resurrected by a late callback.
        detail = rows[0]['detail']
        timing = detail['timing']
        timing['stages'].setdefault(stage, round((time.monotonic() - event['_timing_origin']) * 1000))
        timing.update(values)
        r.change(db.meeting_answer_traces, rows[0]['id'], detail=detail)


def client_report(agent, event, values):
    # Only accept bounded durations, never client wall-clock timestamps or text.
    allowed = ('offer_to_first_audio_ms', 'question_to_first_audio_ms', 'output_latency_ms')
    clean = {k: round(v, 2) for k, v in values.items() if k in allowed and
        isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and 0 <= v <= 300000}
    mark(agent, event, 'first_audio_report_received', client={
        'clock': 'browser_audio_context', 'measurement': 'first_output_frame', **clean})
