import asyncio
import json
import socket

import httpx
import pytest
import uvicorn

from echooo import database as db
from echooo.meeting_live import TranscriptFeed, TranscriptWriter, join_words
from echooo.meeting_transcription import reconcile_passages
from echooo.models import STTEvent, STTEventType
from test_product import app, client


def setup_writer(client, app):
    meeting = client.post('/api/meetings', json={'title': 'Live captions'}).json()
    with app.state.store.scope(meeting['owner_id']) as r:
        rec = r.add(db.recordings, meeting_id=meeting['id'], sample_rate=16000, samples=160000)
    feed = app.state.meeting_transcriptions.feed
    return meeting, rec, TranscriptWriter(app.state.store, meeting['owner_id'], meeting['id'], rec['id'], feed)


def final(label='PENDING', turn=0, words=None, text='你好 Echooo。'):
    return STTEvent(type=STTEventType.FINAL, transcript=text,
        raw={'turn_order': turn, 'speaker_label': label, 'words': words or [
            {'text': '你好', 'start': 0, 'end': 600}, {'text': 'Echooo。', 'start': 600, 'end': 1500}]})


def test_word_speakers_split_turn_and_revision_preserves_ids_and_edits(client, app):
    m, rec, writer = setup_writer(client, app)
    words = [{'text': '你好', 'start': 0, 'end': 600, 'speaker': 'A'},
        {'text': 'Echooo。', 'start': 600, 'end': 1500, 'speaker': 'B'}]
    rows = writer.consume(final('A', words=words), 0, 1, 2000)
    assert len(rows) == 2
    assert rows[0]['speaker'].startswith('Speaker A')
    assert rows[1]['speaker'].startswith('Speaker B')
    assert writer.consume(final('A', words=words), 0, 1, 2000) == []
    # Speaker A in another connection is not automatically the same person.
    later = writer.consume(final('A'), 2000, 2, 4000)[0]
    assert 'connection 2' in later['speaker']
    path = f'/api/meetings/{m["id"]}'
    response = client.patch(path + '/utterances/' + rows[0]['id'], json={'speaker': 'Alice', 'content': '人工纠正'})
    assert response.status_code == 200
    revision = STTEvent(type=STTEventType.SPEAKER_REVISION, raw={'revisions': [
        {'turn_order': 0, 'speaker_label': 'C', 'words': [{**w, 'speaker': 'C'} for w in words]}]})
    # A new writer can apply the corrections after reconstructing state from storage.
    resumed = TranscriptWriter(app.state.store, m['owner_id'], m['id'], rec['id'], writer.feed)
    changed = resumed.consume(revision, 0, 1, 4000)
    assert [u['id'] for u in changed] == [rows[1]['id']]
    assert changed[0]['speaker'].startswith('Speaker C')
    records = {u['id']: u for u in client.get(path).json()['utterances']}
    assert records[rows[0]['id']]['speaker'] == 'Alice'
    assert records[rows[0]['id']]['content'] == '人工纠正'
    assert records[later['id']]['speaker'] == later['speaker']
    assert resumed.consume(revision, 0, 1, 4000) == []


def test_revision_can_split_a_previously_single_speaker_turn(client, app):
    m, rec, writer = setup_writer(client, app)
    original = writer.consume(final('A'), 0, 1, 2000)[0]
    revision = [{'turn_order': 0, 'speaker_label': 'A', 'words': [
        {'text': '你好', 'start': 0, 'end': 600, 'speaker': 'A'},
        {'text': 'Echooo。', 'start': 600, 'end': 1500, 'speaker': 'B'}]}]
    changed = writer.revise(revision, 1)
    assert len(changed) == 2
    assert changed[0]['id'] == original['id']
    assert changed[0]['content'] == '你好'
    assert changed[1]['content'] == 'Echooo。'
    assert writer.revise(revision, 1) == []


