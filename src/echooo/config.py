from __future__ import annotations

import os
import math
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]
PROMPTS_FILE = ROOT / "config" / "prompts.toml"


# Compact, conversation-oriented subsets of the official catalogues. Operators
# can expose additional base/enrolled voice IDs with DASHSCOPE_TTS_CUSTOM_VOICES.
DASHSCOPE_VOICE_CATALOGUES = {
    "qwen-audio-3.0-tts-plus": (
        ("longanlingxin", "Lingxin", "Warm, thoughtful female voice"),
        ("longanlufeng", "Lufeng", "Bright, upbeat male voice"),
    ),
    "qwen-audio-3.0-tts-flash": (
        ("longanfengyue", "Fengyue", "Natural, friendly female voice"),
        ("longanyuanfei", "Yuanfei", "Regal female voice"),
        ("longanlingxi", "Lingxi", "Sweet, playful female voice"),
        ("loongeva_v3.6", "Eva", "Polished American English female voice"),
        ("loongjohn", "John", "Calm American English male voice"),
    ),
    "cosyvoice-v3-flash": (
        ("longanyang", "Yang", "Sunny, natural male voice · Mandarin / English"),
        ("longanhuan", "Huan", "Energetic female voice · Mandarin / English"),
        ("longanwen_v3", "Wen", "Elegant female voice · Mandarin / English"),
        ("longanlang_v3", "Lang", "Crisp male voice · Mandarin / English"),
        ("longyingtao_v3", "Yingtao", "Gentle female voice · Mandarin / English"),
        ("longyichen_v3", "Yichen", "Lively male voice · Mandarin / English"),
        ("longlaobo_v3", "Laobo", "Mature male voice · Mandarin / English"),
        ("longanyue_v3", "Yue", "Energetic Cantonese male voice · Cantonese / English"),
        ("loongandy_v3", "Andy", "American English male voice"),
        ("loongindah_v3", "Indah", "Indonesian female voice"),
        ("longhuhu_v3", "Huhu", "Playful child voice · Mandarin / English"),
        ("longjiqi_v3", "Robot", "Playful robot voice · Mandarin / English"),
    ),
}


