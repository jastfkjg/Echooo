"""Bounded process-local diagnostics; never writes on the audio hot path."""
from collections import OrderedDict, deque
from copy import deepcopy
import time

_buffers = OrderedDict()
LIMIT = 500
MEETINGS = 32


def record(who, mid, stage, *, recording_id=None, event_id=None, **data):
    key = (who, mid)
    if key not in _buffers:
        _buffers[key] = deque(maxlen=LIMIT)
    _buffers.move_to_end(key)
    while len(_buffers) > MEETINGS:
        _buffers.popitem(last=False)
    _buffers[key].append({'at': time.time(), 'stage': stage,
        'recording_id': recording_id, 'event_id': event_id, 'data': deepcopy(data)})


def snapshot(who, mid):
    return list(_buffers.get((who, mid), ()))


def clear(who, mid):
    _buffers.pop((who, mid), None)


def agent_record(agent, stage, **data):
    event = getattr(agent, 'current_event', None)
    record(agent.who, agent.mid, stage, recording_id=getattr(agent, 'recording_id', None),
        event_id=event['id'] if event else None, **data)
