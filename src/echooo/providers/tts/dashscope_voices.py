from __future__ import annotations

import re
import uuid
import wave
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from echooo.config import Settings


MAX_VOICE_SAMPLE = 10 * 1024 * 1024
VOICE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,256}$")
VOICE_PREFIX = re.compile(r"^[A-Za-z0-9]{1,10}$")
LANGUAGES = {"zh", "en", "ja", "de", "fr", "ru", "ko"}
SUFFIXES = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4"}


class DashScopeVoiceError(RuntimeError):
    """A sanitized error from DashScope custom-voice management."""


def validate_voice_sample(filename: str, data: bytes) -> tuple[str, str]:
    """Validate safe, model-supported audio and return a random OSS filename."""
    suffix = Path(filename).suffix.lower()
    if suffix not in SUFFIXES:
        raise ValueError("Choose a WAV, MP3, or M4A recording.")
    if not data:
        raise ValueError("The voice sample is empty.")
    if len(data) > MAX_VOICE_SAMPLE:
        raise ValueError("The voice sample must be 10 MB or smaller.")
    if suffix == ".wav":
        if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
            raise ValueError("The selected file is not a valid WAV recording.")
        try:
            with wave.open(BytesIO(data)) as audio:
                duration = audio.getnframes() / audio.getframerate()
                if audio.getsampwidth() != 2:
                    raise ValueError("WAV samples must use 16-bit audio.")
                if audio.getframerate() < 16_000:
                    raise ValueError("WAV samples must use a sample rate of at least 16 kHz.")
                if duration < 5 or duration > 60:
                    raise ValueError("Voice samples must be between 5 and 60 seconds.")
        except (wave.Error, ZeroDivisionError) as exc:
            raise ValueError("The selected file is not a valid WAV recording.") from exc
    elif suffix == ".mp3" and not (data[:3] == b"ID3" or data[:2] >= b"\xff\xe0"):
        raise ValueError("The selected file is not a valid MP3 recording.")
    elif suffix == ".m4a" and (len(data) < 12 or data[4:8] != b"ftyp"):
        raise ValueError("The selected file is not a valid M4A recording.")
    return f"{uuid.uuid4().hex}{suffix}", SUFFIXES[suffix]


