"""LLM boundary. Only already-authorized records may enter this module.

Mock mode is a deterministic local demonstration, explicitly surfaced in the UI.
The real adapter drafts structured responses and uses a second, fail-closed check
before public text is passed to speech synthesis. It is not a secrecy guarantee.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

import httpx

from echooo.config import Settings


FALLBACK = "That is outside the information I can confirm in this conversation. I will ask the owner to clarify."
COMMITMENT = re.compile(r"(承诺|保证|同意|接受报价|成交|签约|签字|付款|转账|下单|预订|确定交期|答应|保证交付|commit|promise|guarantee|accept.{0,20}(offer|price)|agree|book|purchase|pay\b|sign\b)", re.I)


def relevant(query: str, facts: list[dict], limit: int = 8) -> list[dict]:
    """Lexical retrieval inside the authorized set; never searches global data."""
    words = set(re.findall(r"[a-z0-9]{2,}", query.lower()))
    words.update(re.findall(r"(?=([\u4e00-\u9fff]{2}))", query))
    def score(fact):
        value = (fact["title"] + " " + fact["content"]).lower()
        return sum(w in value for w in words)
    ranked = sorted(facts, key=score, reverse=True)
    if any(x in query.lower() for x in ["概况", "介绍", "进展", "总结", "overview", "summary", "知道什么"]):
        return ranked[:limit]
    return [f for f in ranked if score(f) > 0][:limit]


class Intelligence:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def json_call(self, system: str, data: dict, *, fast: bool = False) -> dict:
        headers = {}
        if self.settings.llm_api_key:
            headers["Authorization"] = f"Bearer {self.settings.llm_api_key}"
        payload = {"model": self.settings.llm_model, "temperature": 0,
            "messages": [{"role": "system", "content": system},
                {"role": "user", "content": json.dumps(data, ensure_ascii=False)}],
            "stream": False, "max_tokens": 2400}
        if fast:
            host = urlsplit(self.settings.llm_base_url).hostname or ""
            model = self.settings.llm_model.lower()
            if host.endswith(".aliyuncs.com") and model.startswith(("deepseek-v4", "deepseek-v3.2", "deepseek-v3.1", "qwen3")):
                payload["enable_thinking"] = False
            elif host == "api.deepseek.com" and model.startswith("deepseek-v4"):
                payload["thinking"] = {"type": "disabled"}
        timeout = httpx.Timeout(self.settings.llm_timeout_seconds, connect=10)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                self.settings.llm_base_url.rstrip("/") + "/chat/completions",
                headers=headers, json=payload,
            )
            response.raise_for_status()
        packet = response.json()
        choices = packet.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            raise ValueError("Model returned no choices")
        message = choices[0].get("message") or {}
        if choices[0].get("finish_reason") == "length":
            raise ValueError("Model output was truncated")
        output = message.get("content")
        if not isinstance(output, str) or not output:
            raise ValueError("Model returned no content")
        if len(output) > 24000:
            raise ValueError("Model output too large")
        output = re.sub(r"^```(?:json)?\s*|\s*```$", "", output.strip())
        result = json.loads(output)
        if not isinstance(result, dict):
            raise ValueError("Expected JSON object")
        return result

    async def reply(self, *, query: str, facts: list[dict], history: list[dict],
        mode: str, audience: str, goal: str, action_policy: str) -> dict:
        selected = relevant(query, facts)
        if self.settings.llm_provider == "mock":
            if mode == "delegate" and COMMITMENT.search(query):
                return {"kind": "approval", "reply": "This commitment requires owner approval. I have recorded the request.", "citations": [], "proposal": query}
            if not selected:
                return {"kind": "clarify", "reply": FALLBACK if mode == "delegate" else "This is a local demo. Connect a live model for general conversation. No personal memory was used for this reply.", "citations": []}
            return {"kind": "answer", "reply": "Based on confirmed information: " + "; ".join(f["content"] for f in selected[:3]),
                "citations": [f["id"] for f in selected[:3]]}
        # Real models can resolve paraphrases; retain additional authorized facts
        # within a bounded context even when lexical overlap is absent.
        ranked = selected + [f for f in facts if f not in selected]
        selected, size = [], 0
        for fact in ranked:
            length = len(fact["content"]) + len(fact["title"])
            if len(selected) >= 12 or size + length > 36000:
                break
            selected.append(fact)
            size += length
        context = {"mode": mode, "audience": audience, "goal": goal, "question": query,
            "facts": [{k: f[k] for k in ("id", "title", "content")} for f in selected],
            "conversation": [{"role": m["role"], "content": m["content"]} for m in history[-12:]],
            "action_policy": action_policy}
        draft = await self.json_call(self.settings.prompts.delegate_system, context)
        if draft.get("kind") not in {"answer", "clarify", "approval"}:
            raise ValueError("Invalid reply kind")
        if not isinstance(draft.get("reply"), str) or not 0 < len(draft["reply"]) <= 6000:
            raise ValueError("Invalid reply")
        ids = draft.get("citations", [])
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids) or not set(ids) <= {f["id"] for f in selected}:
            raise ValueError("Unknown citation")
        if mode == "delegate":
            if COMMITMENT.search(query) or draft["kind"] == "approval":
                return {"kind": "approval", "reply": "This decision requires owner approval. I have recorded the request.", "proposal": query, "citations": []}
            # The checker sees only the same disclosure set, not a global private profile.
            check = await self.json_call(self.settings.prompts.check_system, {**context, "draft": draft})
            if check.get("commitment") is True:
                return {"kind": "approval", "reply": "This decision requires owner approval. I have recorded the request.", "proposal": query, "citations": []}
            if check.get("allow") is not True:
                return {"kind": "clarify", "reply": FALLBACK, "citations": []}
        return {**draft, "citations": ids}

    async def extract(self, records: list[dict]) -> list[dict]:
        """Only proposes facts. This function never writes confirmed memories."""
        if not records:
            return []
        if self.settings.llm_provider == "mock":
            return [{"title": (r["content"][:38] + "…") if len(r["content"]) > 38 else r["content"],
                "content": r["content"], "evidence_ids": [r["id"]]} for r in records[-20:]]
        result = await self.json_call(self.settings.prompts.memory_system, {"records": records[-40:]})
        proposals = result.get("proposals")
        if not isinstance(proposals, list):
            raise ValueError("Invalid memory extraction")
        allowed = {r["id"] for r in records}
        clean = []
        for p in proposals[:20]:
            if (isinstance(p, dict) and isinstance(p.get("title"), str) and 0 < len(p["title"]) <= 150
                and isinstance(p.get("content"), str) and 0 < len(p["content"]) <= 12000
                and isinstance(p.get("evidence_ids"), list) and p["evidence_ids"]
                and all(isinstance(i, str) for i in p["evidence_ids"])
                and set(p["evidence_ids"]) <= allowed):
                clean.append(p)
        return clean
