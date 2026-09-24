"""Backpressure and playback completion from the remote AudioWorklet."""
import asyncio
import base64
import contextlib
import secrets
import time


class MeetingPlayback:
    def __init__(self, send):
        self.send = send
        self.stream_id = None
        self.pending = {}
        self.lock = asyncio.Lock()
        self.gate = asyncio.Event(); self.gate.set()
        self.metrics = {}
        self.on_first_audio = None
        self.first_audio_reported = False

    def receive(self, data):
        if data.get('stream_id') != self.stream_id:
            return
        future = self.pending.get(data.get('request_id'))
        if future and not future.done():
            future.set_result(data)

    async def command(self, action, **values):
        async with self.lock:
            if not self.stream_id:
                raise ValueError('No active speech stream')
            request = secrets.token_hex(8)
            future = self.pending[request] = asyncio.get_running_loop().create_future()
            try:
                await self.send({'trigger': 'echooo.audio', 'data': {
                    'stream_id': self.stream_id, 'request_id': request, 'action': action, **values}})
                result = await asyncio.wait_for(future, 8)
                if result.get('error'):
                    raise ValueError('Remote audio playback failed')
                self.metrics = {k: result[k] for k in ('buffered_ms', 'played_samples', 'received_samples', 'underruns', 'first_audio_ms') if k in result}
                if not self.first_audio_reported and self.metrics.get('played_samples', 0) > 0:
                    self.first_audio_reported = True
                    if self.on_first_audio:
                        self.on_first_audio({'measurement': 'remote_output_frame',
                            'start_to_first_audio_ms': self.metrics.get('first_audio_ms')})
                return result
            finally:
                self.pending.pop(request, None)

    async def start(self, rate):
        self.metrics = {}
        self.first_audio_reported = False
        self.stream_id = secrets.token_hex(12)
        self.gate.set()
        await self.command('start', sample_rate=rate)

    async def chunk(self, pcm):
        await self.gate.wait()
        # Retain roughly 0.8 seconds remotely, enough to absorb network jitter.
        while self.metrics.get('buffered_ms', 0) > 800:
            await asyncio.sleep(.1)
            await self.gate.wait()
            await self.command('status')
        await self.command('chunk', chunk=base64.b64encode(pcm).decode())

    async def finish(self):
        result = await self.command('finish')
        deadline = time.monotonic() + 120
        while not result.get('done'):
            if time.monotonic() > deadline:
                raise TimeoutError('Playback did not finish')
            await asyncio.sleep(.1)
            await self.gate.wait()
            result = await self.command('status')
        self.stream_id = None

    async def pause(self):
        self.gate.clear()
        if self.stream_id:
            await self.command('pause')

    async def resume(self):
        try:
            if self.stream_id:
                await self.command('resume')
        finally:
            self.gate.set()

    async def stop(self):
        self.gate.set()
        if self.stream_id:
            with contextlib.suppress(Exception):
                await self.command('stop')
        self.stream_id = None
