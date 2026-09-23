"""Persistent storage. All application queries use a trusted owner scope.

SQLite is the zero-service development database. PostgreSQL also enforces scope
with RLS; migrations run as the schema owner, serving queries use SET LOCAL ROLE.
Never expose this connection or an owner_id argument as a model tool.
"""
from __future__ import annotations

import contextlib
import hashlib
import secrets
import time
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON, Boolean, LargeBinary, Column, Float, ForeignKey, Integer, MetaData, String, Table, Text,
    UniqueConstraint, create_engine, delete, event, insert, select, text, update,
)
from sqlalchemy.pool import StaticPool


def uid() -> str:
    return secrets.token_hex(16)


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


metadata = MetaData()
users = Table("owners", metadata,
    Column("id", String, primary_key=True), Column("name", String, unique=True, nullable=False),
    Column("password", String, nullable=False), Column("created_at", Float, nullable=False))
tokens = Table("credentials", metadata,
    Column("id", String, primary_key=True),
    Column("owner_id", String, ForeignKey("owners.id", ondelete="CASCADE"), nullable=False),
    Column("kind", String, nullable=False), Column("session_id", String),
    Column("expires_at", Float, nullable=False))


def owned_table(name: str, *columns: Column, constraints=()) -> Table:
    return Table(name, metadata, Column("id", String, primary_key=True),
        Column("owner_id", String, ForeignKey("owners.id", ondelete="CASCADE"), nullable=False, index=True),
        *columns, Column("created_at", Float, nullable=False), *constraints)


domains = owned_table("domains", Column("name", String, nullable=False),
    Column("description", Text, nullable=False), Column("color", String, nullable=False),
    constraints=(UniqueConstraint("owner_id", "name"),))


def ensure_default_domain(connection, owner: str) -> dict:
    """Provision the owner's ordinary default domain, safely across requests."""
    if connection.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as upsert
    else:
        from sqlalchemy.dialects.sqlite import insert as upsert
    connection.execute(upsert(domains).values(id=uid(), owner_id=owner, name="default",
        description="Everyday conversations and memories. Choose another domain for a specific context.",
        color="sage", created_at=time.time()).on_conflict_do_nothing(index_elements=["owner_id", "name"]))
    return dict(connection.execute(select(domains).where(
        domains.c.owner_id == owner, domains.c.name == "default")).mappings().one())


def domain_ref() -> Column:
    return Column("domain_id", String, ForeignKey("domains.id", ondelete="CASCADE"), nullable=False, index=True)


sources = owned_table("sources", domain_ref(), Column("title", String, nullable=False),
    Column("content", Text, nullable=False), Column("kind", String, nullable=False))
memories = owned_table("memories", domain_ref(), Column("title", String, nullable=False),
    Column("content", Text, nullable=False), Column("visibility", String, nullable=False),
    Column("audiences", JSON, nullable=False), Column("expires_at", Float),
    Column("source_id", String, ForeignKey("sources.id", ondelete="CASCADE")),
    Column("provenance", JSON, nullable=False), Column("version", Integer, nullable=False),
    Column("updated_at", Float, nullable=False))
versions = owned_table("memory_versions", domain_ref(),
    Column("memory_id", String, ForeignKey("memories.id", ondelete="CASCADE"), nullable=False),
    Column("version", Integer, nullable=False), Column("snapshot", JSON, nullable=False))
sessions = owned_table("sessions", Column("title", String, nullable=False),
    Column("mode", String, nullable=False), Column("audience", String, nullable=False),
    Column("goal", Text, nullable=False), Column("domain_ids", JSON, nullable=False),
    Column("read_ids", JSON, nullable=False), Column("disclose_ids", JSON, nullable=False),
    Column("grants", JSON, nullable=False),
    Column("write_domain_id", String, ForeignKey("domains.id", ondelete="CASCADE"), nullable=True),
    Column("allow_learning", Integer, nullable=False), Column("action_policy", String, nullable=False),
    Column("status", String, nullable=False), Column("expires_at", Float, nullable=True),
    Column("summary", JSON, nullable=False), Column("voice", JSON, nullable=False))


def session_ref() -> Column:
    return Column("session_id", String, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True)


messages = owned_table("messages", session_ref(), Column("role", String, nullable=False),
    Column("content", Text, nullable=False), Column("citations", JSON, nullable=False),
    Column("delivery", String, nullable=False))
