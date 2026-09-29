"""Owner-scoped server speech preferences shared by both meeting transports."""
import asyncio
import base64
import io
import time
import wave
from dataclasses import replace

from pydantic import Field

from echooo import database as db
from echooo.contracts import Input
from echooo.models import VoiceProfile
from echooo.providers.factory import create_tts
from echooo.service import Problem
from echooo.voice_ownership import visible_voices


class VoiceSettings(Input):
    provider: str = Field(max_length=40)
    voice: str = Field(min_length=1, max_length=200)


def providers(settings):
    configured = settings.assistant_tts_providers or settings.tts_provider
    return [p for p in dict.fromkeys(p.strip() for p in configured.split(','))
        if p in {'dashscope', 'cosyvoice'} and (p != 'dashscope' or settings.dashscope_api_key)]


def preferences(store, who, settings):
    with store.scope(who) as r:
        rows = r.list(db.assistant_voice_settings)
    if rows:
        return {k: rows[0][k] for k in ('provider', 'voice')}
    choices = providers(settings)
    provider = settings.tts_provider if settings.tts_provider in choices else choices[0] if choices else ''
    return {'provider': provider, 'voice': settings.dashscope_tts_voice if provider == 'dashscope'
        else settings.cosyvoice_speaker_id if provider == 'cosyvoice' else ''}


def factory(store, who, settings):
    selected = preferences(store, who, settings)
    if selected['provider'] not in providers(settings):
        raise Problem('The selected speech service is unavailable. Update Assistant voice in Settings.', 503)
    tts = create_tts(replace(settings, tts_provider=selected['provider']))
    tts.configure_voice(VoiceProfile(mode='sft', speaker_id=selected['voice']))
    return tts


async def synthesize(tts, text, cancel=None):
    """Bounded WAV for local playback; no browser-synthesis fallback."""
    cancel = cancel or asyncio.Event()
    pcm, rate = bytearray(), None
    async with asyncio.timeout(30):
        async for chunk in tts.stream_audio(text, cancel=cancel):
            if cancel.is_set():
                raise asyncio.CancelledError()
            if (chunk.encoding != 'pcm_s16le' or chunk.channels != 1 or
                    chunk.sample_rate not in {8000, 16000, 24000} or
                    rate is not None and rate != chunk.sample_rate):
                raise ValueError('Unsupported speech audio format')
            rate = chunk.sample_rate
            pcm.extend(chunk.data)
            if len(pcm) > rate * 2 * 120:
                raise ValueError('Speech exceeds playback limit')
    if not pcm or len(pcm) % 2:
        raise ValueError('Speech service returned no valid audio')
    output = io.BytesIO()
    with wave.open(output, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)
    return base64.b64encode(output.getvalue()).decode('ascii')


def routes(app, store, settings, owner):
    async def catalogue(who):
        services = []
        for provider in providers(settings):
            if provider == 'dashscope':
                voices = settings.dashscope_voice_options()
                manager = app.state.voice_manager
                if manager:
                    try:
                        custom = visible_voices(store, who, await manager.list_voices())
                        known = {v['id'] for v in voices}
                        voices += [v for v in custom if v.get('status') == 'OK' and v['id'] not in known]
                    except Exception:
                        pass  # Presets remain usable when voice management is unavailable.
            else:
                voices = [{'id': settings.cosyvoice_speaker_id, 'name': 'Configured preset'}]
            services.append({'id': provider, 'name': 'DashScope' if provider == 'dashscope' else 'CosyVoice',
                'voices': voices})
        return services

    async def validate(who, data):
        services = await catalogue(who)
        if not any(s['id'] == data.provider and any(v['id'] == data.voice for v in s['voices']) for s in services):
            raise Problem('Choose an available speech service and voice.', 422)

    from fastapi import Request

    @app.get('/api/settings/assistant-voice')
    async def get_voice(request: Request):
        who = owner(request)
        return {**preferences(store, who, settings), 'services': await catalogue(who)}

    @app.put('/api/settings/assistant-voice')
    async def save_voice(request: Request, data: VoiceSettings):
        who = owner(request)
        await validate(who, data)
        # An upsert also handles two settings pages saving for the first time.
        if store.postgres:
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        with store.scope(who) as r:
            r.c.execute(insert(db.assistant_voice_settings).values(id=db.uid(), owner_id=who,
                created_at=time.time(), **data.model_dump()).on_conflict_do_update(
                    index_elements=['owner_id'], set_=data.model_dump()))
        return data.model_dump()

    @app.post('/api/settings/assistant-voice/preview')
    async def preview(request: Request, data: VoiceSettings):
        who = owner(request)
        await validate(who, data)
        tts = create_tts(replace(settings, tts_provider=data.provider))
        tts.configure_voice(VoiceProfile(mode='sft', speaker_id=data.voice))
        try:
            return {'audio': await synthesize(tts, 'Hello, this is your meeting assistant. I can help you follow the discussion.')}
        except Exception as exc:
            raise Problem('Speech preview failed. Check the speech service and try again.', 503) from exc
