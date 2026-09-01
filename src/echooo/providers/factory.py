from __future__ import annotations

from echooo.config import Settings
from echooo.providers.base import LanguageModelProvider, SpeechToTextProvider, TextToSpeechProvider


def create_stt(settings: Settings) -> SpeechToTextProvider:
    if settings.stt_provider == "assemblyai":
        from echooo.providers.stt.assemblyai import AssemblyAIStreamingSTT

        return AssemblyAIStreamingSTT(settings)
    if settings.stt_provider == "mock":
        from echooo.providers.stt.mock import MockSTT

        return MockSTT()
    raise ValueError(f"Unknown STT_PROVIDER: {settings.stt_provider}")


def create_llm(settings: Settings) -> LanguageModelProvider:
    if settings.llm_provider == "openai_compatible":
        from echooo.providers.llm.openai_compatible import OpenAICompatibleLLM

        return OpenAICompatibleLLM(settings)
    if settings.llm_provider == "mock":
        from echooo.providers.llm.mock import MockLLM

        return MockLLM()
    raise ValueError(f"Unknown LLM_PROVIDER: {settings.llm_provider}")


def create_tts(settings: Settings) -> TextToSpeechProvider:
    if settings.tts_provider == "cosyvoice":
        from echooo.providers.tts.cosyvoice import CosyVoiceTTS

        return CosyVoiceTTS(settings)
    if settings.tts_provider == "mock":
        from echooo.providers.tts.mock import MockToneTTS

        return MockToneTTS()
    raise ValueError(f"Unknown TTS_PROVIDER: {settings.tts_provider}")