def test_batch_repairs_text_and_unifies_sessions_without_overwriting_human_fields(client, app):
    m, rec, writer = setup_writer(client, app)
    first = writer.consume(final(text='你好 Echo。'), 0, 1, 2000)[0]
    second = writer.consume(final('C', text='你好 Eco。'), 2000, 2, 4000)[0]
    path = f'/api/meetings/{m["id"]}/utterances/{second["id"]}'
    client.patch(path, json={'speaker': second['speaker'], 'content': '人工纠正'})
    result = {'utterances': [{'speaker': 'A', 'words': [
        {'text': '你好', 'start': 0, 'end': 600}, {'text': 'Echooo。', 'start': 600, 'end': 1500},
        {'text': '你好', 'start': 2000, 'end': 2600}, {'text': 'Echooo。', 'start': 2600, 'end': 3500}]}]}
    with app.state.store.scope(m['owner_id']) as r:
        existing = r.list(db.utterances)
        changed = reconcile_passages(r, result, existing, rec['id'])
        assert len(changed) == 2
        assert existing[0]['id'] == first['id']
        assert existing[0]['content'] == '你好 Echooo。'
        assert existing[1]['content'] == '人工纠正'
        assert existing[0]['speaker'] == existing[1]['speaker']
        assert reconcile_passages(r, result, existing, rec['id']) == []
    assert join_words([{'text': '你'}, {'text': '好'}, {'text': '，'}, {'text': 'Echooo'}]) == '你好， Echooo'


def test_feed_is_scoped_bounded_and_draft_is_not_persisted(client, app):
    m, rec, writer = setup_writer(client, app)
    feed = writer.feed
    queue = feed.subscribe(m['owner_id'], m['id'])
    other_owner = feed.subscribe('other-owner', m['id'])
    other_meeting = feed.subscribe(m['owner_id'], 'other-meeting')
    for i in range(100):
        writer.consume(STTEvent(type=STTEventType.PARTIAL, transcript=f'临时 {i}'), 0, 1, 1000)
    assert queue.qsize() <= 64 and queue.get_nowait()['type'] == 'resync'
    assert other_owner.empty() and other_meeting.empty()
    with app.state.store.scope(m['owner_id']) as r:
        assert not r.list(db.utterances)
    writer.clear()
    assert (m['owner_id'], m['id']) not in feed.drafts
    feed.unsubscribe(m['owner_id'], m['id'], queue)
    assert (m['owner_id'], m['id']) not in feed.listeners


@pytest.mark.asyncio
async def test_sse_delivers_partial_before_final_and_cleans_up(app):
    """Real HTTP streaming: ASGI buffered clients cannot detect proxy-like buffering."""
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', lifespan='on'))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(.01)
        async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{sock.getsockname()[1]}', timeout=2) as client:
            assert (await client.post('/api/auth/setup', json={'name': 'owner', 'password': 'test-password-123'})).status_code == 200
            m = (await client.post('/api/meetings', json={'title': 'SSE'})).json()
            path = f'/api/meetings/{m["id"]}/events'
            async with httpx.AsyncClient(base_url=str(client.base_url)) as guest:
                assert (await guest.get(path)).status_code == 401
            feed = app.state.meeting_transcriptions.feed
            async with client.stream('GET', path) as response:
                assert response.headers['x-accel-buffering'] == 'no'
                lines = response.aiter_lines()
                assert json.loads((await anext(lines))[6:])['type'] == 'resync'
                feed.publish(m['owner_id'], m['id'], {'type': 'partial', 'text': '正在讲话', 'recording_id': 'r'})
                async def next_event():
                    async for line in lines:
                        if line.startswith('data: '):
                            return json.loads(line[6:])
                event = await asyncio.wait_for(next_event(), .5)
                assert event['text'] == '正在讲话'
                # Revoking a credential while the generator is waiting must not
                # allow the next queued transcript to leak before revalidation.
                app.state.auth.revoke(client.cookies.get('echooo_owner'))
                feed.publish(m['owner_id'], m['id'], {'type': 'partial', 'text': 'must not be delivered'})
                assert await asyncio.wait_for(next_event(), .5) is None
            for _ in range(100):
                if not feed.listeners:
                    break
                await asyncio.sleep(.01)
            assert not feed.listeners
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 5)
        sock.close()
