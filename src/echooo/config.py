from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def _optional_int(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    return int(value) if value else None


@dataclass(slots=True)
class Settings:
    app_host: str = field(default_factory=lambda: os.getenv("APP_HOST", "127.0.0.1"))
    app_port: int = field(default_factory=lambda: _int("APP_PORT", 8000))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))

    stt_provider: str = field(default_factory=lambda: os.getenv("STT_PROVIDER", "mock"))
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "mock"))
    tts_provider: str = field(default_factory=lambda: os.getenv("TTS_PROVIDER", "mock"))

    assemblyai_api_key: str = field(default_factory=lambda: os.getenv("ASSEMBLYAI_API_KEY", ""))
    assemblyai_streaming_url: str = field(
        default_factory=lambda: os.getenv(
            "ASSEMBLYAI_STREAMING_URL", "wss://streaming.assemblyai.com/v3/ws"
        )
    )
    assemblyai_speech_model: str = field(
        default_factory=lambda: os.getenv("ASSEMBLYAI_SPEECH_MODEL", "universal-3-5-pro")
    )
    assemblyai_sample_rate: int = field(
        default_factory=lambda: _int("ASSEMBLYAI_SAMPLE_RATE", 16000)
    )
    assemblyai_mode: str = field(default_factory=lambda: os.getenv("ASSEMBLYAI_MODE", "balanced"))
    assemblyai_language_code: str = field(
        default_factory=lambda: os.getenv("ASSEMBLYAI_LANGUAGE_CODE", "").strip()
    )
    assemblyai_min_turn_silence: int | None = field(
        default_factory=lambda: _optional_int("ASSEMBLYAI_MIN_TURN_SILENCE")
    )
    assemblyai_max_turn_silence: int | None = field(
        default_factory=lambda: _optional_int("ASSEMBLYAI_MAX_TURN_SILENCE")
    )

    llm_base_url: str = field(
        default_factory=lambda: os.getenv("LLM_BASE_URL", "http://127.0.0.1:11434/v1")
    )
    llm_api_key: str = field(default_factory=lambda: os.getenv("LLM_API_KEY", ""))
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "local-model"))
    llm_temperature: float = field(default_factory=lambda: _float("LLM_TEMPERATURE", 0.4))
    llm_timeout_seconds: float = field(default_factory=lambda: _float("LLM_TIMEOUT_SECONDS", 60))
    llm_system_prompt: str = field(
        default_factory=lambda: os.getenv(
            "LLM_SYSTEM_PROMPT",
            "你是一个简洁、可靠的中文语音助手。回答适合被朗读，不使用 Markdown 表格。",
        )
    )

    cosyvoice_base_url: str = field(
        default_factory=lambda: os.getenv("COSYVOICE_BASE_URL", "http://127.0.0.1:50000")
    )
    cosyvoice_mode: str = field(default_factory=lambda: os.getenv("COSYVOICE_MODE", "sft"))
    cosyvoice_sample_rate: int = field(default_factory=lambda: _int("COSYVOICE_SAMPLE_RATE", 24000))
    cosyvoice_timeout_seconds: float = field(
        default_factory=lambda: _float("COSYVOICE_TIMEOUT_SECONDS", 60)
    )
    cosyvoice_speaker: str = field(
        default_factory=lambda: os.getenv("COSYVOICE_SPEAKER", "中文女")
    )
    cosyvoice_prompt_wav: str = field(
        default_factory=lambda: os.getenv("COSYVOICE_PROMPT_WAV", "")
    )
    cosyvoice_prompt_text: str = field(
        default_factory=lambda: os.getenv("COSYVOICE_PROMPT_TEXT", "")
    )
    cosyvoice_instruct_text: str = field(
        default_factory=lambda: os.getenv("COSYVOICE_INSTRUCT_TEXT", "")
    )

    history_limit: int = field(default_factory=lambda: _int("HISTORY_LIMIT", 20))

    @classmethod
    def load(cls, env_file: Path | None = None) -> "Settings":
        load_dotenv(env_file or ROOT / ".env", override=False)
        return cls()

    def validate(self) -> None:
        if self.stt_provider == "assemblyai" and not self.assemblyai_api_key:
            raise ValueError("ASSEMBLYAI_API_KEY is required when STT_PROVIDER=assemblyai")
        if self.llm_provider == "openai_compatible" and not self.llm_model:
            raise ValueError("LLM_MODEL is required when LLM_PROVIDER=openai_compatible")
        if self.tts_provider == "cosyvoice":
            if self.cosyvoice_mode not in {
                "sft",
                "zero_shot",
                "cross_lingual",
                "instruct",
                "instruct2",
            }:
                raise ValueError(f"Unsupported COSYVOICE_MODE: {self.cosyvoice_mode}")
            if self.cosyvoice_mode in {"zero_shot", "cross_lingual", "instruct2"}:
                prompt = self.resolve_path(self.cosyvoice_prompt_wav)
                if not prompt or not prompt.is_file():
                    raise ValueError(
                        "COSYVOICE_PROMPT_WAV must point to a readable file for "
                        f"COSYVOICE_MODE={self.cosyvoice_mode}"
                    )

    @staticmethod
    def resolve_path(value: str) -> Path | None:
        if not value:
            return None
        path = Path(value).expanduser()
        return path if path.is_absolute() else ROOT / path

    def public_dict(self) -> dict[str, object]:
        return {
            "providers": {
                "stt": self.stt_provider,
                "llm": self.llm_provider,
                "tts": self.tts_provider,
            },
            "audio": {
                "input_sample_rate": self.assemblyai_sample_rate,
                "input_encoding": "pcm_s16le",
            },
            "debug_text_enabled": True,
        }

