from __future__ import annotations

import asyncio
import contextlib
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError

from echooo import database as db
from echooo.auth import Auth, AuthError
from echooo.config import ROOT, Settings
from echooo.contracts import (Credentials, DomainInput, MemoryInput, SourceInput,
    SessionInput, SessionRenameInput, SessionVoiceInput, MessageInput, ReviewInput,
    DecisionInput, InviteInput, SaveConversationMemory)
from echooo.ingestion import MAX_UPLOAD, extract_file
from echooo.intelligence import Intelligence
from echooo.rooms import Rooms, public_message
from echooo.service import Service, Problem, need
from echooo.providers.tts.dashscope_voices import (
    MAX_VOICE_SAMPLE, DashScopeVoiceError, DashScopeVoiceManager,
)


def create_app(settings: Settings | None = None, store: db.Store | None = None) -> FastAPI:
    settings = settings or Settings.load()
    settings.validate()
    store = store or db.Store(settings.database_url)
    auth = Auth(store)
    service = Service(store, Intelligence(settings))
    rooms = Rooms(service, auth, settings)
    voice_manager = DashScopeVoiceManager(settings) if settings.tts_provider == "dashscope" else None

    @asynccontextmanager
    async def lifespan(app):
        yield
        for clients in list(rooms.clients.values()):
            for client in tuple(clients):
                await client.stop("The service is shutting down.")
        store.close()

    app = FastAPI(title="Echooo · Scoped personal representative", version="0.2.0", lifespan=lifespan)
    app.state.store, app.state.auth, app.state.service, app.state.rooms = store, auth, service, rooms
    app.state.voice_manager = voice_manager
    app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")

    def same_origin(origin: str | None, base: str) -> bool:
        return not origin or origin.rstrip("/") == (settings.public_origin or base).rstrip("/")

    @app.middleware("http")
    async def security(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"} and (
            request.headers.get("sec-fetch-site") == "cross-site" or
            not same_origin(request.headers.get("origin"), str(request.base_url))):
            return JSONResponse({"detail": "Cross-site requests are not allowed."}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = ("default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; media-src 'self' blob:; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        return response

    @app.exception_handler(Problem)
    async def problem_handler(request, exc):
        return JSONResponse({"detail": exc.message}, status_code=exc.status)

    @app.exception_handler(AuthError)
    async def auth_handler(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=401)

    @app.exception_handler(IntegrityError)
    async def conflict_handler(request, exc):
        return JSONResponse({"detail": "A record conflict occurred. Refresh and try again."}, status_code=409)

    def owner(request: Request) -> str:
        return auth.resolve(request.cookies.get("echooo_owner"), "owner")["owner_id"]

    def guest(request: Request, sid: str) -> str:
        c = auth.resolve(request.cookies.get("echooo_guest"), "guest")
        if c["session_id"] != sid:
            raise Problem("This invitation does not belong to this conversation.", 403)
        service.active(c["owner_id"], sid)
        return c["owner_id"]

    def with_cookie(payload, token, kind="owner", ttl=86400 * 7):
        response = JSONResponse(payload)
        response.set_cookie("echooo_" + kind, token, httponly=True, secure=settings.cookie_secure,
            samesite="strict", max_age=int(ttl), path="/")
        return response

    @app.get("/", include_in_schema=False)
    @app.get("/invite", include_in_schema=False)
    @app.get("/room/{sid}", include_in_schema=False)
    async def index():
        return FileResponse(ROOT / "web" / "index.html")

    @app.get("/health")
    async def health():
        return {"status": "ok", "version": "0.2.0"}

    @app.get("/api/auth")
    async def auth_status(request: Request):
        user = None
        with contextlib.suppress(AuthError):
            c = auth.resolve(request.cookies.get("echooo_owner"), "owner")
            user = {"id": c["owner_id"], "name": c["name"]}
        return {"needs_setup": auth.needs_setup(), "user": user}

    @app.post("/api/auth/setup")
    async def setup(data: Credentials):
        user, token = await asyncio.to_thread(auth.setup, data.name, data.password)
        return with_cookie({"user": user}, token)

    @app.post("/api/auth/login")
    async def login(request: Request, data: Credentials):
        user, token = await asyncio.to_thread(auth.login, data.name, data.password,
            request.client.host if request.client else "unknown")
        return with_cookie({"user": user}, token)

    @app.post("/api/auth/logout")
    async def logout(request: Request):
        auth.revoke(request.cookies.get("echooo_owner"))
        response = JSONResponse({"ok": True})
        response.delete_cookie("echooo_owner")
        return response

    @app.get("/api/config")
    async def config(request: Request):
        owner(request)
        return {**settings.public_dict(), "demo": settings.llm_provider == "mock",
            "database": "postgresql" if store.postgres else "sqlite", "version": "0.2.0"}

    def merge_voice_catalogue(custom: list[dict]) -> list[dict]:
        options = settings.dashscope_voice_options()
        known = {str(option["id"]) for option in options}
        options.extend(voice for voice in custom
            if voice["id"] not in known and voice.get("status") == "OK")
        return options

    def voice_payload(custom: list[dict], **extra) -> dict:
        return {"model": settings.dashscope_tts_model,
            "default_voice": settings.dashscope_tts_voice,
            "voices": merge_voice_catalogue(custom), "custom_voices": custom, **extra}

    async def voice_catalogue() -> list[dict]:
        manager = app.state.voice_manager
        if settings.tts_provider != "dashscope" or manager is None:
            raise Problem("Custom voice management is unavailable for the configured TTS provider.", 409)
        try:
            custom = await manager.list_voices()
        except DashScopeVoiceError as exc:
            raise Problem(str(exc), 503) from exc
        return merge_voice_catalogue(custom)

    @app.get("/api/tts/voices")
    async def list_tts_voices(request: Request):
        owner(request)
        try:
            await voice_catalogue()
            manager = app.state.voice_manager
            return voice_payload(manager.cached_voices if manager else [],
                management_available=True)
        except Problem as exc:
            return voice_payload([], management_available=False, management_error=exc.message)

    @app.post("/api/tts/voices/clone", status_code=201)
    async def clone_tts_voice(request: Request,
        prefix: str = Form(...), language: str = Form("zh"),
        enable_preprocess: bool = Form(False), file: UploadFile = File(...)):
        owner(request)
        manager = app.state.voice_manager
        if settings.tts_provider != "dashscope" or manager is None:
            raise Problem("Custom voice management is unavailable for the configured TTS provider.", 409)
        try:
            data = await file.read(MAX_VOICE_SAMPLE + 1)
            voice = await manager.create_voice(prefix=prefix.strip(), language=language,
                filename=Path(file.filename or "sample").name, data=data,
                enable_preprocess=enable_preprocess)
            return voice_payload(manager.cached_voices, voice=voice)
        except ValueError as exc:
            raise Problem(str(exc), 422) from exc
        except DashScopeVoiceError as exc:
            raise Problem(str(exc), 503) from exc
        finally:
            await file.close()

    @app.delete("/api/tts/voices/{voice_id}")
    async def delete_tts_voice(request: Request, voice_id: str):
        who = owner(request)
        manager = app.state.voice_manager
        if settings.tts_provider != "dashscope" or manager is None:
            raise Problem("Custom voice management is unavailable for the configured TTS provider.", 409)
        if voice_id in {option["id"] for option in settings.dashscope_voice_options()
            if not option.get("custom")}:
            raise Problem("Built-in voices cannot be deleted.", 409)
        try:
            await manager.delete_voice(voice_id)
            reset = service.reset_session_voices(who, voice_id, settings.dashscope_tts_voice)
            return voice_payload(manager.cached_voices, ok=True, reset_sessions=reset)
        except ValueError as exc:
            raise Problem(str(exc), 404) from exc
        except DashScopeVoiceError as exc:
            raise Problem(str(exc), 503) from exc

    @app.get("/api/domains")
    async def list_domains(request: Request):
        return service.domains(owner(request))

    @app.post("/api/domains", status_code=201)
    async def new_domain(request: Request, data: DomainInput):
        return service.create_domain(owner(request), data)

    @app.put("/api/domains/{did}")
    async def edit_domain(request: Request, did: str, data: DomainInput):
        result = service.update_domain(owner(request), did, data)
        await rooms.invalidate()
        return result

    @app.delete("/api/domains/{did}")
    async def remove_domain(request: Request, did: str):
        who = owner(request)
        for sid in service.delete_domain(who, did):
            auth.revoke_room(who, sid)
        await rooms.invalidate()
        return {"ok": True}

    @app.get("/api/domains/{did}/memories")
    async def list_memories(request: Request, did: str):
        return service.memories(owner(request), did)

    @app.post("/api/domains/{did}/memories", status_code=201)
    async def new_memory(request: Request, did: str, data: MemoryInput):
        return service.create_memory(owner(request), did, data)

    @app.put("/api/memories/{mid}")
    async def edit_memory(request: Request, mid: str, data: MemoryInput):
        result = service.update_memory(owner(request), mid, data)
        await rooms.invalidate()
        return result

    @app.get("/api/memories/{mid}/versions")
    async def memory_versions(request: Request, mid: str):
        with store.scope(owner(request)) as r:
            need(r.get(db.memories, mid), "Memory")
            return r.list(db.versions, db.versions.c.memory_id == mid)

    @app.delete("/api/memories/{mid}")
    async def remove_memory(request: Request, mid: str):
        service.delete_memory(owner(request), mid)
        await rooms.invalidate()
        return {"ok": True}

    @app.get("/api/domains/{did}/sources")
    async def list_sources(request: Request, did: str):
        with store.scope(owner(request)) as r:
            need(r.get(db.domains, did), "Domain")
            return r.list(db.sources, db.sources.c.domain_id == did)

    @app.post("/api/domains/{did}/sources", status_code=201)
    async def new_source(request: Request, did: str, data: SourceInput):
        return service.source(owner(request), did, data.title, data.content)

    @app.post("/api/domains/{did}/upload", status_code=201)
    async def upload(request: Request, did: str, file: UploadFile = File(...)):
        who = owner(request)
        try:
            data = await file.read(MAX_UPLOAD + 1)
            filename = Path(file.filename or "document.txt").name[:150]
            content = await asyncio.to_thread(extract_file, filename, data)
            return service.source(who, did, filename, content, "upload")
        finally:
            await file.close()

    @app.post("/api/sources/{source_id}/extract")
    async def extract(request: Request, source_id: str):
        try:
            return await service.extract_source(owner(request), source_id)
        except (Problem, AuthError):
            raise
        except Exception as exc:
            raise Problem("Extraction is unavailable. Your source is saved; try again later or add memories manually.", 503) from exc

    @app.delete("/api/sources/{source_id}")
    async def remove_source(request: Request, source_id: str):
        service.delete_source(owner(request), source_id)
        await rooms.invalidate()
        return {"ok": True}

    @app.get("/api/proposals")
    async def list_proposals(request: Request):
        with store.scope(owner(request)) as r:
            return r.list(db.proposals)

    @app.post("/api/proposals/{pid}/review")
    async def review(request: Request, pid: str, data: ReviewInput):
        result = service.review(owner(request), pid, data)
        await rooms.invalidate()
        return result

    @app.get("/api/sessions")
    async def list_sessions(request: Request):
        return service.list_sessions(owner(request))

    @app.post("/api/sessions", status_code=201)
    async def new_session(request: Request, data: SessionInput):
        return service.create_session(owner(request), data)

    @app.post("/api/sessions/quick-chat", status_code=201)
    async def quick_chat(request: Request):
        return service.quick_chat(owner(request))

    @app.get("/api/sessions/{sid}")
    async def session(request: Request, sid: str):
        return service.view_session(owner(request), sid)

    @app.patch("/api/sessions/{sid}")
    async def rename_session(request: Request, sid: str, data: SessionRenameInput):
        return service.rename_session(owner(request), sid, data.title)

    @app.patch("/api/sessions/{sid}/voice")
    async def update_session_voice(request: Request, sid: str, data: SessionVoiceInput):
        who = owner(request)
        if settings.tts_provider != "dashscope":
            raise Problem("Cloud voice selection is unavailable for the configured TTS provider.", 409)
        if data.dashscope_voice not in settings.dashscope_voice_ids():
            manager = app.state.voice_manager
            if manager is None or data.dashscope_voice not in manager.known_voice_ids:
                raise Problem("Choose a voice available for the configured model and region.", 422)
        return service.update_session_voice(who, sid, data.dashscope_voice)

    @app.delete("/api/sessions/{sid}")
    async def delete_session(request: Request, sid: str):
        who = owner(request)
        service.delete_session(who, sid)
        auth.revoke_room(who, sid)
        await rooms.invalidate()
        return {"ok": True}

    @app.post("/api/sessions/{sid}/invite")
    async def invite(request: Request, sid: str):
        who = owner(request)
        s = service.active(who, sid)
        if s["mode"] != "delegate":
            raise Problem("Private conversations cannot have guests.")
        auth.revoke_room(who, sid)
        await rooms.invalidate()
        token = auth.issue(who, "invite", s["expires_at"] - time.time(), sid)
        return {"token": token, "expires_at": s["expires_at"]}

    @app.post("/api/guest/join")
    async def join(data: InviteInput):
        c = auth.consume_invite(data.token)
        s = service.active(c["owner_id"], c["session_id"])
        if s["mode"] != "delegate":
            raise Problem("This invitation is unavailable.", 403)
        ttl = s["expires_at"] - time.time()
        token = auth.issue(c["owner_id"], "guest", ttl, s["id"])
        return with_cookie({"session_id": s["id"]}, token, "guest", ttl)

    @app.get("/api/guest/sessions/{sid}")
    async def guest_session(request: Request, sid: str):
        view = service.view_session(guest(request, sid), sid, guest=True)
        return {**view, "demo": settings.llm_provider == "mock", "stt": settings.stt_provider}

    @app.post("/api/sessions/{sid}/messages")
    async def owner_message(request: Request, sid: str, data: MessageInput):
        result = await service.talk(owner(request), sid, data.content, guest=False,
            authorize=lambda: owner(request))
        for m in (result["user"], result["assistant"]):
            await rooms.broadcast(sid, {"type": "message", "message": public_message(m)})
        return result

    @app.post("/api/guest/sessions/{sid}/messages")
    async def guest_message(request: Request, sid: str, data: MessageInput):
        result = await service.talk(guest(request, sid), sid, data.content, guest=True,
            authorize=lambda: guest(request, sid))
        for m in (result["user"], result["assistant"]):
            await rooms.broadcast(sid, {"type": "message", "message": public_message(m)})
        return {"user": public_message(result["user"]), "assistant": public_message(result["assistant"]), "kind": result["kind"]}

    @app.post("/api/sessions/{sid}/notes")
    async def note(request: Request, sid: str, data: MessageInput):
        return service.private_note(owner(request), sid, data.content)

    @app.post("/api/sessions/{sid}/memory-proposals", status_code=201)
    async def save_chat_memory(request: Request, sid: str, data: SaveConversationMemory):
        return service.save_conversation_memory(owner(request), sid, data)

    @app.post("/api/actions/{aid}/decision")
    async def decision(request: Request, aid: str, data: DecisionInput):
        m = service.decide(owner(request), aid, data.decision, data.response)
        await rooms.broadcast(m["session_id"], {"type": "message", "message": public_message(m)})
        await rooms.broadcast(m["session_id"], {"type": "speech.checked", "content": m["content"]})
        return m

    @app.post("/api/sessions/{sid}/end")
    async def end(request: Request, sid: str):
        who = owner(request)
        service.stop(who, sid, "ended")
        auth.revoke_room(who, sid)
        await rooms.invalidate()
        warning = None
        try:
            await service.learn_session(who, sid)
        except Exception:
            warning = "The conversation has ended. Memory extraction is incomplete; retry from the conversation review."
        return {**service.view_session(who, sid), "warning": warning}

    @app.post("/api/sessions/{sid}/revoke")
    async def revoke(request: Request, sid: str):
        who = owner(request)
        service.stop(who, sid, "revoked")
        auth.revoke_room(who, sid)
        await rooms.invalidate()
        return service.view_session(who, sid)

    @app.post("/api/sessions/{sid}/learn")
    async def learn(request: Request, sid: str):
        try:
            return await service.learn_session(owner(request), sid)
        except (Problem, AuthError):
            raise
        except Exception as exc:
            raise Problem("Memory extraction is unavailable. Please try again later.", 503) from exc

    @app.get("/api/export")
    async def export(request: Request):
        with store.scope(owner(request)) as r:
            result = {t.name: r.list(t) for t in db.OWNED}
            result["exported_at"] = time.time()
            return JSONResponse(result, headers={"Content-Disposition": 'attachment; filename="echooo-export.json"'})

    @app.websocket("/ws/sessions/{sid}")
    async def socket(ws: WebSocket, sid: str):
        is_guest = ws.query_params.get("role", "owner") == "guest"
        token = ws.cookies.get("echooo_guest" if is_guest else "echooo_owner")
        base = ("https" if ws.url.scheme == "wss" else "http") + "://" + ws.url.netloc
        try:
            if not same_origin(ws.headers.get("origin"), base):
                raise AuthError("Cross-site connections are not allowed")
            c = auth.resolve(token, "guest" if is_guest else "owner")
            if is_guest and c["session_id"] != sid:
                raise AuthError("You do not have access to this conversation")
            service.active(c["owner_id"], sid)
        except (AuthError, Problem):
            await ws.close(code=1008)
            return
        await ws.accept()
        await rooms.connect(ws, c["owner_id"], sid, is_guest, token)

    return app


app = create_app()