proposals = owned_table("proposals", domain_ref(),
    Column("session_id", String, ForeignKey("sessions.id", ondelete="CASCADE")),
    Column("source_id", String, ForeignKey("sources.id", ondelete="CASCADE")),
    Column("title", String, nullable=False), Column("content", Text, nullable=False),
    Column("evidence", JSON, nullable=False), Column("status", String, nullable=False),
    Column("target_id", String, ForeignKey("memories.id", ondelete="CASCADE")),
    Column("expected_version", Integer), Column("result_id", String))
actions = owned_table("actions", session_ref(), Column("request", Text, nullable=False),
    Column("status", String, nullable=False), Column("response", Text, nullable=False))
audit = owned_table("audit", Column("session_id", String, ForeignKey("sessions.id", ondelete="CASCADE")),
    Column("domain_id", String, ForeignKey("domains.id", ondelete="CASCADE")),
    Column("kind", String, nullable=False), Column("detail", JSON, nullable=False))

meetings = owned_table("meetings", Column("title", String, nullable=False),
    Column("status", String, nullable=False), Column("revision", Integer, nullable=False))

def meeting_ref():
    return Column("meeting_id", String, ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True)

recordings = owned_table("meeting_recordings", meeting_ref(),
    Column("sample_rate", Integer, nullable=False), Column("samples", Integer, nullable=False))
audio_parts = owned_table("meeting_audio_parts", meeting_ref(),
    Column("recording_id", String, ForeignKey("meeting_recordings.id", ondelete="CASCADE"), nullable=False),
    Column("sequence", Integer, nullable=False), Column("pcm", LargeBinary, nullable=False),
    constraints=(UniqueConstraint("recording_id", "sequence"),))
utterances = owned_table("meeting_utterances", meeting_ref(),
    Column("recording_id", String, ForeignKey("meeting_recordings.id", ondelete="CASCADE")),
    Column("speaker", String, nullable=False), Column("content", Text, nullable=False),
    Column("start_ms", Integer, nullable=False), Column("end_ms", Integer, nullable=False))
utterance_sources = owned_table("meeting_utterance_sources", meeting_ref(),
    Column("recording_id", String, ForeignKey("meeting_recordings.id", ondelete="CASCADE"), nullable=False),
    Column("utterance_id", String, ForeignKey("meeting_utterances.id", ondelete="CASCADE"), nullable=False),
    Column("state", JSON, nullable=False), constraints=(UniqueConstraint("utterance_id"),))
meeting_sections = owned_table("meeting_sections", meeting_ref(),
    Column("evidence_ids", JSON, nullable=False), Column("summary", Text, nullable=False),
    Column("items", JSON, nullable=False), Column("revision", Integer, nullable=False),
    Column("status", String, nullable=False))
recording_summaries = owned_table("meeting_recording_summaries", meeting_ref(),
    Column("recording_id", String, ForeignKey("meeting_recordings.id", ondelete="CASCADE")),
    Column("scope_key", String, nullable=False), Column("summary", Text, nullable=False),
    Column("evidence_ids", JSON, nullable=False), Column("revision", Integer, nullable=False),
    Column("status", String, nullable=False))

# A separate table upgrades existing installations without rewriting recordings.
recording_transcriptions = owned_table("meeting_recording_transcriptions", meeting_ref(),
    Column("recording_id", String, ForeignKey("meeting_recordings.id", ondelete="CASCADE"), nullable=False),
    Column("state", JSON, nullable=False),
    constraints=(UniqueConstraint("recording_id"),))

meeting_minutes = owned_table("meeting_minutes", meeting_ref(),
    Column("recording_id", String, ForeignKey("meeting_recordings.id", ondelete="CASCADE")),
    Column("scope_key", String, nullable=False), Column("content", JSON, nullable=False),
    Column("evidence_ids", JSON, nullable=False), Column("revision", Integer, nullable=False),
    Column("status", String, nullable=False),
    constraints=(UniqueConstraint("meeting_id", "scope_key"),))

meeting_bots = owned_table("meeting_bots", meeting_ref(),
    Column("meeting_url", Text, nullable=False), Column("platform", String, nullable=False),
    Column("bot_name", String, nullable=False), Column("provider_id", String),
    Column("state", String, nullable=False), Column("desired_state", String, nullable=False),
    Column("callback_hash", String, nullable=False), Column("error", Text, nullable=False),
    Column("updated_at", Float, nullable=False), Column("deadline", Float, nullable=False),
    constraints=(UniqueConstraint("meeting_id"),))

meeting_agent_settings = owned_table("meeting_agent_settings", meeting_ref(),
    Column("connection_id", String, ForeignKey("meeting_bots.id", ondelete="CASCADE"), nullable=False),
    Column("chat_enabled", Boolean, nullable=False), Column("voice_enabled", Boolean, nullable=False),
    constraints=(UniqueConstraint("connection_id"),))

