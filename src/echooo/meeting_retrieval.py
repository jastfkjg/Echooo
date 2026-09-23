"""Bounded, owner/meeting-scoped lexical retrieval over durable transcript evidence.

Build a disposable inverted index in a worker thread only when the model requests
search. English words and CJK bigrams support multilingual query variants without
an embedding provider. Ranking retrieves candidates; it never classifies facts.
"""
from collections import Counter, defaultdict
import math
import re

from sqlalchemy import func, select

from echooo import database as db
from echooo.meeting_knowledge import digest

RECENT_CHARS = 3000
SEARCH_CHARS = 18000
CHUNK_CHARS = 1500
MAX_BLOCKS = 8
TURN_GAP_MS = 2000
WINDOW_GAP_MS = 10000


def terms(text):
    tokens = re.findall(r'[^\W_]+', text.casefold(), re.UNICODE)
    result = []
    for token in tokens:
        for part in re.findall(r'[\u3400-\u9fff]+|[^\u3400-\u9fff]+', token):
            if re.fullmatch(r'[\u3400-\u9fff]+', part):
                result.extend(part[i:i + 2] for i in range(max(1, len(part) - 1)))
            else:
                result.append(part)
    return result


def source_hash(row):
    return digest({k: row[k] for k in ('speaker', 'content', 'recording_id', 'start_ms', 'end_ms')})


def transcript_stamp(store, who, mid):
    with store.scope(who) as r:
        meeting = r.get(db.meetings, mid)
        if not meeting:
            raise ValueError('Meeting unavailable')
        count, latest = r.c.execute(select(func.count(), func.max(db.utterances.c.created_at)).where(
            db.utterances.c.owner_id == who, db.utterances.c.meeting_id == mid)).one()
        return (meeting['revision'], count, latest)


def ordered_query(who, mid):
    u, rec = db.utterances, db.recordings
    order = (func.coalesce(rec.c.created_at, u.c.created_at), u.c.start_ms, u.c.created_at, u.c.id)
    query = select(u).outerjoin(rec, u.c.recording_id == rec.c.id).where(
        u.c.owner_id == who, u.c.meeting_id == mid)
    return query, order


def passage(row, content=None, offset=0):
    return {**{k: row[k] for k in ('id', 'speaker', 'recording_id', 'start_ms', 'end_ms')},
        'content': row['content'] if content is None else content,
        'source_hash': source_hash(row), 'offset': offset,
        'truncated': content is not None and len(content) != len(row['content'])}


def utterance_units(passages):
    """Join temporally adjacent same-speaker ASR fragments before ranking.

    Unrecorded text has no reliable audio timeline and remains a separate turn.
    Original rows remain intact for citations and post-generation integrity checks.
    """
    units = []
    for p in passages:
        last = units[-1][-1] if units else None
        merge = (last and p['recording_id'] is not None and
            p['recording_id'] == last['recording_id'] and p['speaker'] == last['speaker'] and
            -500 <= p['start_ms'] - last['end_ms'] <= TURN_GAP_MS and
            p['end_ms'] - units[-1][0]['start_ms'] <= 30000 and
            sum(len(x['content']) for x in units[-1]) + len(p['content']) <= CHUNK_CHARS and
            not p['truncated'] and not last['truncated'])
        if merge:
            units[-1].append(p)
        else:
            units.append([p])
    return units


def recent_passages(store, who, mid):
    query, order = ordered_query(who, mid)
    with store.scope(who) as r:
        rows = list(r.c.execute(query.order_by(*(c.desc() for c in order)).limit(60)).mappings())
    units = utterance_units([passage(row, row['content'][:2000]) for row in reversed(rows)])
    selected, size = [], 0
    for unit in reversed(units):
        length = sum(len(p['content']) for p in unit)
        if len(selected) >= 6 or size + length > RECENT_CHARS:
            break
        selected.append(unit)
        size += length
    return [p for unit in reversed(selected) for p in unit]


def adjacent(left, right):
    a, b = left[-1], right[0]
    return (a['recording_id'] == b['recording_id'] and
        (a['recording_id'] is None or -500 <= b['start_ms'] - a['end_ms'] <= WINDOW_GAP_MS))


def search_meeting_evidence(store, who, mid, queries, cancelled):
    if (not isinstance(queries, list) or not 1 <= len(queries) <= 4 or
            any(not isinstance(q, str) or not q.strip() or len(q) > 180 for q in queries)):
        raise ValueError('Invalid meeting search queries')
    query_terms = set(terms(' '.join(queries)))
    if not query_terms:
        raise ValueError('Empty meeting search terms')
    query, order = ordered_query(who, mid)
    passages, postings = [], defaultdict(list)
    with store.scope(who) as r:
        for row in r.c.execute(query.order_by(*order).execution_options(yield_per=100)).mappings():
            if cancelled.is_set():
                raise TimeoutError('Meeting search cancelled')
            if len(row['content']) <= CHUNK_CHARS:
                passages.append(passage(row))
            else:
                # Long turns need bounded overlapping excerpts; tiny ASR rows do not.
                for start in range(0, len(row['content']), CHUNK_CHARS - 200):
                    passages.append(passage(row, row['content'][start:start + CHUNK_CHARS], start))
    units = utterance_units(passages)
    chunks = []
    for index, unit in enumerate(units):
        if cancelled.is_set():
            raise TimeoutError('Meeting search cancelled')
        counts = Counter(terms(' '.join(p['content'] for p in unit)))
        chunks.append((unit, sum(counts.values())))
        for token in query_terms & counts.keys():
            postings[token].append((index, counts[token]))
    if not chunks:
        return {'passages': [], 'matched_chunks': 0, 'searched_chunks': 0, 'truncated': False}
    average = max(1, sum(length for _, length in chunks) / len(chunks))
    scores = defaultdict(float)
    for matches in postings.values():
        weight = math.log(1 + (len(chunks) - len(matches) + .5) / (len(matches) + .5))
        for index, frequency in matches:
            if cancelled.is_set():
                raise TimeoutError('Meeting search cancelled')
            scores[index] += weight * frequency * 2.2 / (frequency + 1.2 * (.25 + .75 * chunks[index][1] / average))
    ranked = sorted(scores, key=lambda i: (scores[i], i), reverse=True)
    # Six relevance-ranked windows plus two recent matching windows retain revisions.
    hits = list(dict.fromkeys(ranked[:6] + sorted(scores, reverse=True)[:2]))
    selected, size, blocks = {}, 0, 0
    for index in hits:
        if index in selected or blocks >= MAX_BLOCKS:
            continue
        window = [index]
        if index > 0 and adjacent(units[index - 1], units[index]):
            window.insert(0, index - 1)
        if index + 1 < len(units) and adjacent(units[index], units[index + 1]):
            window.append(index + 1)
        window = [i for i in window if i not in selected]
        length = sum(len(p['content']) for i in window for p in units[i])
        # Keep each selected Q&A window whole rather than clipping its answer.
        if size + length > SEARCH_CHARS:
            continue
        for i in window:
            selected[i] = blocks
        blocks += 1
        size += length
    return {'passages': [{**p, 'block': selected[i], 'score': round(scores.get(i, 0), 6),
            'selection': 'match' if i in hits else 'adjacent'}
            for i in sorted(selected, key=lambda i: (selected[i], i)) for p in units[i]],
        'matched_chunks': len(scores), 'searched_chunks': len(chunks),
        'truncated': len(selected.keys() & scores.keys()) < len(scores)}
