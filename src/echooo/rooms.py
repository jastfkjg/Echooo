from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections import defaultdict

from fastapi import WebSocket

from echooo.auth import Auth, AuthError
from echooo.config import Settings
from echooo.models import STTEventType, VoiceProfile
from echooo.providers.factory import create_stt, create_tts
from echooo.service import Problem, Service


def public_message(m: dict) -> dict:
    return {k: m[k] for k in ("id", "role", "content", "created_at", "delivery")}


class Rooms:
    def __init__(self, service: Service, auth: Auth, settings: Settings):
        self.service, self.auth, self.settings = service, auth, settings
        self.clients: dict[str, set[Connection]] = defaultdict(set)

    async def broadcast(self, sid: str, event: dict):
        for client in tuple(self.clients.get(sid, ())):
            try:
                client.validate()
                await client.send(event)
            except (Problem, AuthError):
                await client.stop("授权已结束或变更。")
            except Exception:
                pass

    async def invalidate(self):
        for clients in list(self.clients.values()):
            for client in tuple(clients):
                try:
                    client.validate()
                except (Problem, AuthError):
                    await client.stop("授权已结束或变更。")

    async def connect(self, ws: WebSocket, owner: str, sid: str, guest: bool, token: str):
        s = self.service.active(owner, sid)
        if guest and s["mode"] != "delegate":
            raise Problem("无权访问", 403)
        connection = Connection(self, ws, owner, sid, guest, token, s["mode"])
        self.clients[sid].add(connection)
        try:
            await connection.run()
        finally:
            self.clients[sid].discard(connection)
            if not self.clients[sid]:
                self.clients.pop(sid, None)


