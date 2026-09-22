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

RECENT_CHARS = 12000
SEARCH_CHARS = 18000
CHUNK_CHARS = 1500


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


def recent_passages(store, who, mid):
    query, order = ordered_query(who, mid)
    result, size = [], 0
    with store.scope(who) as r:
        for row in r.c.execute(query.order_by(*(c.desc() for c in order)).limit(60)).mappings():
            text = row['content'][:2000]
            if size + len(text) > RECENT_CHARS:
                break
            result.append(passage(row, text))
            size += len(text)
    return list(reversed(result))


def search_meeting_evidence(store, who, mid, queries, cancelled):
    if (not isinstance(queries, list) or not 1 <= len(queries) <= 4 or
            any(not isinstance(q, str) or not q.strip() or len(q) > 180 for q in queries)):
        raise ValueError('Invalid meeting search queries')
    query_terms = set(terms(' '.join(queries)))
    if not query_terms:
        raise ValueError('Empty meeting search terms')
    query, order = ordered_query(who, mid)
    chunks, postings = [], defaultdict(list)
    with store.scope(who) as r:
        for row in r.c.execute(query.order_by(*order).execution_options(yield_per=100)).mappings():
            for start in range(0, len(row['content']), CHUNK_CHARS - 200):
                if cancelled.is_set():
                    raise TimeoutError('Meeting search cancelled')
                text = row['content'][start:start + CHUNK_CHARS]
                counts = Counter(terms(text))
                index = len(chunks)
                chunks.append((passage(row, text, start), sum(counts.values())))
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
    # Reserve candidates for later matching discussion, including decision revisions.
    hits = list(dict.fromkeys(ranked[:6] + sorted(scores, reverse=True)[:4]))
    selected, size = set(), 0
    for index in hits:
        item = chunks[index][0]
        if size + len(item['content']) <= SEARCH_CHARS:
            selected.add(index)
            size += len(item['content'])
    for index in hits:
        for neighbor in (index - 1, index + 1):
            if (0 <= neighbor < len(chunks) and neighbor not in selected and
                    chunks[neighbor][0]['recording_id'] == chunks[index][0]['recording_id']):
                item = chunks[neighbor][0]
                if size + len(item['content']) <= SEARCH_CHARS:
                    selected.add(neighbor)
                    size += len(item['content'])
    return {'passages': [chunks[i][0] for i in sorted(selected)],
        'matched_chunks': len(scores), 'searched_chunks': len(chunks),
        'truncated': len(selected & scores.keys()) < len(scores)}