def _csv(name: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value.strip() for value in os.getenv(name, "").split(",") if value.strip()))


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def _optional_int(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    return int(value) if value else None


@dataclass(frozen=True, slots=True)
class PromptSettings:
    """Version-controlled agent behavior, deliberately kept out of .env."""

    delegate_system: str = ""
    check_system: str = ""
    memory_system: str = ""

    @classmethod
    def load(cls, path: Path = PROMPTS_FILE) -> "PromptSettings":
        try:
            with path.open("rb") as handle:
                document = tomllib.load(handle)
            return cls(
                delegate_system=str(document.get("delegate", {}).get("system", "")).strip(),
                check_system=str(document.get("check", {}).get("system", "")).strip(),
                memory_system=str(document.get("memory", {}).get("system", "")).strip(),
            )
        except FileNotFoundError as exc:
            raise ValueError(f"Prompt configuration not found: {path}") from exc
        except (KeyError, TypeError, tomllib.TOMLDecodeError) as exc:
            raise ValueError(f"Invalid prompt configuration: {path}: {exc}") from exc


@dataclass(slots=True)
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///data/echooo.db"))
    public_origin: str = field(default_factory=lambda: os.getenv("PUBLIC_ORIGIN", ""))
    cookie_secure: bool = field(default_factory=lambda: os.getenv("COOKIE_SECURE", "false").lower() == "true")
    app_host: str = field(default_factory=lambda: os.getenv("APP_HOST", "127.0.0.1"))
    app_port: int = field(default_factory=lambda: _int("APP_PORT", 8000))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    attendee_base_url: str = field(default_factory=lambda: os.getenv("ATTENDEE_BASE_URL", ""))
    attendee_api_key: str = field(default_factory=lambda: os.getenv("ATTENDEE_API_KEY", ""))
    attendee_callback_url: str = field(default_factory=lambda: os.getenv("ATTENDEE_CALLBACK_URL", ""))
    attendee_max_seconds: int = field(default_factory=lambda: _int("ATTENDEE_MAX_SECONDS", 7200))

    stt_provider: str = field(default_factory=lambda: os.getenv("STT_PROVIDER", "mock"))
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "mock"))
    tts_provider: str = field(default_factory=lambda: os.getenv("TTS_PROVIDER", "browser"))

    assemblyai_api_key: str = field(default_factory=lambda: os.getenv("ASSEMBLYAI_API_KEY", ""))
    assemblyai_api_url: str = field(default_factory=lambda: os.getenv("ASSEMBLYAI_API_URL", "https://api.assemblyai.com"))
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

    cosyvoice_base_url: str = field(
        default_factory=lambda: os.getenv("COSYVOICE_BASE_URL", "http://127.0.0.1:50000")
    )
    cosyvoice_sample_rate: int = field(default_factory=lambda: _int("COSYVOICE_SAMPLE_RATE", 24000))
    cosyvoice_timeout_seconds: float = field(
        default_factory=lambda: _float("COSYVOICE_TIMEOUT_SECONDS", 60)
    )
    cosyvoice_speaker_id: str = field(default_factory=lambda: os.getenv("COSYVOICE_SPEAKER_ID", "中文女"))
    dashscope_api_key: str = field(default_factory=lambda: os.getenv("DASHSCOPE_API_KEY", ""))
    dashscope_voice_api_key: str = field(default_factory=lambda: os.getenv("DASHSCOPE_VOICE_API_KEY", ""))
    dashscope_tts_url: str = field(default_factory=lambda: os.getenv(
        "DASHSCOPE_TTS_URL", "wss://dashscope.aliyuncs.com/api-ws/v1/inference"))
    dashscope_tts_customization_url: str = field(default_factory=lambda: os.getenv(
        "DASHSCOPE_TTS_CUSTOMIZATION_URL", ""))
    dashscope_upload_url: str = field(default_factory=lambda: os.getenv(
        "DASHSCOPE_UPLOAD_URL", "https://dashscope.aliyuncs.com/api/v1/uploads"))
    dashscope_tts_model: str = field(default_factory=lambda: os.getenv("DASHSCOPE_TTS_MODEL", "cosyvoice-v3-flash"))
    dashscope_tts_voice: str = field(default_factory=lambda: os.getenv("DASHSCOPE_TTS_VOICE", "longanyang"))
    dashscope_tts_custom_voices: tuple[str, ...] = field(default_factory=lambda: _csv("DASHSCOPE_TTS_CUSTOM_VOICES"))
    dashscope_tts_sample_rate: int = field(default_factory=lambda: _int("DASHSCOPE_TTS_SAMPLE_RATE", 24000))
    dashscope_tts_timeout_seconds: float = field(default_factory=lambda: _float("DASHSCOPE_TTS_TIMEOUT_SECONDS", 60))
    prompts: PromptSettings = field(default_factory=PromptSettings.load)

    @classmethod
    def load(cls, env_file: Path | None = None) -> "Settings":
        load_dotenv(env_file or ROOT / ".env", override=False)
        return cls()

    def validate(self) -> None:
        if self.attendee_base_url:
            url = urlsplit(self.attendee_base_url)
            if url.scheme not in {'http', 'https'} or not url.hostname or url.username or url.password or url.query or url.fragment:
                raise ValueError('ATTENDEE_BASE_URL must be an HTTP(S) service URL without credentials or query')
        if self.attendee_callback_url:
            url = urlsplit(self.attendee_callback_url)
            if url.scheme != 'wss' or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in {'', '/'}:
                raise ValueError('ATTENDEE_CALLBACK_URL must be a wss:// origin reachable by Attendee')
        if not 60 <= self.attendee_max_seconds <= 14400:
            raise ValueError('ATTENDEE_MAX_SECONDS must be between 60 and 14400')
        if self.tts_provider == "mock":
            self.tts_provider = "browser"  # Compatibility with the former local demo .env.
        for value, choices, label in ((self.stt_provider, {"mock", "assemblyai"}, "STT"),
            (self.llm_provider, {"mock", "openai_compatible"}, "LLM"),
            (self.tts_provider, {"browser", "cosyvoice", "dashscope"}, "TTS")):
            if value not in choices:
                raise ValueError(f"Unsupported {label} provider: {value}")
        if self.assemblyai_sample_rate != 16000:
            raise ValueError("This browser capture release requires ASSEMBLYAI_SAMPLE_RATE=16000")
        if self.stt_provider == "assemblyai" and not self.assemblyai_api_key:
            raise ValueError("ASSEMBLYAI_API_KEY is required when STT_PROVIDER=assemblyai")
        if self.tts_provider == "dashscope":
            for name, value in (("DASHSCOPE_API_KEY", self.dashscope_api_key),
                ("DASHSCOPE_TTS_MODEL", self.dashscope_tts_model),
                ("DASHSCOPE_TTS_VOICE", self.dashscope_tts_voice)):
                if not value.strip():
                    raise ValueError(f"{name} is required when TTS_PROVIDER=dashscope")
            url = urlsplit(self.dashscope_tts_url)
            if url.scheme != "wss" or not url.hostname or url.username or url.password or url.query or url.fragment:
                raise ValueError("DASHSCOPE_TTS_URL must be a wss:// endpoint without credentials, query or fragment")
            for name, endpoint in (("DASHSCOPE_TTS_CUSTOMIZATION_URL", self.dashscope_customization_url()),
                ("DASHSCOPE_UPLOAD_URL", self.dashscope_upload_url)):
                parsed = urlsplit(endpoint)
                if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                    raise ValueError(f"{name} must be an https:// endpoint without credentials, query or fragment")
            if self.dashscope_tts_sample_rate not in {8000, 16000, 22050, 24000, 44100, 48000}:
                raise ValueError("Unsupported DASHSCOPE_TTS_SAMPLE_RATE")
            if not math.isfinite(self.dashscope_tts_timeout_seconds) or self.dashscope_tts_timeout_seconds <= 0:
                raise ValueError("DASHSCOPE_TTS_TIMEOUT_SECONDS must be finite and greater than zero")
            for voice in (self.dashscope_tts_voice, *self.dashscope_tts_custom_voices):
                if not re.fullmatch(r"[A-Za-z0-9_.-]{1,256}", voice):
                    raise ValueError("DashScope voice IDs may contain only letters, numbers, dot, underscore and hyphen")
        if self.llm_provider == "openai_compatible" and not self.llm_model:
            raise ValueError("LLM_MODEL is required when LLM_PROVIDER=openai_compatible")
        if self.llm_provider == "openai_compatible" and not all((self.prompts.delegate_system, self.prompts.check_system, self.prompts.memory_system)):
            raise ValueError("config/prompts.toml must define delegate, check, and memory prompts")

    def public_dict(self) -> dict[str, object]:
        public = {
            "providers": {
                "stt": self.stt_provider,
                "llm": self.llm_provider,
                "tts": self.tts_provider,
            },
            "audio": {
                "input_sample_rate": self.assemblyai_sample_rate,
                "input_encoding": "pcm_s16le",
            },
        }
        if self.tts_provider == "dashscope":
            public["tts"] = {
                "model": self.dashscope_tts_model,
                "default_voice": self.dashscope_tts_voice,
                "voices": self.dashscope_voice_options(),
                "custom_voice_management": True,
            }
        return public

    def dashscope_voice_options(self) -> list[dict[str, object]]:
        presets = DASHSCOPE_VOICE_CATALOGUES.get(self.dashscope_tts_model, ())
        options = [{"id": voice_id, "name": name, "description": description, "custom": False}
            for voice_id, name, description in presets]
        known = {option["id"] for option in options}
        if self.dashscope_tts_voice not in known:
            options.insert(0, {"id": self.dashscope_tts_voice, "name": self.dashscope_tts_voice,
                "description": "Server default voice", "custom": True})
            known.add(self.dashscope_tts_voice)
        for voice_id in self.dashscope_tts_custom_voices:
            if voice_id not in known:
                options.append({"id": voice_id, "name": voice_id,
                    "description": "Custom voice", "custom": True})
                known.add(voice_id)
        return options

    def dashscope_voice_ids(self) -> set[str]:
        return {str(option["id"]) for option in self.dashscope_voice_options()}

    def dashscope_customization_url(self) -> str:
        if self.dashscope_tts_customization_url.strip():
            return self.dashscope_tts_customization_url.strip()
        endpoint = urlsplit(self.dashscope_tts_url)
        return f"https://{endpoint.netloc}/api/v1/services/audio/tts/customization"
