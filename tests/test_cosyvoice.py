from echooo.config import Settings
from echooo.models import VoiceProfile
from echooo.providers.tts.cosyvoice import CosyVoiceTTS


def test_sft_request_uses_speaker() -> None:
    settings = Settings(
        tts_provider="cosyvoice",
        cosyvoice_base_url="http://cosyvoice:50000/",
    )
    provider = CosyVoiceTTS(settings)
    provider.configure_voice(VoiceProfile(mode="sft", speaker_id="English Female"))

    url, data, files = provider._request("Hello")

    assert url == "http://cosyvoice:50000/inference_sft"
    assert data == {"tts_text": "Hello", "spk_id": "English Female"}
    assert files is None


def test_zero_shot_request_attaches_uploaded_audio() -> None:
    provider = CosyVoiceTTS(Settings(tts_provider="cosyvoice"))
    provider.configure_voice(
        VoiceProfile(
            mode="zero_shot",
            reference_audio=b"RIFF-test",
            reference_filename="prompt.wav",
            reference_content_type="audio/wav",
            reference_text="Reference audio transcript",
        )
    )

    url, data, files = provider._request("Text to synthesize")

    assert url.endswith("/inference_zero_shot")
    assert data == {
        "tts_text": "Text to synthesize",
        "prompt_text": "Reference audio transcript",
    }
    assert files is not None
    assert files["prompt_wav"] == ("prompt.wav", b"RIFF-test", "audio/wav")
