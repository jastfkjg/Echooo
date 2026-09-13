import asyncio
import time

import pytest

from echooo.models import STTEvent, STTEventType
from test_meeting_agent import agent, app, client, Socket


def turn(text, speaker='A', partial=False):
    return STTEvent(STTEventType.PARTIAL if partial else STTEventType.FINAL, text,
        raw={'speaker_label': speaker})


@pytest.fixture
def decisions(agent):
    calls = []
    actions = []
    async def classify(system, context, **kwargs):
        calls.append(context)
        return {'action': actions.pop(0) if actions else 'respond'}
    agent.intelligence.json_call = classify
    return calls, actions


async def settle(agent):
    if agent.decision_task:
        await agent.decision_task


async def test_model_accepts_declarative_followup_and_declines_human_discussion(agent, decisions):
    calls, actions = decisions
    await agent.transcript(turn('Echooo，总结一下'), 'rec:1:1'); agent.queue.get_nowait()
    await agent.transcript(turn('用中英文各一句'), 'rec:1:2'); await settle(agent)
    assert agent.queue.get_nowait()['request'] == '用中英文各一句'
    assert calls[-1]['speaker_relation'] == 'same'
    actions.append('listen')
    await agent.transcript(turn('今天中午我们一起去吃饭'), 'rec:1:3'); await settle(agent)
    assert agent.queue.empty() and agent.conversation_active()
    actions.append('end')
    await agent.transcript(turn('那最大的风险是什么？', 'B'), 'rec:1:4'); await settle(agent)
    assert agent.queue.empty() and not agent.conversation_active()
    assert calls[-1]['speaker_relation'] == 'different'


async def test_window_expires_and_explicit_exit_disengages(agent, decisions):
    calls, _ = decisions
    await agent.transcript(turn('Echooo，你好'), 'rec:1:1'); agent.queue.get_nowait()
    agent.conversation_until = time.monotonic() - 1
    await agent.transcript(turn('继续说'), 'rec:1:2'); await settle(agent)
    assert agent.queue.empty() and not calls
    await agent.transcript(turn('Echooo，你好'), 'rec:1:3'); agent.queue.get_nowait()
    await agent.transcript(turn('谢谢，你先听着'), 'rec:1:4')
    await agent.transcript(turn('继续说'), 'rec:1:5'); await settle(agent)
    assert agent.queue.empty() and not agent.conversation_active() and not calls


async def test_unknown_speaker_uses_context_instead_of_losing_followup(agent, decisions):
    calls, _ = decisions
    await agent.transcript(turn('Echooo，你好', 'PENDING'), 'rec:1:1'); agent.queue.get_nowait()
    await agent.transcript(turn('英文版本也来一份', 'PENDING'), 'rec:1:2'); await settle(agent)
    assert agent.queue.get_nowait()['request'] == '英文版本也来一份'
    assert calls[-1]['speaker_relation'] == 'unknown'


async def test_zoom_activity_and_overlap_are_hints_to_model(agent, decisions):
    calls, actions = decisions
    def activity(pid):
        agent.speaker_event({'participant_uuid': pid, 'active': True, 'is_self': False, 'timestamp_ms': time.time()*1000})
    activity('1024')
    await agent.transcript(turn('Echooo，你好', 'PENDING'), 'rec:1:1'); agent.queue.get_nowait()
    activity('1024')
    await agent.transcript(turn('那你怎么看？', 'PENDING'), 'rec:1:2'); await settle(agent)
    assert agent.queue.get_nowait()['sender'] == 'participant:1024'
    activity('2048'); actions.append('listen')
    await agent.transcript(turn('继续说', 'PENDING'), 'rec:1:3'); await settle(agent)
    assert agent.queue.empty() and calls[-1]['speaker_relation'] == 'unknown'


async def test_noise_and_short_acknowledgements_do_not_pause_or_cancel(agent):
    socket = agent.manager.sockets[agent.cid] = Socket(agent)
    await agent.playback.start(24000)
    agent.phase = 'speaking'
    for event in [STTEvent(STTEventType.SPEECH_STARTED), turn('嗯', partial=True), turn('对'), turn('okay')]:
        await agent.transcript(event, 'rec:1:1')
    assert agent.phase == 'speaking'
    assert [p['data']['action'] for p in socket.packets] == ['start']
    await agent.stop(); agent.manager.sockets.pop(agent.cid)


