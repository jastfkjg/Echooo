from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]
PROMPTS_FILE = ROOT / "config" / "prompts.toml"


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

    stt_provider: str = field(default_factory=lambda: os.getenv("STT_PROVIDER", "mock"))
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "mock"))
    tts_provider: str = field(default_factory=lambda: os.getenv("TTS_PROVIDER", "browser"))

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
    prompts: PromptSettings = field(default_factory=PromptSettings.load)

    @classmethod
    def load(cls, env_file: Path | None = None) -> "Settings":
        load_dotenv(env_file or ROOT / ".env", override=False)
        return cls()

    def validate(self) -> None:
        if self.tts_provider == "mock":
            self.tts_provider = "browser"  # Compatibility with the former local demo .env.
        for value, choices, label in ((self.stt_provider, {"mock", "assemblyai"}, "STT"),
            (self.llm_provider, {"mock", "openai_compatible"}, "LLM"),
            (self.tts_provider, {"browser", "cosyvoice"}, "TTS")):
            if value not in choices:
                raise ValueError(f"Unsupported {label} provider: {value}")
        if self.assemblyai_sample_rate != 16000:
            raise ValueError("This browser capture release requires ASSEMBLYAI_SAMPLE_RATE=16000")
        if self.stt_provider == "assemblyai" and not self.assemblyai_api_key:
            raise ValueError("ASSEMBLYAI_API_KEY is required when STT_PROVIDER=assemblyai")
        if self.llm_provider == "openai_compatible" and not self.llm_model:
            raise ValueError("LLM_MODEL is required when LLM_PROVIDER=openai_compatible")
        if self.llm_provider == "openai_compatible" and not all((self.prompts.delegate_system, self.prompts.check_system, self.prompts.memory_system)):
            raise ValueError("config/prompts.toml must define delegate, check, and memory prompts")

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
        }
