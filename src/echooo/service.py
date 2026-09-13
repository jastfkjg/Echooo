from __future__ import annotations

import asyncio
import time
from collections import defaultdict

from sqlalchemy import func, select, update

from echooo import database as db
from echooo.contracts import DomainInput, MemoryInput, SessionInput, ReviewInput, SaveConversationMemory
from echooo.intelligence import FALLBACK, Intelligence


class Problem(Exception):
    def __init__(self, message: str, status: int = 400):
        self.message, self.status = message, status
        super().__init__(message)


def need(item: dict | None, label: str = "Record") -> dict:
    if item is None:
        raise Problem(f"{label} was not found or is not accessible.", 404)
    return item


def memory_values(data: MemoryInput) -> dict:
    values = data.model_dump(exclude={"expected_version"})
    if values["expires_at"] is not None and values["expires_at"] <= time.time():
        raise Problem("The expiry must be in the future.")
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
                raise Problem("A domain with this name already exists.", 409)
            d = r.add(db.domains, **data.model_dump())
            r.log("domain.created", domain_id=d["id"])
            return d

    def update_domain(self, owner: str, item_id: str, data: DomainInput) -> dict:
        with self.store.scope(owner) as r:
            need(r.get(db.domains, item_id), "Domain")
            if r.list(db.domains, db.domains.c.name == data.name, db.domains.c.id != item_id):
                raise Problem("A domain with this name already exists.", 409)
            r.change(db.domains, item_id, **data.model_dump())
            self._invalidate(r, domain_id=item_id)
            r.log("domain.updated", domain_id=item_id)
            return need(r.get(db.domains, item_id))

    def delete_domain(self, owner: str, item_id: str) -> list[str]:
        with self.store.scope(owner) as r:
            need(r.get(db.domains, item_id), "Domain")
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

    def purge_meeting_evidence(self, r, mid, ids=None):
        """Remove reviewed derivatives and drafts when their meeting evidence is deleted."""
        links = r.list(db.meeting_proposal_links, db.meeting_proposal_links.c.meeting_id == mid)
        affected = {link['proposal_id'] for link in links
            if ids is None or any(e['id'] in ids for e in link['evidence'])}
        memory_ids = {m['id'] for m in r.list(db.memories) if m['provenance'].get('proposal_id') in affected}
        memory_ids.update(v['memory_id'] for v in r.list(db.versions)
            if v['snapshot'].get('provenance', {}).get('proposal_id') in affected)
        self._purge(r, memory_ids=memory_ids)
        for pid in affected:
            r.remove(db.proposals, pid)

    def memories(self, owner: str, domain: str) -> list[dict]:
        with self.store.scope(owner) as r:
            need(r.get(db.domains, domain), "Domain")
            return r.list(db.memories, db.memories.c.domain_id == domain)

    def create_memory(self, owner: str, domain: str, data: MemoryInput) -> dict:
        with self.store.scope(owner) as r:
            need(r.get(db.domains, domain), "Domain")
            m = r.add(db.memories, domain_id=domain, **memory_values(data), source_id=None,
                provenance={"kind": "owner", "note": "Confirmed by owner"}, version=1, updated_at=time.time())
            r.add(db.versions, domain_id=domain, memory_id=m["id"], version=1, snapshot=m)
            r.log("memory.created", domain_id=domain, memory_id=m["id"])
            return m

    def update_memory(self, owner: str, mid: str, data: MemoryInput) -> dict:
        with self.store.scope(owner) as r:
            m = need(r.get(db.memories, mid), "Memory")
            result = self._replace_memory(r, m, data, m["provenance"])
            self._invalidate(r, memory_id=mid)
            return result

    def _replace_memory(self, r, current: dict, data: MemoryInput, provenance: dict) -> dict:
        if data.expected_version != current["version"]:
            raise Problem("This memory has changed. Review the latest version before confirming.", 409)
        values = {**memory_values(data), "version": current["version"] + 1,
            "updated_at": time.time(), "provenance": provenance}
        result = r.c.execute(update(db.memories).where(db.memories.c.owner_id == r.owner,
            db.memories.c.id == current["id"], db.memories.c.version == data.expected_version).values(**values))
        if result.rowcount != 1:
            raise Problem("This memory was updated by another operation. Please try again.", 409)
        m = {**current, **values}
        r.add(db.versions, domain_id=m["domain_id"], memory_id=m["id"], version=m["version"], snapshot=m)
        r.log("memory.updated", domain_id=m["domain_id"], memory_id=m["id"], version=m["version"])
        return m

    def delete_memory(self, owner: str, mid: str):
        with self.store.scope(owner) as r:
            m = need(r.get(db.memories, mid), "Memory")
            self._purge(r, memory_ids={mid})
            r.log("memory.deleted", domain_id=m["domain_id"])

    def source(self, owner: str, domain: str, title: str, content: str, kind="text") -> dict:
        with self.store.scope(owner) as r:
            need(r.get(db.domains, domain), "Domain")
            if not content.strip() or len(content) > 100000:
                raise Problem("The source is empty or exceeds 100,000 characters.")
            item = r.add(db.sources, domain_id=domain, title=title, content=content, kind=kind)
            r.log("source.created", domain_id=domain, source_id=item["id"])
            return item

    async def extract_source(self, owner: str, source_id: str) -> list[dict]:
        async with self.learning_locks[source_id]:
            with self.store.scope(owner) as r:
                source = need(r.get(db.sources, source_id), "Source")
                existing = r.list(db.proposals, db.proposals.c.source_id == source_id)
                if existing:
                    return existing
            chunks = [source["content"][i:i+4000] for i in range(0, len(source["content"]), 4000)]
            records = [{"id": f"{source_id}:{i}", "content": s, "speaker": "Source imported by owner"} for i, s in enumerate(chunks)]
            extracted = await self.ai.extract(records)
            with self.store.scope(owner) as r:
                need(r.get(db.sources, source_id), "Source")  # deletion during model call
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
            source = need(r.get(db.sources, source_id), "Source")
            ids = {m["id"] for m in r.list(db.memories) if m["source_id"] == source_id or m["provenance"].get("source_id") == source_id}
            ids.update(v["memory_id"] for v in r.list(db.versions)
                if v["snapshot"].get("source_id") == source_id or v["snapshot"].get("provenance", {}).get("source_id") == source_id)
            self._purge(r, memory_ids=ids)
            r.remove(db.sources, source_id)
            r.log("source.deleted", domain_id=source["domain_id"])

    def create_session(self, owner: str, data: SessionInput) -> dict:
        with self.store.scope(owner) as r:
            return self._create_session(r, data)

    def quick_chat(self, owner: str) -> dict:
        with self.store.scope(owner) as r:
            domain = db.ensure_default_domain(r.c, owner)
            # Serialize default-chat creation across workers. SQLite already holds
            # a write lock from ensure_default_domain's upsert in this transaction.
            r.c.execute(select(db.domains.c.id).where(db.domains.c.owner_id == owner,
                db.domains.c.id == domain["id"]).with_for_update())
            facts = r.list(db.memories, db.memories.c.domain_id == domain["id"])
            facts = [m for m in facts if m["expires_at"] is None or m["expires_at"] > time.time()]
            latest = r.c.execute(select(db.sessions).where(db.sessions.c.owner_id == owner,
                db.sessions.c.mode == "private").order_by(db.sessions.c.created_at.desc(),
                db.sessions.c.id.desc()).limit(1)).mappings().first()
            if latest:
                s = dict(latest)
                same_scope = (s["domain_ids"] == [domain["id"]] and s["write_domain_id"] == domain["id"]
                    and s["allow_learning"] and s["action_policy"] == "none" and not s["goal"]
                    and not s["audience"] and not s["voice"] and not s["disclose_ids"]
                    and set(s["read_ids"]) == {m["id"] for m in facts}
                    and s["grants"] == {m["id"]: m["version"] for m in facts})
                if (same_scope and s["status"] == "active"
                    and not r.list(db.messages, db.messages.c.session_id == s["id"])
                    and not r.list(db.proposals, db.proposals.c.session_id == s["id"])
                    and not r.list(db.actions, db.actions.c.session_id == s["id"])):
                    self._active(r, s["id"])
                    return s
            data = SessionInput(mode="private", domain_ids=[domain["id"]],
                write_domain_id=domain["id"], allow_learning=True, action_policy="none")
            return self._create_session(r, data, facts=facts)

    def list_sessions(self, owner: str) -> list[dict]:
        with self.store.scope(owner) as r:
            counts = dict(r.c.execute(select(db.messages.c.session_id, func.count()).where(
                db.messages.c.owner_id == owner).group_by(db.messages.c.session_id)).all())
            return [{**s, "message_count": counts.get(s["id"], 0)} for s in reversed(r.list(db.sessions))]

    def rename_session(self, owner: str, sid: str, title: str) -> dict:
        with self.store.scope(owner) as r:
            need(r.get(db.sessions, sid), "Conversation")
            r.change(db.sessions, sid, title=title)
            return r.get(db.sessions, sid)

    def update_session_voice(self, owner: str, sid: str, dashscope_voice: str) -> dict:
        with self.store.scope(owner) as r:
            session = need(r.get(db.sessions, sid), "Conversation")
            voice = {**session["voice"], "dashscope_voice": dashscope_voice}
            r.change(db.sessions, sid, voice=voice)
            r.log("session.voice_updated", session_id=sid, voice_provider="dashscope")
            return r.get(db.sessions, sid)

    def reset_session_voices(self, owner: str, removed_voice: str, default_voice: str) -> int:
        changed = 0
        with self.store.scope(owner) as r:
            for session in r.list(db.sessions):
                if session["voice"].get("dashscope_voice") != removed_voice:
                    continue
                r.change(db.sessions, session["id"], voice={
                    **session["voice"], "dashscope_voice": default_voice,
                })
                r.log("session.voice_reset", session_id=session["id"], voice_provider="dashscope")
                changed += 1
        return changed

    def delete_session(self, owner: str, sid: str) -> None:
        with self.store.scope(owner) as r:
            need(r.get(db.sessions, sid), "Conversation")
            # Only this conversation and its FK children are removed. Confirmed
            # memories (including their evidence/provenance) remain in domains.
            r.remove(db.sessions, sid)

    def _create_session(self, r, data: SessionInput, *, facts: list[dict] | None = None) -> dict:
        for domain in data.domain_ids:
            need(r.get(db.domains, domain), "Domain")
        if facts is None:
            facts = [need(r.get(db.memories, mid), "Memory") for mid in data.read_ids]
        for m in facts:
            if m["domain_id"] not in data.domain_ids:
                raise Problem("A selected memory is outside the authorized domains.", 403)
            if m["expires_at"] and m["expires_at"] <= time.time():
                raise Problem("A selected memory has expired.", 409)
            if m["id"] in data.disclose_ids and not self._disclosable(m, data.audience):
                raise Problem("A selected memory cannot be disclosed to this audience.", 403)
        values = data.model_dump(exclude={"duration_minutes"})
        # Server-selected default memories use the same version and scope checks.
        values["read_ids"] = [m["id"] for m in facts]
        if data.mode == "private":
            values["disclose_ids"] = []
        expires_at = time.time() + data.duration_minutes * 60 if data.mode == "delegate" else None
        s = r.add(db.sessions, **values, status="active", expires_at=expires_at,
            grants={m["id"]: m["version"] for m in facts}, summary={})
        r.log("session.created", session_id=s["id"], domain_ids=data.domain_ids,
            disclose_count=len(s["disclose_ids"]), action_policy=data.action_policy)
        return s

    @staticmethod
    def _disclosable(m: dict, audience: str) -> bool:
        return (m["visibility"] == "shareable" and (not m["audiences"] or audience in m["audiences"])
            and (not m["expires_at"] or m["expires_at"] > time.time()))

    def _active(self, r, sid: str) -> dict:
        s = need(r.get(db.sessions, sid), "Conversation")
        if s["status"] != "active" or (s["mode"] == "delegate" and
            (s["expires_at"] is None or s["expires_at"] <= time.time())):
            raise Problem("This conversation has ended, expired, or been revoked.", 410)
        for domain in s["domain_ids"]:
            need(r.get(db.domains, domain), "Domain")
        for mid, version in s["grants"].items():
            m = r.get(db.memories, mid)
            if not m or m["version"] != version or (m["expires_at"] and m["expires_at"] <= time.time()):
                raise Problem("Authorized knowledge has changed. Ask the owner to create a new conversation.", 410)
            if mid in s["disclose_ids"] and not self._disclosable(m, s["audience"]):
                raise Problem("Disclosure permissions have changed.", 410)
        return s

    def active(self, owner: str, sid: str) -> dict:
        with self.store.scope(owner) as r:
            return self._active(r, sid)

    def view_session(self, owner: str, sid: str, *, guest=False) -> dict:
        with self.store.scope(owner) as r:
            s = need(r.get(db.sessions, sid), "Conversation")
            if guest:
                self._active(r, sid)
                if s["mode"] != "delegate":
                    raise Problem("Private conversations are not accessible to guests.", 403)
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
                    raise Problem("You do not have access to this private conversation.", 403)
                if not guest and s["mode"] == "delegate":
                    raise Problem("Use the guest entrance to speak in delegated conversations. Private notes are not sent to the guest.", 403)
                history = r.list(db.messages, db.messages.c.session_id == sid,
                    db.messages.c.role != "private_note")
                if len(history) >= 200:
                    raise Problem("This conversation has reached 100 turns. End it and create a new one.", 409)
                permitted = s["disclose_ids"] if s["mode"] == "delegate" else s["read_ids"]
                facts = [need(r.get(db.memories, mid)) for mid in permitted]
                speaker = "guest" if guest else "owner"
                if s["mode"] == "private" and s["title"] == "New conversation" and not history:
                    r.change(db.sessions, sid, title=content[:60])
                user_message = r.add(db.messages, session_id=sid, role=speaker, content=content,
                    citations=[], delivery="received")
            try:
                reply = await self.ai.reply(query=content, facts=facts, history=history, mode=s["mode"],
                    audience=s["audience"], goal=s["goal"], action_policy=s["action_policy"])
            except asyncio.CancelledError:
                raise
            except Exception:
                # Never expose vendor errors, endpoints, request context or keys.
                reply = {"kind": "unavailable", "reply": "Unable to verify a reply right now. Please try again later or contact the owner.", "citations": []}
            if authorize:
                authorize()  # Invitation rotation/logout can revoke a caller without ending the room.
            with self.store.scope(owner) as r:
                s = self._active(r, sid)  # check AFTER generation, before ANY output
                if not set(reply.get("citations", [])) <= set(permitted):
                    reply = {"kind": "clarify", "reply": FALLBACK, "citations": []}
                if reply["kind"] == "approval":
                    if s["action_policy"] == "none":
                        reply["reply"] = "This authorization only allows sharing information. I cannot make decisions for the owner."
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

    def save_conversation_memory(self, owner: str, sid: str, data: SaveConversationMemory):
        """An explicit owner request, distinct from automatic conversation learning."""
        with self.store.scope(owner) as r:
            s = need(r.get(db.sessions, sid), "Conversation")
            if s["mode"] != "private" or s["status"] == "revoked":
                raise Problem("Only private, non-revoked conversations can be saved this way.", 403)
            need(r.get(db.domains, data.domain_id), "Destination domain")
            if s["domain_ids"] and data.domain_id not in s["domain_ids"]:
                raise Problem("Save this memory to a domain selected for the conversation.", 403)
            message = need(r.get(db.messages, data.message_id), "Message")
            if message["session_id"] != sid or message["role"] != "owner":
                raise Problem("Select your own message from this conversation.", 403)
            evidence = [{"id": message["id"], "speaker": "Owner", "content": message["content"], "manual_save": True}]
            p = r.add(db.proposals, domain_id=data.domain_id, session_id=sid, source_id=None,
                title=data.title, content=data.content, evidence=evidence, status="pending",
                target_id=None, expected_version=None, result_id=None)
            r.log("memory.manually_proposed", session_id=sid, domain_id=data.domain_id, proposal_id=p["id"])
            return p

    def decide(self, owner: str, aid: str, decision: str, response: str) -> dict:
        with self.store.scope(owner) as r:
            a = need(r.get(db.actions, aid), "Approval request")
            self._active(r, a["session_id"])
            if decision == "approve" and not response.strip():
                raise Problem("Enter the exact wording you authorize the assistant to share.")
            status = "approved" if decision == "approve" else "rejected"
            result = r.c.execute(update(db.actions).where(db.actions.c.owner_id == owner,
                db.actions.c.id == aid, db.actions.c.status == "pending").values(status=status, response=response))
            if result.rowcount != 1:
                raise Problem("This request has already been handled.", 409)
            text = response.strip() if response.strip() else "The owner has not approved this request. No commitment has been made."
            message = r.add(db.messages, session_id=a["session_id"], role="owner_approved",
                content=text, citations=[], delivery="approved")
            r.log("action." + status, session_id=a["session_id"], action_id=aid, message_id=message["id"])
            return message

    def stop(self, owner: str, sid: str, status: str):
        with self.store.scope(owner) as r:
            s = need(r.get(db.sessions, sid), "Conversation")
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
                s = need(r.get(db.sessions, sid), "Conversation")
                if not s["allow_learning"]:
                    return []
                if s["status"] != "ended":
                    raise Problem("End the conversation first. Revoked conversations do not automatically produce memories.", 409)
                existing = [p for p in r.list(db.proposals, db.proposals.c.session_id == sid)
                    if not any(e.get("manual_save") for e in p["evidence"])]
                if existing:
                    return existing
                records = [{"id": m["id"], "speaker": s["audience"] if m["role"] == "guest" else "Owner",
                    "content": m["content"]} for m in r.list(db.messages, db.messages.c.session_id == sid)
                    if m["role"] in {"guest", "owner", "owner_approved"}]
            extracted = await self.ai.extract(records)
            with self.store.scope(owner) as r:
                s = need(r.get(db.sessions, sid), "Conversation")
                if s["status"] != "ended" or not s["allow_learning"]:
                    raise Problem("Permission to learn from this conversation has been revoked.", 410)
                existing = [p for p in r.list(db.proposals, db.proposals.c.session_id == sid)
                    if not any(e.get("manual_save") for e in p["evidence"])]
                if existing:
                    return existing
                by_id = {x["id"]: x for x in records}
                result = []
                for p in extracted:
                    evidence = [by_id[i] for i in p["evidence_ids"]]
                    speakers = ", ".join(dict.fromkeys(x["speaker"] for x in evidence))
                    result.append(r.add(db.proposals, domain_id=s["write_domain_id"], session_id=sid,
                        source_id=None, title=p["title"], content=f"{speakers} stated in this conversation: {p['content']}",
                        evidence=evidence, status="pending", target_id=None, expected_version=None, result_id=None))
                r.log("memory.proposed", session_id=sid, count=len(result))
                return result

    def review(self, owner: str, pid: str, data: ReviewInput) -> dict:
        with self.store.scope(owner) as r:
            p = need(r.get(db.proposals, pid), "Proposed update")
            if p["status"] != "pending":
                raise Problem("This update has already been reviewed.", 409)
            meeting_links = r.list(db.meeting_proposal_links, db.meeting_proposal_links.c.proposal_id == pid)
            if meeting_links and data.decision == 'approve':
                from echooo.meeting_knowledge import evidence_valid
                link = meeting_links[0]
                if not evidence_valid(r, link['evidence']):
                    raise Problem('The supporting transcript changed or was deleted. Dismiss this draft and prepare a new update.', 409)
                configs = r.list(db.meeting_knowledge, db.meeting_knowledge.c.meeting_id == link['meeting_id'])
                if not configs or configs[0]['project_id'] != p['domain_id']:
                    raise Problem('The destination project is no longer available.', 409)
                if data.target_id and data.target_id == p['target_id'] and data.expected_version != p['expected_version']:
                    raise Problem('The proposed target has changed. Review the conflict before saving a new memory.', 409)
            status = "approved" if data.decision == "approve" else "rejected"
            claim = r.c.execute(update(db.proposals).where(db.proposals.c.owner_id == owner,
                db.proposals.c.id == pid, db.proposals.c.status == "pending").values(status=status))
            if claim.rowcount != 1:
                raise Problem("This update has already been handled.", 409)
            result = None
            if data.decision == "approve":
                content = MemoryInput(**data.model_dump(exclude={"decision", "target_id"}))
                provenance = {"kind": "reviewed", "proposal_id": pid, "evidence": p["evidence"],
                    "session_id": p["session_id"], "source_id": p["source_id"]}
                if meeting_links:
                    provenance['meeting_id'] = meeting_links[0]['meeting_id']
                if data.target_id:
                    current = need(r.get(db.memories, data.target_id), "Target memory")
                    if current["domain_id"] != p["domain_id"]:
                        raise Problem("Updates cannot be written to another domain.", 403)
                    result = self._replace_memory(r, current, content, provenance)
                    self._invalidate(r, memory_id=current["id"])
                else:
                    result = r.add(db.memories, domain_id=p["domain_id"], **memory_values(content),
                        source_id=p["source_id"], provenance=provenance, version=1, updated_at=time.time())
                    r.add(db.versions, domain_id=p["domain_id"], memory_id=result["id"], version=1, snapshot=result)
                r.change(db.proposals, pid, result_id=result["id"])
            r.log("proposal." + status, domain_id=p["domain_id"], proposal_id=pid)
            return {"status": status, "memory": result}
