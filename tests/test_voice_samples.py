from io import BytesIO

import pytest
from starlette.datastructures import UploadFile

from echooo.voice_samples import VoiceSampleError, VoiceSampleStore


async def test_voice_sample_is_kept_in_memory_and_can_be_deleted() -> None:
    store = VoiceSampleStore()
    upload = UploadFile(
        filename="voice.wav",
        file=BytesIO(b"RIFF-reference-audio"),
        headers={"content-type": "audio/wav"},
    )

    sample = await store.save_upload(upload)

    assert sample.filename == "voice.wav"
    assert (await store.get(sample.id)).data == b"RIFF-reference-audio"
    await store.delete(sample.id)
    with pytest.raises(VoiceSampleError):
        await store.get(sample.id)


async def test_voice_sample_rejects_non_audio_extension() -> None:
    store = VoiceSampleStore()
    upload = UploadFile(filename="notes.txt", file=BytesIO(b"not audio"))

    with pytest.raises(VoiceSampleError, match="Upload WAV"):
        await store.save_upload(upload)
