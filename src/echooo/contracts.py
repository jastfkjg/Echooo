from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Credentials(Input):
    name: str = Field(min_length=2, max_length=60)
    password: str = Field(min_length=1, max_length=200)


class DomainInput(Input):
    name: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=1000)
    color: Literal["sage", "blue", "amber", "violet", "rose", "slate"] = "sage"


class MemoryInput(Input):
    title: str = Field(min_length=1, max_length=150)
    content: str = Field(min_length=1, max_length=12000)
    visibility: Literal["private", "shareable"] = "private"
    audiences: list[str] = Field(default_factory=list, max_length=20)
    expires_at: float | None = None
    expected_version: int | None = None

    @field_validator("audiences")
    @classmethod
    def clean_audiences(cls, values):
        if any(not v.strip() or len(v) > 80 for v in values):
            raise ValueError("Invalid audience")
        return list(dict.fromkeys(v.strip() for v in values))


class SourceInput(Input):
    title: str = Field(min_length=1, max_length=150)
    content: str = Field(min_length=1, max_length=100000)


class SessionInput(Input):
    title: str = Field(default="New conversation", min_length=1, max_length=120)
    mode: Literal["private", "delegate"] = "delegate"
    audience: str = Field(default="", max_length=80)
    goal: str = Field(default="", max_length=2000)
    domain_ids: list[str] = Field(default_factory=list, max_length=12)
    read_ids: list[str] = Field(default_factory=list, max_length=100)
    disclose_ids: list[str] = Field(default_factory=list, max_length=100)
    write_domain_id: str | None = None
    allow_learning: bool = True
    action_policy: Literal["ask", "none"] = "ask"
    duration_minutes: int = Field(default=60, ge=5, le=1440)
    voice: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_scope(self):
        self.domain_ids = list(dict.fromkeys(self.domain_ids))
        self.read_ids = list(dict.fromkeys(self.read_ids))
        self.disclose_ids = list(dict.fromkeys(self.disclose_ids))
        if self.write_domain_id is not None and self.write_domain_id not in self.domain_ids:
            raise ValueError("Write domain must be in this session")
        if self.allow_learning and self.write_domain_id is None:
            raise ValueError("Choose a destination domain to enable memory proposals")
        if self.mode == "delegate" and not self.domain_ids:
            raise ValueError("Delegation requires an explicitly selected domain")
        if self.mode == "delegate" and not self.audience:
            raise ValueError("An audience is required")
        if not set(self.disclose_ids) <= set(self.read_ids):
            raise ValueError("Disclosure facts must also be readable")
        if len(str(self.voice)) > 2000:
            raise ValueError("Voice profile too large")
        return self


class MessageInput(Input):
    content: str = Field(min_length=1, max_length=6000)


class SaveConversationMemory(Input):
    domain_id: str
    message_id: str
    title: str = Field(min_length=1, max_length=150)
    content: str = Field(min_length=1, max_length=12000)


class ReviewInput(MemoryInput):
    decision: Literal["approve", "reject"]
    target_id: str | None = None


class DecisionInput(Input):
    decision: Literal["approve", "reject"]
    response: str = Field(default="", max_length=2000)


class InviteInput(Input):
    token: str = Field(min_length=32, max_length=200)