class DashScopeVoiceManager:
    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.transport = transport
        self.known_voice_ids: set[str] = set()
        self.cached_voices: list[dict] = []

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self.transport,
            timeout=httpx.Timeout(self.settings.dashscope_tts_timeout_seconds),
            headers={"Authorization": f"Bearer {self.settings.dashscope_voice_api_key or self.settings.dashscope_api_key}"},
        )

    @staticmethod
    def _checked_json(response: httpx.Response, operation: str) -> dict:
        try:
            payload = response.json()
        except ValueError as exc:
            raise DashScopeVoiceError(f"Alibaba Cloud returned an invalid response while {operation}.") from exc
        code = str(payload.get("code") or "")
        message = str(payload.get("message") or "").lower()
        if response.status_code == 401 or code == "InvalidApiKey":
            raise DashScopeVoiceError(
                "Alibaba Cloud rejected the voice-management API key. Configure "
                "DASHSCOPE_VOICE_API_KEY with a Model Studio API key for this region."
            )
        if response.status_code == 403:
            raise DashScopeVoiceError(
                "The configured Alibaba Cloud key does not have permission to manage custom voices."
            )
        if response.status_code == 404 and "model not exist" in message:
            raise DashScopeVoiceError(
                "The voice-enrollment service is unavailable at the configured customization endpoint. "
                "Check DASHSCOPE_TTS_CUSTOMIZATION_URL and enable voice cloning for this workspace."
            )
        if response.status_code == 404:
            raise DashScopeVoiceError(
                "The configured Alibaba Cloud customization endpoint was not found."
            )
        if response.is_error or code:
            raise DashScopeVoiceError(
                f"Alibaba Cloud could not complete voice {operation}; check the model, region, quota, and recording."
            )
        if not isinstance(payload.get("output", {}), dict):
            raise DashScopeVoiceError(f"Alibaba Cloud returned an invalid response while {operation}.")
        return payload

    async def _customize(self, input_: dict, operation: str, *, resolve_oss: bool = False) -> dict:
        headers = {"Content-Type": "application/json"}
        if resolve_oss:
            headers["X-DashScope-OssResourceResolve"] = "enable"
        try:
            async with self._client() as client:
                response = await client.post(
                    self.settings.dashscope_customization_url(),
                    headers=headers,
                    json={"model": "voice-enrollment", "input": input_},
                )
            return self._checked_json(response, operation)
        except DashScopeVoiceError:
            raise
        except (httpx.HTTPError, OSError) as exc:
            raise DashScopeVoiceError(f"Could not connect to Alibaba Cloud while {operation}.") from exc

    def _display_name(self, voice_id: str) -> str:
        model_prefix = self.settings.dashscope_tts_model + "-"
        if not voice_id.startswith(model_prefix):
            return voice_id
        enrolled = voice_id[len(model_prefix):]
        name, separator, unique_id = enrolled.partition("-")
        if separator and unique_id and VOICE_PREFIX.fullmatch(name):
            return name
        return voice_id

    def _option(self, item: dict) -> dict | None:
        voice_id = str(item.get("voice_id") or item.get("voice") or "").strip()
        if not VOICE_ID.fullmatch(voice_id):
            return None
        created = str(item.get("gmt_create") or "").strip()
        status = str(item.get("status") or "").strip()
        detail = "Custom voice"
        if status and status != "OK":
            detail += f" · {status}"
        elif created:
            detail += f" · {created[:10]}"
        return {
            "id": voice_id,
            "name": self._display_name(voice_id),
            "description": detail,
            "custom": True,
            "managed": True,
            "status": status or "OK",
            "target_model": str(item.get("target_model") or ""),
            "created_at": created,
        }

    async def list_voices(self) -> list[dict]:
        result: list[dict] = []
        for page in range(10):
            payload = await self._customize({
                "action": "list_voice", "page_index": page, "page_size": 100,
            }, "listing")
            items = payload.get("output", {}).get("voice_list", [])
            if not isinstance(items, list):
                raise DashScopeVoiceError("Alibaba Cloud returned an invalid response while listing voices.")
            for item in items:
                if not isinstance(item, dict):
                    continue
                option = self._option(item)
                if option and (option["target_model"] == self.settings.dashscope_tts_model or
                    (not option["target_model"] and option["id"].startswith(
                        self.settings.dashscope_tts_model + "-"))):
                    option["target_model"] = self.settings.dashscope_tts_model
                    result.append(option)
            if len(items) < 100:
                break
        voices = list({voice["id"]: voice for voice in result}.values())
        self.known_voice_ids = {voice["id"] for voice in voices}
        self.cached_voices = voices
        return voices

    async def query_voice(self, voice_id: str) -> dict | None:
        if not VOICE_ID.fullmatch(voice_id):
            return None
        payload = await self._customize(
            {"action": "query_voice", "voice_id": voice_id}, "querying"
        )
        item = {"voice_id": voice_id, **payload.get("output", {})}
        option = self._option(item)
        if option and option["target_model"] == self.settings.dashscope_tts_model:
            return option
        return None

    async def _upload(self, filename: str, content_type: str, data: bytes) -> str:
        try:
            async with self._client() as client:
                policy_response = await client.get(
                    self.settings.dashscope_upload_url,
                    headers={"Content-Type": "application/json"},
                    params={"action": "getPolicy", "model": "voice-enrollment"},
                )
                try:
                    policy_payload = policy_response.json()
                    policy = policy_payload.get("data", {})
                except ValueError as exc:
                    raise DashScopeVoiceError("Alibaba Cloud returned an invalid upload policy.") from exc
                code = str(policy_payload.get("code") or "")
                if policy_response.status_code == 401 or code == "InvalidApiKey":
                    raise DashScopeVoiceError(
                        "Alibaba Cloud rejected the key used for temporary file upload. "
                        "Set DASHSCOPE_VOICE_API_KEY to a Model Studio API key accepted by "
                        "DASHSCOPE_UPLOAD_URL."
                    )
                if policy_response.status_code == 403:
                    raise DashScopeVoiceError(
                        "The configured Alibaba Cloud key cannot upload temporary voice samples."
                    )
                if policy_response.status_code == 404:
                    raise DashScopeVoiceError(
                        "The configured DASHSCOPE_UPLOAD_URL does not provide the temporary upload API."
                    )
                required = ("policy", "signature", "upload_dir", "upload_host",
                    "oss_access_key_id", "x_oss_object_acl", "x_oss_forbid_overwrite")
                if policy_response.is_error or not all(policy.get(key) for key in required):
                    raise DashScopeVoiceError("Alibaba Cloud could not prepare the voice sample upload.")
                upload_host = str(policy["upload_host"])
                host = urlsplit(upload_host)
                if host.scheme != "https" or not host.hostname or not host.hostname.endswith(".aliyuncs.com"):
                    raise DashScopeVoiceError("Alibaba Cloud returned an invalid upload destination.")
                upload_dir = str(policy["upload_dir"]).strip("/")
                if not upload_dir or ".." in upload_dir.split("/"):
                    raise DashScopeVoiceError("Alibaba Cloud returned an invalid upload destination.")
                key = f"{upload_dir}/{filename}"
                form = {
                    "OSSAccessKeyId": str(policy["oss_access_key_id"]),
                    "Signature": str(policy["signature"]),
                    "policy": str(policy["policy"]),
                    "x-oss-object-acl": str(policy["x_oss_object_acl"]),
                    "x-oss-forbid-overwrite": str(policy["x_oss_forbid_overwrite"]),
                    "key": key,
                    "success_action_status": "200",
                }
                upload = await client.post(upload_host, data=form,
                    files={"file": (filename, data, content_type)})
                if upload.is_error:
                    raise DashScopeVoiceError("Alibaba Cloud could not upload the voice sample.")
                return f"oss://{key}"
        except DashScopeVoiceError:
            raise
        except (httpx.HTTPError, OSError) as exc:
            raise DashScopeVoiceError("Could not connect to Alibaba Cloud while uploading the voice sample.") from exc

    async def create_voice(self, *, prefix: str, language: str, filename: str,
        data: bytes, enable_preprocess: bool = False) -> dict:
        if not VOICE_PREFIX.fullmatch(prefix):
            raise ValueError("Voice name must contain 1–10 English letters or numbers.")
        if language not in LANGUAGES:
            raise ValueError("Choose a supported recording language.")
        safe_name, content_type = validate_voice_sample(filename, data)
        url = await self._upload(safe_name, content_type, data)
        payload = await self._customize({
            "action": "create_voice",
            "target_model": self.settings.dashscope_tts_model,
            "prefix": prefix,
            "url": url,
            "language_hints": [language],
            "enable_preprocess": enable_preprocess,
            "enable_volume_normalization": "false",
        }, "creation", resolve_oss=True)
        voice_id = str(payload.get("output", {}).get("voice_id") or "").strip()
        if not VOICE_ID.fullmatch(voice_id):
            raise DashScopeVoiceError("Alibaba Cloud created the voice but returned an invalid voice ID.")
        fallback = {
            "id": voice_id, "name": prefix, "description": "Custom voice",
            "custom": True, "managed": True, "status": "DEPLOYING", "target_model": self.settings.dashscope_tts_model,
            "created_at": "",
        }
        try:
            voice = await self.query_voice(voice_id) or fallback
        except DashScopeVoiceError:
            # Creation succeeded. A delayed status lookup must not invite a retry
            # that creates a duplicate voice.
            voice = fallback
        self.known_voice_ids.add(voice_id)
        self.cached_voices = [item for item in self.cached_voices if item["id"] != voice_id] + [voice]
        return voice

    async def delete_voice(self, voice_id: str) -> None:
        voices = await self.list_voices()
        if voice_id not in {voice["id"] for voice in voices}:
            raise ValueError("This custom voice does not exist for the configured model.")
        await self._customize({"action": "delete_voice", "voice_id": voice_id}, "deletion")
        self.known_voice_ids.discard(voice_id)
        self.cached_voices = [voice for voice in self.cached_voices if voice["id"] != voice_id]
