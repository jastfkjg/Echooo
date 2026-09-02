from __future__ import annotations

import asyncio
import time
from collections import defaultdict

from sqlalchemy import update

from echooo import database as db
from echooo.contracts import DomainInput, MemoryInput, SessionInput, ReviewInput
from echooo.intelligence import FALLBACK, Intelligence


class Problem(Exception):
    def __init__(self, message: str, status: int = 400):
        self.message, self.status = message, status
        super().__init__(message)


def need(item: dict | None, label: str = "记录") -> dict:
    if item is None:
        raise Problem(f"{label}不存在或无权访问。", 404)
    return item


def memory_values(data: MemoryInput) -> dict:
    values = data.model_dump(exclude={"expected_version"})
    if values["expires_at"] is not None and values["expires_at"] <= time.time():
        raise Problem("有效期必须晚于当前时间。")
    return values


class Service:
    def __init__(self, store: db.Store, intelligence: Intelligence):
        self.store, self.ai = store, intelligence
        self.turn_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.learning_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def domains(self, owner: str) -> list[dict]:
        with self.store.scope(owner) as r:
            records = r.list(db.domains)
            facts = r.list(db.memories)
            pending = r.list(db.proposals, db.proposals.c.status == "pending")
            return [{**d, "memory_count": sum(f["domain_id"] == d["id"] for f in facts),
                "pending_count": sum(p["domain_id"] == d["id"] for p in pending)} for d in records]

    def create_domain(self, owner: str, data: DomainInput) -> dict:
        with self.store.scope(owner) as r:
            if r.list(db.domains, db.domains.c.name == data.name):
                raise Problem("已有同名领域。", 409)
            d = r.add(db.domains, **data.model_dump())
            r.log("domain.created", domain_id=d["id"])
            return d

    def update_domain(self, owner: str, item_id: str, data: DomainInput) -> dict:
        with self.store.scope(owner) as r:
            need(r.get(db.domains, item_id), "领域")
            if r.list(db.domains, db.domains.c.name == data.name, db.domains.c.id != item_id):
                raise Problem("已有同名领域。", 409)
            r.change(db.domains, item_id, **data.model_dump())
            self._invalidate(r, domain_id=item_id)
            r.log("domain.updated", domain_id=item_id)
            return need(r.get(db.domains, item_id))

    def delete_domain(self, owner: str, item_id: str) -> list[str]:
        with self.store.scope(owner) as r:
            need(r.get(db.domains, item_id), "领域")
            affected = [s["id"] for s in r.list(db.sessions) if item_id in s["domain_ids"]]
            self._purge(r, session_ids=set(affected), memory_ids={m["id"] for m in r.list(db.memories, db.memories.c.domain_id == item_id)})
            r.remove(db.domains, item_id)
            # Tombstone contains no deleted name, content, or identifier.
            r.log("domain.deleted", affected_sessions=len(affected))
            return affected

    def _purge(self, r, *, session_ids=None, memory_ids=None):
        """Conservatively remove transitive copies in conversations and memories.

        Version snapshots count as lineage: replacing a memory does not erase the
        origin of the historical copy. Deletion must not leave that copy retrievable.
        """
        session_ids, memory_ids = set(session_ids or ()), set(memory_ids or ())
        all_sessions, all_memories = r.list(db.sessions), r.list(db.memories)
        snapshots = r.list(db.versions)
        changed = True
        while changed:
            before = (len(session_ids), len(memory_ids))
            for s in all_sessions:
                if set(s["read_ids"]) & memory_ids:
                    session_ids.add(s["id"])
            for m in all_memories:
                if m["provenance"].get("session_id") in session_ids:
                    memory_ids.add(m["id"])
            for v in snapshots:
                if v["snapshot"].get("provenance", {}).get("session_id") in session_ids:
                    memory_ids.add(v["memory_id"])
            changed = before != (len(session_ids), len(memory_ids))
        for sid in session_ids:
            r.remove(db.sessions, sid)
        for mid in memory_ids:
            r.remove(db.memories, mid)

    def _invalidate(self, r, *, memory_id=None, domain_id=None):
        for s in r.list(db.sessions, db.sessions.c.status == "active"):
            if (memory_id and memory_id in s["read_ids"]) or (domain_id and domain_id in s["domain_ids"]):
                r.change(db.sessions, s["id"], status="revoked")
                r.log("session.revoked", session_id=s["id"], reason="knowledge_changed")

    def memories(self, owner: str, domain: str) -> list[dict]:
        with self.store.scope(owner) as r:
            need(r.get(db.domains, domain), "领域")
            return r.list(db.memories, db.memories.c.domain_id == domain)

    def create_memory(self, owner: str, domain: str, data: MemoryInput) -> dict:
        with self.store.scope(owner) as r:
            need(r.get(db.domains, domain), "领域")
            m = r.add(db.memories, domain_id=domain, **memory_values(data), source_id=None,
                provenance={"kind": "owner", "note": "本人直接确认"}, version=1, updated_at=time.time())
            r.add(db.versions, domain_id=domain, memory_id=m["id"], version=1, snapshot=m)
            r.log("memory.created", domain_id=domain, memory_id=m["id"])
            return m

    def update_memory(self, owner: str, mid: str, data: MemoryInput) -> dict:
        with self.store.scope(owner) as r:
            m = need(r.get(db.memories, mid), "记忆")
            result = self._replace_memory(r, m, data, m["provenance"])
            self._invalidate(r, memory_id=mid)
            return result

    def _replace_memory(self, r, current: dict, data: MemoryInput, provenance: dict) -> dict:
        if data.expected_version != current["version"]:
            raise Problem("记忆已发生变化，请查看最新版本后重新确认。", 409)
        values = {**memory_values(data), "version": current["version"] + 1,
            "updated_at": time.time(), "provenance": provenance}
        result = r.c.execute(update(db.memories).where(db.memories.c.owner_id == r.owner,
            db.memories.c.id == current["id"], db.memories.c.version == data.expected_version).values(**values))
        if result.rowcount != 1:
            raise Problem("记忆已被其他操作更新，请重试。", 409)
        m = {**current, **values}
        r.add(db.versions, domain_id=m["domain_id"], memory_id=m["id"], version=m["version"], snapshot=m)
        r.log("memory.updated", domain_id=m["domain_id"], memory_id=m["id"], version=m["version"])
        return m

    def delete_memory(self, owner: str, mid: str):
        with self.store.scope(owner) as r:
            m = need(r.get(db.memories, mid), "记忆")
            self._purge(r, memory_ids={mid})
            r.log("memory.deleted", domain_id=m["domain_id"])

    def source(self, owner: str, domain: str, title: str, content: str, kind="text") -> dict:
        with self.store.scope(owner) as r:
            need(r.get(db.domains, domain), "领域")
            if not content.strip() or len(content) > 100000:
                raise Problem("资料为空或超过 100,000 字符。")
            item = r.add(db.sources, domain_id=domain, title=title, content=content, kind=kind)
            r.log("source.created", domain_id=domain, source_id=item["id"])
            return item

    async def extract_source(self, owner: str, source_id: str) -> list[dict]:
        async with self.learning_locks[source_id]:
            with self.store.scope(owner) as r:
                source = need(r.get(db.sources, source_id), "资料")
                existing = r.list(db.proposals, db.proposals.c.source_id == source_id)
                if existing:
                    return existing
            chunks = [source["content"][i:i+4000] for i in range(0, len(source["content"]), 4000)]
            records = [{"id": f"{source_id}:{i}", "content": s, "speaker": "本人导入资料"} for i, s in enumerate(chunks)]
            extracted = await self.ai.extract(records)
            with self.store.scope(owner) as r:
                need(r.get(db.sources, source_id), "资料")  # deletion during model call
                existing = r.list(db.proposals, db.proposals.c.source_id == source_id)
                if existing:
                    return existing
                by_id = {x["id"]: x for x in records}
                return [r.add(db.proposals, domain_id=source["domain_id"], source_id=source_id,
                    session_id=None, title=p["title"], content=p["content"], status="pending",
                    evidence=[by_id[i] for i in p["evidence_ids"]], target_id=None,
                    expected_version=None, result_id=None) for p in extracted]

    def delete_source(self, owner: str, source_id: str):
        with self.store.scope(owner) as r:
            source = need(r.get(db.sources, source_id), "资料")
            ids = {m["id"] for m in r.list(db.memories) if m["source_id"] == source_id or m["provenance"].get("source_id") == source_id}
            ids.update(v["memory_id"] for v in r.list(db.versions)
                if v["snapshot"].get("source_id") == source_id or v["snapshot"].get("provenance", {}).get("source_id") == source_id)
            self._purge(r, memory_ids=ids)
            r.remove(db.sources, source_id)
            r.log("source.deleted", domain_id=source["domain_id"])

    def create_session(self, owner: str, data: SessionInput) -> dict:
        with self.store.scope(owner) as r:
            for domain in data.domain_ids:
                need(r.get(db.domains, domain), "领域")
            facts = []
            for mid in data.read_ids:
                m = need(r.get(db.memories, mid), "记忆")
                if m["domain_id"] not in data.domain_ids:
                    raise Problem("读取记忆超出了选定领域。", 403)
                if m["expires_at"] and m["expires_at"] <= time.time():
                    raise Problem("选定记忆已过期。", 409)
                if mid in data.disclose_ids and not self._disclosable(m, data.audience):
                    raise Problem("选定记忆未获准向此交流对象披露。", 403)
                facts.append(m)
            values = data.model_dump(exclude={"duration_minutes"})
            if data.mode == "private":
                values["disclose_ids"] = []
            s = r.add(db.sessions, **values, status="active", expires_at=time.time() + data.duration_minutes * 60,
                grants={m["id"]: m["version"] for m in facts}, summary={})
            r.log("session.created", session_id=s["id"], domain_ids=data.domain_ids,
                disclose_count=len(s["disclose_ids"]), action_policy=data.action_policy)
            return s

    @staticmethod
    def _disclosable(m: dict, audience: str) -> bool:
        return (m["visibility"] == "shareable" and (not m["audiences"] or audience in m["audiences"])
            and (not m["expires_at"] or m["expires_at"] > time.time()))

    def _active(self, r, sid: str) -> dict:
        s = need(r.get(db.sessions, sid), "会话")
        if s["status"] != "active" or s["expires_at"] <= time.time():
            raise Problem("会话已结束、过期或被撤销。", 410)
        for domain in s["domain_ids"]:
            need(r.get(db.domains, domain), "领域")
        for mid, version in s["grants"].items():
            m = r.get(db.memories, mid)
            if not m or m["version"] != version or (m["expires_at"] and m["expires_at"] <= time.time()):
                raise Problem("授权资料已变化，请由本人创建新会话。", 410)
            if mid in s["disclose_ids"] and not self._disclosable(m, s["audience"]):
                raise Problem("披露授权已变化。", 410)
        return s

    def active(self, owner: str, sid: str) -> dict:
        with self.store.scope(owner) as r:
            return self._active(r, sid)

    def view_session(self, owner: str, sid: str, *, guest=False) -> dict:
        with self.store.scope(owner) as r:
            s = need(r.get(db.sessions, sid), "会话")
            if guest:
                self._active(r, sid)
                if s["mode"] != "delegate":
                    raise Problem("不能访问私人会话。", 403)
                return {"id": s["id"], "title": s["title"], "audience": s["audience"],
                    "status": s["status"], "expires_at": s["expires_at"], "messages": self._public_messages(r, sid)}
            return {**s, "messages": r.list(db.messages, db.messages.c.session_id == sid),
                "actions": r.list(db.actions, db.actions.c.session_id == sid),
                "proposals": r.list(db.proposals, db.proposals.c.session_id == sid),
                "audit": r.list(db.audit, db.audit.c.session_id == sid)}

    @staticmethod
    def _public_messages(r, sid):
        return [{k: m[k] for k in ("id", "role", "content", "created_at", "delivery")}
            for m in r.list(db.messages, db.messages.c.session_id == sid) if m["role"] != "private_note"]

    async def talk(self, owner: str, sid: str, content: str, *, guest: bool, authorize=None) -> dict:
        async with self.turn_locks[sid]:
            if authorize:
                authorize()
            with self.store.scope(owner) as r:
                s = self._active(r, sid)
                if guest and s["mode"] != "delegate":
                    raise Problem("无权访问私人会话。", 403)
                if not guest and s["mode"] == "delegate":
                    raise Problem("委托会话请通过访客入口发言；私人指示不会发送给对方。", 403)
                history = r.list(db.messages, db.messages.c.session_id == sid,
                    db.messages.c.role != "private_note")
                if len(history) >= 200:
                    raise Problem("本次会话已达 100 轮，请结束并创建新会话。", 409)
                permitted = s["disclose_ids"] if s["mode"] == "delegate" else s["read_ids"]
                facts = [need(r.get(db.memories, mid)) for mid in permitted]
                speaker = "guest" if guest else "owner"
                user_message = r.add(db.messages, session_id=sid, role=speaker, content=content,
                    citations=[], delivery="received")
            try:
                reply = await self.ai.reply(query=content, facts=facts, history=history, mode=s["mode"],
                    audience=s["audience"], goal=s["goal"], action_policy=s["action_policy"])
            except asyncio.CancelledError:
                raise
            except Exception:
                # Never expose vendor errors, endpoints, request context or keys.
                reply = {"kind": "unavailable", "reply": "暂时无法核验回复，请稍后重试或联系本人。", "citations": []}
            if authorize:
                authorize()  # Invitation rotation/logout can revoke a caller without ending the room.
            with self.store.scope(owner) as r:
                s = self._active(r, sid)  # check AFTER generation, before ANY output
                if not set(reply.get("citations", [])) <= set(permitted):
                    reply = {"kind": "clarify", "reply": FALLBACK, "citations": []}
                if reply["kind"] == "approval":
                    if s["action_policy"] == "none":
                        reply["reply"] = "本次授权仅限信息交流，我不能代表本人作出决定。"
                    else:
                        r.add(db.actions, session_id=sid, request=content, status="pending", response="")
                assistant = r.add(db.messages, session_id=sid, role="assistant", content=reply["reply"],
                    citations=reply.get("citations", []), delivery="checked")
                r.log("reply.checked", session_id=sid, kind_result=reply["kind"],
                    message_id=assistant["id"], memory_ids=reply.get("citations", []))
                return {"user": user_message, "assistant": assistant, "kind": reply["kind"]}

    def private_note(self, owner: str, sid: str, content: str):
        with self.store.scope(owner) as r:
            self._active(r, sid)
            return r.add(db.messages, session_id=sid, role="private_note", content=content,
                citations=[], delivery="owner_only")

    def decide(self, owner: str, aid: str, decision: str, response: str) -> dict:
        with self.store.scope(owner) as r:
            a = need(r.get(db.actions, aid), "确认请求")
            self._active(r, a["session_id"])
            if decision == "approve" and not response.strip():
                raise Problem("请明确填写获准向对方表达的内容。")
            status = "approved" if decision == "approve" else "rejected"
            result = r.c.execute(update(db.actions).where(db.actions.c.owner_id == owner,
                db.actions.c.id == aid, db.actions.c.status == "pending").values(status=status, response=response))
            if result.rowcount != 1:
                raise Problem("该请求已经处理。", 409)
            text = response.strip() if response.strip() else "本人未批准这项请求，暂不作出承诺。"
            message = r.add(db.messages, session_id=a["session_id"], role="owner_approved",
                content=text, citations=[], delivery="approved")
            r.log("action." + status, session_id=a["session_id"], action_id=aid, message_id=message["id"])
            return message

    def stop(self, owner: str, sid: str, status: str):
        with self.store.scope(owner) as r:
            s = need(r.get(db.sessions, sid), "会话")
            if s["status"] == "active" or status == "revoked":
                r.change(db.sessions, sid, status=status)
                r.log("session." + status, session_id=sid)
            # A summary is an attributed activity record, never a global biography.
            records = r.list(db.messages, db.messages.c.session_id == sid)
            summary = {
                "statements": [{"speaker": m["role"], "text": m["content"], "message_id": m["id"]}
                    for m in records if m["role"] in {"guest", "owner", "owner_approved"}],
                "unresolved": [a["request"] for a in r.list(db.actions, db.actions.c.session_id == sid,
                    db.actions.c.status == "pending")],
                "checked_replies": sum(m["role"] == "assistant" for m in records),
            }
            r.change(db.sessions, sid, summary=summary)

    async def learn_session(self, owner: str, sid: str) -> list[dict]:
        async with self.learning_locks[sid]:
            with self.store.scope(owner) as r:
                s = need(r.get(db.sessions, sid), "会话")
                if not s["allow_learning"]:
                    return []
                if s["status"] != "ended":
                    raise Problem("请先结束会话；撤销的会话不会自动学习。", 409)
                existing = r.list(db.proposals, db.proposals.c.session_id == sid)
                if existing:
                    return existing
                records = [{"id": m["id"], "speaker": s["audience"] if m["role"] == "guest" else "本人",
                    "content": m["content"]} for m in r.list(db.messages, db.messages.c.session_id == sid)
                    if m["role"] in {"guest", "owner", "owner_approved"}]
            extracted = await self.ai.extract(records)
            with self.store.scope(owner) as r:
                s = need(r.get(db.sessions, sid), "会话")
                if s["status"] != "ended" or not s["allow_learning"]:
                    raise Problem("学习授权已撤销。", 410)
                existing = r.list(db.proposals, db.proposals.c.session_id == sid)
                if existing:
                    return existing
                by_id = {x["id"]: x for x in records}
                result = []
                for p in extracted:
                    evidence = [by_id[i] for i in p["evidence_ids"]]
                    speakers = "、".join(dict.fromkeys(x["speaker"] for x in evidence))
                    result.append(r.add(db.proposals, domain_id=s["write_domain_id"], session_id=sid,
                        source_id=None, title=p["title"], content=f"{speakers}在本次交流中表示：{p['content']}",
                        evidence=evidence, status="pending", target_id=None, expected_version=None, result_id=None))
                r.log("memory.proposed", session_id=sid, count=len(result))
                return result

    def review(self, owner: str, pid: str, data: ReviewInput) -> dict:
        with self.store.scope(owner) as r:
            p = need(r.get(db.proposals, pid), "更新建议")
            if p["status"] != "pending":
                raise Problem("此更新已处理。", 409)
            status = "approved" if data.decision == "approve" else "rejected"
            claim = r.c.execute(update(db.proposals).where(db.proposals.c.owner_id == owner,
                db.proposals.c.id == pid, db.proposals.c.status == "pending").values(status=status))
            if claim.rowcount != 1:
                raise Problem("此更新已被处理。", 409)
            result = None
            if data.decision == "approve":
                content = MemoryInput(**data.model_dump(exclude={"decision", "target_id"}))
                provenance = {"kind": "reviewed", "proposal_id": pid, "evidence": p["evidence"],
                    "session_id": p["session_id"], "source_id": p["source_id"]}
                if data.target_id:
                    current = need(r.get(db.memories, data.target_id), "目标记忆")
                    if current["domain_id"] != p["domain_id"]:
                        raise Problem("更新不能跨领域写入。", 403)
                    result = self._replace_memory(r, current, content, provenance)
                    self._invalidate(r, memory_id=current["id"])
                else:
                    result = r.add(db.memories, domain_id=p["domain_id"], **memory_values(content),
                        source_id=p["source_id"], provenance=provenance, version=1, updated_at=time.time())
                    r.add(db.versions, domain_id=p["domain_id"], memory_id=result["id"], version=1, snapshot=result)
                r.change(db.proposals, pid, result_id=result["id"])
            r.log("proposal." + status, domain_id=p["domain_id"], proposal_id=pid)
            return {"status": status, "memory": result}