async def test_short_final_remark_does_not_cancel_before_model_decides(agent, decisions):
    _, actions = decisions
    actions.append('listen')
    socket = agent.manager.sockets[agent.cid] = Socket(agent)
    await agent.playback.start(24000)
    agent.phase = 'speaking'
    agent.conversation_until = time.monotonic() + 15
    await agent.transcript(turn('这个'), 'rec:1:1'); await settle(agent)
    assert agent.phase == 'speaking' and agent.queue.empty()
    assert [p['data']['action'] for p in socket.packets] == ['start']
    await agent.stop(); agent.manager.sockets.pop(agent.cid)


async def test_tentative_fragment_resumes_without_losing_queued_audio(agent):
    socket = agent.manager.sockets[agent.cid] = Socket(agent)
    await agent.playback.start(24000); agent.phase = 'speaking'
    await agent.transcript(turn('这个', partial=True), 'rec:1:1')
    assert agent.phase == 'paused'
    await agent.barge_task
    assert agent.phase == 'speaking'
    assert [p['data']['action'] for p in socket.packets] == ['start', 'pause', 'resume']
    await agent.stop(); agent.manager.sockets.pop(agent.cid)


async def test_sustained_interim_speech_yields_but_single_hypothesis_does_not(agent):
    socket = agent.manager.sockets[agent.cid] = Socket(agent)
    await agent.playback.start(24000); agent.phase = 'speaking'
    await agent.transcript(turn('我想说一下', partial=True), 'rec:1:1')
    await asyncio.sleep(.32)
    await agent.transcript(turn('我想说一下我们这边的情况', partial=True), 'rec:1:1')
    await agent.barge_task
    assert socket.packets[-1]['data']['action'] == 'stop'
    assert not agent.conversation_active()
    agent.manager.sockets.pop(agent.cid)


async def test_explicit_stop_is_immediate_even_if_it_matches_previous_reply(agent):
    socket = agent.manager.sockets[agent.cid] = Socket(agent)
    await agent.playback.start(24000); agent.phase = 'speaking'
    agent.last_spoken = '等一下'; agent.echo_until = time.monotonic()+10
    await agent.transcript(turn('等一下', partial=True), 'rec:1:1')
    assert socket.packets[-1]['data']['action'] == 'stop' and agent.barge_task is None
    agent.manager.sockets.pop(agent.cid)


async def test_new_recording_labels_are_distinct_hints_not_hard_gates(agent, decisions):
    calls, _ = decisions
    await agent.transcript(turn('Echooo，你好'), 'rec:1:1'); agent.queue.get_nowait()
    await agent.transcript(turn('继续说'), 'new-recording:1:2'); await settle(agent)
    assert calls[-1]['speaker_relation'] == 'different'
    assert agent.queue.get_nowait()['request'] == '继续说'


async def test_stop_invalidates_delayed_model_decision(agent):
    entered, release = asyncio.Event(), asyncio.Event()
    async def slow(*args, **kwargs):
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            pass  # Even an uncancellable result must be discarded.
        return {'action': 'respond'}
    agent.intelligence.json_call = slow
    await agent.transcript(turn('Echooo，你好'), 'rec:1:1'); agent.queue.get_nowait()
    await agent.transcript(turn('英文版本'), 'rec:1:2')
    pending = agent.decision_task
    await entered.wait()
    await agent.stop()
    release.set(); await pending
    assert agent.queue.empty() and not agent.conversation_active()


async def test_turn_model_failure_never_falls_back_to_keyword_reply(agent):
    async def fail(*args, **kwargs):
        raise ValueError('PRIVATE_DIAGNOSTIC')
    agent.intelligence.json_call = fail
    await agent.transcript(turn('Echooo，你好'), 'rec:1:1'); agent.queue.get_nowait()
    await agent.transcript(turn('那你为什么这么说？'), 'rec:1:2'); await settle(agent)
    assert agent.queue.empty() and agent.turn_decision == 'unavailable'
    assert 'PRIVATE_DIAGNOSTIC' not in agent.error


async def test_turn_classifier_never_reads_private_chat(agent, decisions):
    calls, _ = decisions
    await agent.accept('private:test', 'PRIVATE_QUESTION', 'private', '1024', reply=False)
    await agent.transcript(turn('Echooo，你好'), 'rec:1:1'); agent.queue.get_nowait()
    await agent.transcript(turn('展开一点'), 'rec:1:2'); await settle(agent)
    assert 'PRIVATE_QUESTION' not in str(calls)
    assert agent.queue.get_nowait()['request'] == '展开一点'
