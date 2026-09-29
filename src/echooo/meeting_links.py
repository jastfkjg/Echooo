"""Durable links from assistant speech to the original human transcript."""
from __future__ import annotations

from echooo import database as db
from echooo.meeting_findings import evidence_current, source_hash


def snapshot(row):
    return {k: row[k] for k in ('id', 'recording_id', 'speaker', 'content', 'start_ms', 'end_ms')} | {
        'source_hash': source_hash(row)}


def save_answer_triggers(r, event, rows):
    """Call in the same transaction that creates the answer event."""
    if event['audience'] != 'voice' or event['source_key'].startswith('intervention:'):
        return
    for row in rows:
        if row['meeting_id'] != event['meeting_id'] or row['owner_id'] != event['owner_id']:
            raise ValueError('Question evidence is outside this meeting')
        r.add(db.meeting_answer_triggers, meeting_id=event['meeting_id'], event_id=event['id'],
              utterance_id=row['id'], snapshot=snapshot(row))


def linked_passages(r, table, condition):
    rows = r.list(table, condition)
    result = []
    for link in rows:
        original = link['snapshot']
        current = r.get(db.utterances, link['utterance_id'])
        result.append({**original, 'changed': bool(current and source_hash(current) != original['source_hash']),
                       'utterance_id': link['utterance_id']})
    return result


def answer_triggers(r, event_id):
    return linked_passages(r, db.meeting_answer_triggers,
                           db.meeting_answer_triggers.c.event_id == event_id)


def sync_action_links(r, mid):
    """Associate an action only when its own evidence cites a linked human answer."""
    responses = r.list(db.meeting_intervention_responses,
                       db.meeting_intervention_responses.c.meeting_id == mid)
    findings = r.list(db.meeting_findings, db.meeting_findings.c.meeting_id == mid)
    current = {u['id']: u for u in r.list(db.utterances, db.utterances.c.meeting_id == mid)}
    by_source = {}
    for response in responses:
        source = current.get(response['utterance_id'])
        if source and source_hash(source) == response['snapshot']['source_hash']:
            by_source.setdefault(response['utterance_id'], set()).add(response['intervention_id'])
    wanted = set()
    for finding in findings:
        if finding['kind'] != 'action_item' or finding['status'] == 'rejected' or not evidence_current(finding, current):
            continue
        for evidence in finding['evidence']:
            wanted.update((pid, finding['id']) for pid in by_source.get(evidence['utterance_id'], ()))
    existing = {(link['intervention_id'], link['finding_id']): link for link in
                r.list(db.meeting_intervention_findings,
                       db.meeting_intervention_findings.c.meeting_id == mid)}
    for pair, link in existing.items():
        if pair not in wanted:
            r.remove(db.meeting_intervention_findings, link['id'])
    for pid, fid in wanted - existing.keys():
        r.add(db.meeting_intervention_findings, meeting_id=mid,
              intervention_id=pid, finding_id=fid)


def intervention_links(r, mid):
    sync_action_links(r, mid)
    responses = r.list(db.meeting_intervention_responses,
                       db.meeting_intervention_responses.c.meeting_id == mid)
    findings = {f['id']: f for f in r.list(db.meeting_findings,
                                             db.meeting_findings.c.meeting_id == mid)}
    result = {}
    for response in responses:
        original = response['snapshot']
        current = r.get(db.utterances, response['utterance_id'])
        result.setdefault(response['intervention_id'], {'responses': [], 'action_items': []})['responses'].append({
            **original, 'utterance_id': response['utterance_id'],
            'changed': bool(current and source_hash(current) != original['source_hash'])})
    for link in r.list(db.meeting_intervention_findings,
                       db.meeting_intervention_findings.c.meeting_id == mid):
        finding = findings.get(link['finding_id'])
        if finding:
            result.setdefault(link['intervention_id'], {'responses': [], 'action_items': []})['action_items'].append({
                'id': finding['id'], 'statement': finding['statement'], 'status': finding['status'],
                'owner': finding['details'].get('owner'),
                'deadline': finding['details'].get('deadline_text') or finding['details'].get('deadline'),
                'evidence_ids': [e['utterance_id'] for e in finding['evidence']]})
    return result
