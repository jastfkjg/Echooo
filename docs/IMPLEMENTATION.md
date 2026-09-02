# Echooo implementation contract

This document tracks the requested product, not the former generic voice demo.

## Product

A personal representative with user-managed knowledge domains. No domain names or
categories are built into the product. Owners create, rename, describe, and delete
domains; upload information to a chosen domain; hold private conversations; and
delegate a bounded conversation to an invited participant.

## Required release behavior

- Persistent owner authentication and owner-scoped data access.
- Arbitrary domain CRUD; no seeded personal data.
- Domain-bound source ingestion and confirmed/versioned memories, including
  disclosure settings, audience restrictions, provenance, and expiry.
- Private owner conversations and separate delegated sessions. Each delegated
  session has immutable domains, audience, selected disclosure facts, write target,
  action permissions, and expiry. The owner can revoke it at any time.
- Invited participants receive a room-scoped credential and cannot access owner
  APIs, private notes, other rooms, domain lists, or unshared knowledge.
- Scoped retrieval before inference; no global conversation history. Facts are
  revalidated before output. Changes/deletion/revocation cancel affected work.
- Text and microphone interaction use the same authorization and output path.
  Only checked responses reach playback. Owner approval is required for commitments.
- Conversation learning produces attributed, pending changes. Review supports
  edits, approval, rejection, optimistic conflict detection, and version history.
- Meeting summary and trace show what was said, its source, approvals, and proposed
  changes. A third party's request is never automatically the owner's agreement.
- Domain deletion removes dependent content and derived records, invalidates
  sessions, and clears active playback. Storage/backup limitations are documented.
- Browser UX verified on desktop and mobile; authorization, cross-domain isolation,
  guest access, revocation, learning, and failure behavior exercised in tests.
- README, architecture/security notes, operation instructions, and roadmap updated.

## Technical approach

FastAPI and SQLAlchemy, SQLite for an immediate local run, PostgreSQL with row-level
security for deployment. A server-enforced repository is shared by HTTP, voice,
retrieval, and background learning. Model selection is replaceable. The first room
supports an invited collaborator speaking with the agent and an owner supervising
privately. Conference media integrations are separate from this authority layer.

## Visual direction

Visual thesis: a quiet dark personal workspace, warm neutral typography, restrained
green accents, and clear separation between private knowledge and delegated work.
Content plan: domain navigation; sources/memories as the main workspace; conversation
and review views; a focused authorization dialog and guest room.
Interaction thesis: short view transitions, progressive disclosure of authorization
details, and explicit listening/thinking/speaking states with reduced-motion support.

## Verification record

Verified on 2026-09-02 against disposable synthetic data:

- `STT_PROVIDER=mock LLM_PROVIDER=mock TTS_PROVIDER=browser .venv/bin/python -m pytest -q`: 28 passed, 1 skipped. The skip is the PostgreSQL-only RLS case.
- With `ECHO_TEST_POSTGRES_URL` pointing to a disposable native PostgreSQL 18.4 database: `pytest tests/test_product.py -q`: 24 passed, including unfiltered cross-owner reads and forged writes rejected by RLS.
- After the final audio termination/late-frame handling change, the product suite was rerun on SQLite: 23 passed, 1 PostgreSQL-only skip.
- `python -m compileall -q src tests`, `node --check web/app.js`, `node --check web/voice.js`, and `git diff --check` passed.
- `docker compose config --quiet` passed with a temporary development password. The Compose container itself was not started; PostgreSQL integration was tested with the native disposable server, which was stopped afterward.
- Desktop browser workflow: empty workspace setup; arbitrary domain creation; private and audience-restricted memories; delegated session with 2 read / 1 disclose; one-use invitation; guest request for private information answered only from shared progress; owner-only note remained absent from guest history; new commitment required approval; exact owner-approved text appeared in guest room; ending invalidated the guest credential and generated attributed pending memories.
- Owner edited a customer request before approving it as a private memory in the original domain. Mobile workflow at 375 × 812: review layout, navigation, domain memories, raw text ingestion, extraction, private conversation using selected private facts, and normal ending. No horizontal page overflow on the inspected mobile review page. Default viewport was restored.
- Browser error/warning logs on both test tabs were empty at the end of the workflow. Server restart preserved workspace data.
- Audio protocol tests use fake STT events and TTS bytes to verify the complete scoped room path, checked-text ordering, PCM alignment, retry, and cancellation. SSE model transport is verified with an HTTP mock transport.

External AssemblyAI / LLM / CosyVoice calls and physical microphone/audio quality have not been acceptance-tested. The browser demo is explicitly labelled deterministic mock mode. Third-party test dependencies emit deprecation warnings under Python 3.14; no test failures resulted.

## Scope decisions

Delivered: dynamic domains, persistent knowledge, scoped private and delegated conversations, invitations, text/voice adapters, owner approval, reviewed learning, lineage-aware deletion, PostgreSQL RLS, and a usable owner/guest interface.

The media layer is a one-participant browser WebSocket room in this release. LiveKit/multi-party conferences, pgvector semantic search, exact played-text accounting, external action execution, and public multi-tenant deployment are subsequent stages with explicit acceptance criteria in ROADMAP.md. Memory updates require review; automatic unreviewed learning is not enabled. This is a working first product release, not a claim of fully autonomous meeting participation or guaranteed model secrecy.