# Private chat is deliberately separate from meeting utterances and minutes.
meeting_agent_events = owned_table("meeting_agent_events", meeting_ref(),
    Column("connection_id", String, nullable=False), Column("source_key", String, nullable=False),
    Column("audience", String, nullable=False), Column("sender", String, nullable=False),
    Column("request", Text, nullable=False), Column("response", Text, nullable=False),
    Column("status", String, nullable=False), Column("error", Text, nullable=False),
    constraints=(UniqueConstraint("connection_id", "source_key"),))

meeting_knowledge = owned_table("meeting_knowledge", meeting_ref(),
    Column("project_id", String, ForeignKey("domains.id", ondelete="SET NULL")),
    Column("goal", Text, nullable=False), Column("reference_ids", JSON, nullable=False),
    Column("grants", JSON, nullable=False), Column("revision", Integer, nullable=False),
    constraints=(UniqueConstraint("meeting_id"),))
meeting_answer_sources = owned_table("meeting_answer_sources", meeting_ref(),
    Column("event_id", String, ForeignKey("meeting_agent_events.id", ondelete="CASCADE"), nullable=False),
    Column("scope", JSON, nullable=False), Column("citations", JSON, nullable=False),
    constraints=(UniqueConstraint("event_id"),))
meeting_answer_checks = owned_table("meeting_answer_checks", meeting_ref(),
    Column("event_id", String, ForeignKey("meeting_agent_events.id", ondelete="CASCADE"), nullable=False),
    Column("detail", JSON, nullable=False),
    constraints=(UniqueConstraint("event_id"),))
meeting_answer_traces = owned_table("meeting_answer_traces", meeting_ref(),
    Column("event_id", String, ForeignKey("meeting_agent_events.id", ondelete="CASCADE"), nullable=False),
    Column("detail", JSON, nullable=False),
    constraints=(UniqueConstraint("event_id"),))
meeting_speech = owned_table("meeting_speech", meeting_ref(),
    Column("event_id", String, ForeignKey("meeting_agent_events.id", ondelete="CASCADE"), nullable=False),
    Column("recording_id", String, ForeignKey("meeting_recordings.id", ondelete="SET NULL")),
    Column("timing", JSON, nullable=False),
    constraints=(UniqueConstraint("event_id"),))
meeting_proposal_links = owned_table("meeting_proposal_links", meeting_ref(),
    Column("proposal_id", String, ForeignKey("proposals.id", ondelete="CASCADE"), nullable=False),
    Column("evidence", JSON, nullable=False),
    constraints=(UniqueConstraint("proposal_id"),))

# Independent reviewed decisions; create_all adds these tables to existing databases.
meeting_findings = owned_table("meeting_findings", meeting_ref(),
    Column("kind", String, nullable=False), Column("statement", Text, nullable=False),
    Column("original", JSON, nullable=False), Column("evidence", JSON, nullable=False),
    Column("details", JSON, nullable=False, default=dict),
    Column("fingerprint", String, nullable=False), Column("status", String, nullable=False),
    Column("revision", Integer, nullable=False),
    constraints=(UniqueConstraint("meeting_id", "fingerprint"),))
meeting_finding_reviews = owned_table("meeting_finding_reviews", meeting_ref(),
    Column("finding_id", String, ForeignKey("meeting_findings.id", ondelete="CASCADE"), nullable=False),
    Column("action", String, nullable=False), Column("before", JSON, nullable=False),
    Column("after", JSON, nullable=False))
meeting_finding_progress = owned_table("meeting_finding_progress", meeting_ref(),
    Column("processed", JSON, nullable=False), Column("phase", String, nullable=False),
    Column("error", Text, nullable=False),
    constraints=(UniqueConstraint("meeting_id"),))

meeting_interventions = owned_table("meeting_interventions", meeting_ref(),
    Column("kind", String, nullable=False), Column("question", Text, nullable=False),
    Column("reason", Text, nullable=False), Column("evidence", JSON, nullable=False),
    Column("status", String, nullable=False), Column("revision", Integer, nullable=False),
    Column("state", JSON, nullable=False))
meeting_intervention_reviews = owned_table("meeting_intervention_reviews", meeting_ref(),
    Column("intervention_id", String, ForeignKey("meeting_interventions.id", ondelete="CASCADE"), nullable=False),
    Column("action", String, nullable=False), Column("before", JSON, nullable=False),
    Column("after", JSON, nullable=False))

meeting_intervention_checks = owned_table('meeting_intervention_checks', meeting_ref(),
    Column('outcome', String, nullable=False), Column('detail', JSON, nullable=False))