class Connection:
    def __init__(self, rooms, ws, owner, sid, guest, token, mode):
        self.rooms, self.ws, self.owner, self.sid = rooms, ws, owner, sid
        self.guest, self.token, self.mode = guest, token, mode
        self.active = True
        self.stt = None
        self.stt_task = None
        self.reply_task = None
        self.cancel = asyncio.Event()
        self.lock = asyncio.Lock()
        self.can_speak = guest or mode == "private"

    async def send(self, event):
        async with self.lock:
            await self.ws.send_json(event)

    def validate(self):
        self.rooms.service.active(self.owner, self.sid)
        c = self.rooms.auth.resolve(self.token, "guest" if self.guest else "owner")
        if c["owner_id"] != self.owner or (self.guest and c["session_id"] != self.sid):
            raise AuthError("授权已失效")

    async def stop(self, reason):
        if not self.active:
            return
        self.active = False
        self.cancel.set()
        if self.reply_task and self.reply_task is not asyncio.current_task():
            self.reply_task.cancel()
        with contextlib.suppress(Exception):
            await self.send({"type": "playback.stop"})
            await self.send({"type": "session.closed", "message": reason})
            await self.ws.close(code=1000)

    async def watch(self):
        while self.active:
            await asyncio.sleep(0.3)
            try:
                self.validate()
            except (Problem, AuthError):
                await self.stop("本次授权已结束。")

    async def run(self):
        await self.send({"type": "session.ready", "can_speak": self.can_speak,
            **self.rooms.settings.public_dict()})
        watcher = asyncio.create_task(self.watch())
        try:
            while self.active:
                packet = await self.ws.receive()
                if packet["type"] == "websocket.disconnect":
                    break
                self.validate()
                if packet.get("bytes") is not None:
                    if not self.can_speak or len(packet["bytes"]) > 32000:
                        raise Problem("音频未启用或数据帧过大。")
                    if self.stt is None:
                        continue  # In-flight frames can arrive after recognition stops.
                    await self.stt.send_audio(packet["bytes"])
                    continue
                try:
                    raw = packet.get("text", "")
                    if len(raw) > 8000:
                        raise Problem("消息过长。")
                    p = json.loads(raw)
                    if not isinstance(p, dict):
                        raise Problem("消息格式无效。")
                    kind = p.get("type")
                    if kind == "input.text" and self.can_speak:
                        content = p.get("content", "")
                        if not isinstance(content, str) or not 0 < len(content.strip()) <= 6000:
                            raise Problem("请输入 1–6000 字符。")
                        await self.begin_reply(content.strip())
                    elif kind == "audio.enable" and self.can_speak:
                        if self.rooms.settings.stt_provider == "mock":
                            await self.send({"type": "error", "message": "本地演示使用文字输入；配置 AssemblyAI 后可开启麦克风。"})
                            continue
                        if self.stt is None:
                            self.stt = create_stt(self.rooms.settings)
                            try:
                                await self.stt.connect()
                                self.stt_task = asyncio.create_task(self.consume_stt())
                            except Exception:
                                await self.close_stt()
                                await self.send({"type": "audio.error", "message": "语音识别暂不可用，可继续输入文字。"})
                                continue
                        await self.send({"type": "audio.ready", "sample_rate": self.rooms.settings.assemblyai_sample_rate})
                    elif kind == "audio.disable":
                        await self.close_stt()
                    elif kind == "interrupt":
                        await self.interrupt()
                    else:
                        raise Problem("本次角色不支持此操作。", 403)
                except (ValueError, Problem) as exc:
                    await self.send({"type": "error", "message": str(exc)})
        except (Problem, AuthError):
            await self.stop("授权已结束。")
        except Exception:
            with contextlib.suppress(Exception):
                await self.send({"type": "error", "message": "会话连接中断，请重新连接。"})
        finally:
            self.active = False
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher
            await self.interrupt(notify=False)
            await self.close_stt()

    async def close_stt(self):
        if self.stt_task:
            self.stt_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self.stt_task
            self.stt_task = None
        if self.stt:
            with contextlib.suppress(Exception):
                await self.stt.close()
            self.stt = None

    async def consume_stt(self):
        try:
            async for event in self.stt.events():
                self.validate()
                if event.type == STTEventType.SPEECH_STARTED:
                    await self.interrupt()
                elif event.type == STTEventType.PARTIAL:
                    await self.send({"type": "transcript.partial", "content": event.transcript})
                elif event.type == STTEventType.FINAL and event.transcript:
                    await self.begin_reply(event.transcript[:6000])
                elif event.type in {STTEventType.ERROR, STTEventType.TERMINATED}:
                    await self.send({"type": "audio.error", "message": "语音识别暂不可用，可继续输入文字。"})
                    break
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.send({"type": "audio.error", "message": "语音识别连接中断，请重新开启麦克风。"})
        finally:
            if self.stt:
                with contextlib.suppress(Exception):
                    await self.stt.close()
                self.stt = None

    async def interrupt(self, notify=True):
        self.cancel.set()
        if self.reply_task and not self.reply_task.done():
            self.reply_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.reply_task
        self.reply_task = None
        if notify:
            await self.rooms.broadcast(self.sid, {"type": "playback.stop"})

    async def begin_reply(self, content):
        await self.interrupt()
        self.cancel = asyncio.Event()
        self.reply_task = asyncio.create_task(self.respond(content))

    async def respond(self, content):
        start = time.perf_counter()
        try:
            await self.rooms.broadcast(self.sid, {"type": "session.state", "state": "thinking"})
            result = await self.rooms.service.talk(self.owner, self.sid, content, guest=self.guest,
                authorize=self.validate)
            self.validate()
            for m in [result["user"], result["assistant"]]:
                await self.rooms.broadcast(self.sid, {"type": "message", "message": public_message(m)})
            await self.rooms.broadcast(self.sid, {"type": "session.state", "state": "listening",
                "reply_ms": round((time.perf_counter() - start) * 1000), "result": result["kind"]})
            if self.rooms.settings.tts_provider == "cosyvoice":
                tts = create_tts(self.rooms.settings)
                session = self.rooms.service.active(self.owner, self.sid)
                tts.configure_voice(VoiceProfile(mode="sft",
                    speaker_id=session["voice"].get("speaker_id") or self.rooms.settings.cosyvoice_speaker_id))
                await self.send({"type": "audio.start", "sample_rate": tts.sample_rate})
                remainder = b""
                async for chunk in tts.stream_audio(result["assistant"]["content"], cancel=self.cancel):
                    self.validate()
                    if self.cancel.is_set():
                        return
                    data = remainder + chunk.data
                    even = len(data) - len(data) % 2
                    remainder = data[even:]
                    if even:
                        async with self.lock:
                            await self.ws.send_bytes(data[:even])
                await self.send({"type": "audio.end"})
            else:
                self.validate()
                await self.send({"type": "speech.checked", "content": result["assistant"]["content"]})
        except asyncio.CancelledError:
            raise
        except (Problem, AuthError):
            await self.stop("本次授权已结束。")
        except Exception:
            with contextlib.suppress(Exception):
                await self.send({"type": "error", "message": "语音输出暂不可用，已核验的回复保留在文字记录中。"})
                await self.send({"type": "session.state", "state": "listening"})
