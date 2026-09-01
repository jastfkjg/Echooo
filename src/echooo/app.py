from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from echooo.config import ROOT, Settings
from echooo.orchestrator import VoiceSession


settings = Settings.load()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

WEB_DIR = ROOT / "web"
app = FastAPI(title="Echooo", version="0.1.0")
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/health")
async def health() -> dict[str, object]:
    return {"status": "ok", **settings.public_dict()}


@app.get("/api/config")
async def public_config() -> dict[str, object]:
    return settings.public_dict()


@app.websocket("/ws")
async def voice_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        settings.validate()
    except ValueError as exc:
        await websocket.send_json({"type": "session.error", "message": str(exc), "recoverable": False})
        await websocket.close(code=1011)
        return
    await VoiceSession(websocket, settings).run()

