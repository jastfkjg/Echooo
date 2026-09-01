from pathlib import Path

from echooo.config import Settings
from echooo.providers.tts.cosyvoice import CosyVoiceTTS


def test_sft_request_uses_speaker() -> None:
    settings = Settings(
        tts_provider="cosyvoice",
        cosyvoice_base_url="http://cosyvoice:50000/",
        cosyvoice_mode="sft",
        cosyvoice_speaker="中文女",
    )

    url, data, files = CosyVoiceTTS(settings)._request("你好")

    assert url == "http://cosyvoice:50000/inference_sft"
    assert data == {"tts_text": "你好", "spk_id": "中文女"}
    assert files is None


def test_zero_shot_request_attaches_prompt_wav(tmp_path: Path) -> None:
    prompt = tmp_path / "prompt.wav"
    prompt.write_bytes(b"RIFF-test")
    settings = Settings(
        tts_provider="cosyvoice",
        cosyvoice_mode="zero_shot",
        cosyvoice_prompt_wav=str(prompt),
        cosyvoice_prompt_text="参考音频文本",
    )

    url, data, files = CosyVoiceTTS(settings)._request("要合成的文本")

    assert url.endswith("/inference_zero_shot")
    assert data == {"tts_text": "要合成的文本", "prompt_text": "参考音频文本"}
    assert files is not None
    assert files["prompt_wav"] == ("prompt.wav", b"RIFF-test", "audio/wav")
