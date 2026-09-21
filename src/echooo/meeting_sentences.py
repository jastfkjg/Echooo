"""Chronological, versioned speech units and lossless links to raw evidence."""
import re

from echooo.meeting_findings import digest, source_hash


def sentences(rows, recording_order=None):
    order = recording_order or {}
    ordered = sorted(rows, key=lambda u: (order.get(u['recording_id'], u['created_at'] if not u['recording_id'] else 0),
        u['recording_id'] or '', u['start_ms'], u['end_ms'], u['id']))
    groups, current = [], []
    for row in ordered:
        if current:
            last = current[-1]
            boundary = (row['recording_id'] != last['recording_id'] or row['speaker'] != last['speaker']
                or not row['recording_id'] or row['start_ms'] - last['end_ms'] > 12000
                or re.search(r'[.!?。！？][\"”’\s]*$', last['content']))
            if boundary:
                groups.append(current)
                current = []
        current.append(row)
    if current:
        groups.append(current)
    result = []
    for group in groups:
        content, spans = '', []
        for row in group:
            text = row['content'].strip()
            separator = '' if not content or re.search(r'[\u3400-\u9fff]$', content) and re.match(r'[\u3400-\u9fff]', text) else ' '
            content += separator
            start = len(content)
            content += text
            spans.append((start, len(content), row))
        version = digest([(u['id'], source_hash(u)) for u in group])
        result.append({'id': 'speech-' + group[0]['id'] + '-' + version[:12], 'version': version,
            'recording_id': group[0]['recording_id'], 'speaker': group[0]['speaker'], 'content': content,
            'start_ms': group[0]['start_ms'], 'end_ms': group[-1]['end_ms'], 'sources': group, 'spans': spans,
            'complete': bool(not group[0]['recording_id'] or re.search(r'[.!?。！？][\"”’\s]*$', content))})
    return result


def public_sentence(s):
    return {k: s[k] for k in ('id', 'version', 'recording_id', 'speaker', 'content', 'start_ms', 'end_ms')}


def expand_evidence(evidence, units):
    """Validate quotes on the merged unit, then map only overlapping original text."""
    by_id = {s['id']: s for s in units}
    result = []
    if not isinstance(evidence, list) or not evidence:
        raise ValueError('Missing sentence evidence')
    for e in evidence:
        if not isinstance(e, dict):
            raise ValueError('Invalid sentence evidence')
        unit, quote = by_id.get(e.get('utterance_id')), e.get('quote')
        if not unit or not isinstance(quote, str) or not quote.strip() or quote not in unit['content']:
            raise ValueError('Unsupported sentence evidence')
        start = unit['content'].index(quote)
        end = start + len(quote)
        for a, b, row in unit['spans']:
            if a < end and b > start:
                part = unit['content'][max(a, start):min(b, end)].strip()
                if part:
                    item = {'utterance_id': row['id'], 'quote': part}
                    if item not in result:
                        result.append(item)
    return result
