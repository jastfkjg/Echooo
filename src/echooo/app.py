from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from echooo.config import ROOT, Settings
from echooo.orchestrator import VoiceSession
from echooo.voice_samples import MAX_VOICE_SAMPLE_BYTES, VoiceSampleError, VoiceSampleStore


settings = Settings.load()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

WEB_DIR = ROOT / "web"
app = FastAPI(title="Echooo", version="0.1.0")
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
voice_samples = VoiceSampleStore()


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/health")
async def health() -> dict[str, object]:
    return {"status": "ok", **settings.public_dict()}


@app.get("/api/config")
async def public_config() -> dict[str, object]:
    return {
        **settings.public_dict(),
        "voice_upload": {
            "enabled": True,
            "max_bytes": MAX_VOICE_SAMPLE_BYTES,
        },
    }


@app.post("/api/voice-samples")
async def upload_voice_sample(file: UploadFile = File(...)) -> dict[str, object]:
    try:
        sample = await voice_samples.save_upload(file)
    except VoiceSampleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await file.close()
    return {
        "id": sample.id,
        "filename": sample.filename,
        "size": len(sample.data),
    }


@app.websocket("/ws")
async def voice_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        settings.validate()
    except ValueError as exc:
        await websocket.send_json({"type": "session.error", "message": str(exc), "recoverable": False})
        await websocket.close(code=1011)
        return
    await VoiceSession(websocket, settings, voice_samples=voice_samples).run()
