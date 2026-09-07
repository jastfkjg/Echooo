from __future__ import annotations

from echooo.config import Settings
from echooo.providers.base import SpeechToTextProvider, TextToSpeechProvider


def create_stt(settings: Settings) -> SpeechToTextProvider:
    if settings.stt_provider == "assemblyai":
        from echooo.providers.stt.assemblyai import AssemblyAIStreamingSTT

        return AssemblyAIStreamingSTT(settings)
    if settings.stt_provider == "mock":
        from echooo.providers.stt.mock import MockSTT

        return MockSTT()
    raise ValueError(f"Unknown STT_PROVIDER: {settings.stt_provider}")


def create_tts(settings: Settings) -> TextToSpeechProvider:
    if settings.tts_provider == "dashscope":
        from echooo.providers.tts.dashscope import DashScopeTTS

        return DashScopeTTS(settings)
    if settings.tts_provider == "cosyvoice":
        from echooo.providers.tts.cosyvoice import CosyVoiceTTS

        return CosyVoiceTTS(settings)
    raise ValueError(f"Unknown TTS_PROVIDER: {settings.tts_provider}")
