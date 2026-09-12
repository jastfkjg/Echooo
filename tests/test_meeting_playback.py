import asyncio
import base64

import pytest

from echooo.meeting_playback import MeetingPlayback


async def test_requires_matching_ack_and_waits_for_actual_playback_completion():
    sent = asyncio.Queue()
    async def send(packet):
        await sent.put(packet['data'])
    playback = MeetingPlayback(send)
    start = asyncio.create_task(playback.start(24000))
    request = await sent.get()
    playback.receive({**request, 'stream_id': 'different'})
    await asyncio.sleep(0)
    assert not start.done()
    playback.receive({**request, 'buffered_ms': 0})
    await start
    finishing = asyncio.create_task(playback.finish())
    request = await sent.get()
    playback.receive({**request, 'done': False, 'buffered_ms': 300})
    assert not finishing.done()
    request = await sent.get()
    assert request['action'] == 'status'
    playback.receive({**request, 'done': True, 'buffered_ms': 0})
    await finishing
    assert playback.stream_id is None


async def test_backpressure_does_not_send_more_pcm_until_remote_buffer_drains():
    packets = []
    playback = None
    async def send(packet):
        data = packet['data']; packets.append(data)
        playback.receive({**data, 'buffered_ms': 0})
    playback = MeetingPlayback(send)
    await playback.start(16000)
    playback.metrics['buffered_ms'] = 1200
    await playback.chunk(b'\x01\x00' * 32)
    assert [p['action'] for p in packets] == ['start', 'status', 'chunk']
    assert base64.b64decode(packets[-1]['chunk']) == b'\x01\x00' * 32


async def test_cancelled_command_does_not_prevent_stop_or_accept_stale_reply():
    queue = asyncio.Queue()
    async def send(packet):
        await queue.put(packet['data'])
    playback = MeetingPlayback(send)
    starting = asyncio.create_task(playback.start(16000))
    stale = await queue.get()
    starting.cancel()
    await asyncio.gather(starting, return_exceptions=True)
    stopping = asyncio.create_task(playback.stop())
    request = await queue.get()
    playback.receive(stale)
    await asyncio.sleep(0)
    assert not stopping.done()
    playback.receive({**request, 'done': True})
    await stopping
    assert not playback.pending and playback.stream_id is None