OWNED = [domains, sources, memories, versions, sessions, messages, proposals, actions, audit,
    meetings, recordings, audio_parts, utterances, meeting_sections, recording_summaries, recording_transcriptions, meeting_minutes, meeting_bots,
    meeting_agent_settings, meeting_agent_events, utterance_sources,
    meeting_knowledge, meeting_answer_sources, meeting_answer_checks, meeting_answer_traces, meeting_proposal_links, meeting_speech, meeting_findings, meeting_finding_reviews, meeting_finding_progress,
    meeting_interventions, meeting_intervention_reviews, meeting_intervention_checks]


class Store:
    def __init__(self, url: str):
        kwargs: dict[str, Any] = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 15}
            if ":memory:" in url:
                kwargs["poolclass"] = StaticPool
            else:
                path = url.split("///", 1)[-1]
                Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(url, **kwargs)
        self.postgres = self.engine.dialect.name == "postgresql"
        if not self.postgres:
            @event.listens_for(self.engine, "connect")
            def pragma(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("PRAGMA secure_delete=ON")
        metadata.create_all(self.engine)
        from echooo.migrations import allow_unscoped_private_chats, add_finding_details
        allow_unscoped_private_chats(self.engine)
        add_finding_details(self.engine)
        # Upgrade existing empty workspaces without moving their data or scopes.
        with self.engine.begin() as c:
            empty_owners = c.execute(select(users.c.id).where(~select(domains.c.id).where(
                domains.c.owner_id == users.c.id).exists())).scalars().all()
            for owner in empty_owners:
                ensure_default_domain(c, owner)
        if self.postgres:
            self._rls()

    def _rls(self) -> None:
        with self.engine.begin() as c:
            # Serialize first-run schema policy installation across processes.
            c.execute(text("SELECT pg_advisory_xact_lock(76823917)"))
            c.execute(text("""DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'echooo_scoped') THEN
                    CREATE ROLE echooo_scoped NOLOGIN NOBYPASSRLS;
                END IF;
            END $$"""))
            c.execute(text("GRANT echooo_scoped TO CURRENT_USER"))
            c.execute(text("GRANT USAGE ON SCHEMA public TO echooo_scoped"))
            for table in OWNED:
                name = table.name  # constant schema identifiers, never user input
                c.execute(text(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY"))
                c.execute(text(f"DROP POLICY IF EXISTS owner_scope ON {name}"))
                c.execute(text(f"CREATE POLICY owner_scope ON {name} TO echooo_scoped USING "
                    "(owner_id = current_setting('echooo.owner_id', true)) WITH CHECK "
                    "(owner_id = current_setting('echooo.owner_id', true))"))
                c.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {name} TO echooo_scoped"))

    @contextlib.contextmanager
    def scope(self, owner: str):
        if not owner:
            raise ValueError("Owner scope is required")
        with self.engine.begin() as c:
            if self.postgres:
                c.execute(text("SET LOCAL ROLE echooo_scoped"))
                c.execute(text("SELECT set_config('echooo.owner_id', :owner, true)"), {"owner": owner})
            yield Repository(c, owner)

    def close(self) -> None:
        self.engine.dispose()


class Repository:
    def __init__(self, connection, owner: str):
        self.c, self.owner = connection, owner

    def list(self, table: Table, *conditions) -> list[dict]:
        stmt = select(table).where(table.c.owner_id == self.owner, *conditions)
        if "created_at" in table.c:
            stmt = stmt.order_by(table.c.created_at.asc(), table.c.id.asc())
        return [dict(row) for row in self.c.execute(stmt).mappings()]

    def get(self, table: Table, item_id: str) -> dict | None:
        rows = self.list(table, table.c.id == item_id)
        return rows[0] if rows else None

    def add(self, table: Table, **values) -> dict:
        values.update(id=uid(), owner_id=self.owner, created_at=time.time())
        self.c.execute(insert(table).values(**values))
        return values

    def change(self, table: Table, item_id: str, **values) -> None:
        if {"owner_id", "id", "created_at"} & values.keys():
            raise ValueError("Immutable identity")
        self.c.execute(update(table).where(table.c.owner_id == self.owner, table.c.id == item_id).values(**values))

    def remove(self, table: Table, item_id: str) -> None:
        self.c.execute(delete(table).where(table.c.owner_id == self.owner, table.c.id == item_id))

    def log(self, kind: str, *, session_id=None, domain_id=None, **detail) -> None:
        self.add(audit, kind=kind, session_id=session_id, domain_id=domain_id, detail=detail)
