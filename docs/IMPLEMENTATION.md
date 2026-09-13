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
- English interface, application notices, and documentation by default; preserve the language of user-provided content.
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

## English default update

The UI, metadata, accessibility labels, dates and counts, service notices, demo reply
wrappers, and project documentation now default to English. Existing user content
is not rewritten; multilingual recognition rules and literal provider voice IDs
are retained. Existing password-validation changes were preserved.

Validation: 28 tests passed with one PostgreSQL-only skip; Python compilation,
JavaScript syntax, and whitespace checks passed. Browser inspection covered English
setup, domain creation, and delegation and invitation dialogs at desktop and
375 × 812 mobile size, with no dialog overflow in the inspected views. The guest
invitation and conversation flow also displayed English, including the default
fallback reply. Browser error/warning logs were empty, and the viewport was reset.

## Global conversation entry update

The home page, sidebar, and Conversations list now expose **Talk with Echooo**.
It opens a private chat without requiring manual domain selection or a title.
The default-domain update below enables everyday memory in this entry. Explicitly
empty scopes never load personal memories, and learning is off without a destination.
The first owner message supplies the initial title. Domain shortcuts still select
the current domain; choosing domains from a chat starts a fresh context. Delegation
remains separately authorized and does not inherit private conversation history.

The owner can explicitly create a pending memory proposal from one of their own
messages, selecting a destination or creating their first domain. Scoped chats
cannot save outside their selected domains; general chats do not acquire access
to a destination merely by saving a proposal. SQLite startup upgrade preserves old
sessions and dependent messages while making the memory destination nullable.

Verification: 34 tests passed with one PostgreSQL-only skip, including six new
cases covering empty scopes, private context isolation, explicit memory saving,
voice-room compatibility, and legacy SQLite migration. JavaScript syntax, Python
compilation, and whitespace checks passed. Browser verification used an isolated
loopback server and disposable database; no existing workspace was migrated or
restarted. It covered an empty workspace, immediate chat, manual save into a new
domain, review with private defaults, and fresh context after domain selection.

The new chat and voice controls were also inspected at 375 × 812 with no horizontal
overflow. The delegation dialog remained separate, with no preselected domains or
copied private goal/transcript. Browser error and warning logs were empty. The
viewport was restored and the disposable test server was stopped afterward.

## Default domain for everyday conversations

Initial setup atomically creates an ordinary domain named `default`. Startup
backfills existing owners with no domains. The quick-chat endpoint resolves that
owner's default domain, reads its confirmed and unexpired memories, and enables
end-of-chat proposals in the same domain. Other domains require explicit selection,
and proposed updates still require review before becoming private memories.

The interface names the active domain and proposal destination. Domain changes
still open a fresh conversation; explicitly selecting no domains disables memory.
Renaming or deleting `default` leaves ordinary CRUD behavior intact. A later quick
chat creates a new empty default domain without restoring removed information.

Verification: 38 tests passed with one PostgreSQL-only skip. New coverage verifies
first-run voice chat, review and recall, expired-memory filtering, owner and domain
isolation, deletion without restoration, and idempotent startup backfill. The
browser flow on a disposable database confirmed initial provisioning, one-click
chat, visible default scope, and end-of-chat proposals. Existing local services
and workspace data were not restarted or migrated during validation.

## Project meeting first version — September 12, 2026

Added optional project association using existing knowledge domains, a compact
Project & knowledge dialog, explicit versioned disclosure grants, restricted meeting
retrieval, and answer citations in Assistant activity. The project is fixed after
capture/participation begins; knowledge can be revoked independently. Private meeting
messages do not grant personal-workspace access.

Project updates now reuse the existing proposal review and versioned memory writes.
Extraction covers bounded transcript batches, excludes private chat and known bot
output, checks evidence IDs, and restricts replacement targets to the primary project.
Reviewed writes validate transcript fingerprints and target versions. Deleting source
meeting evidence removes linked drafts and reviewed derivatives. New tables are added
on startup without rewriting existing recordings. See [Project meetings](PROJECT_MEETINGS.md)
for the complete user flow, API surface and remaining limitations.

Validation: 224 Python tests passed; one optional PostgreSQL test was skipped. All
66 JavaScript tests passed. New integration tests cover default/foreign-owner/project
isolation, sharing consent, references, fixed projects, stale settings, reply citations,
revocation during generation and audio output, changed sources, reviewed learning,
replacement conflicts, provider failure, and an additive schema upgrade. A two-meeting
case confirms that an approved update is available only when explicitly shared into
the next meeting.

Browser checks used an isolated workspace with synthetic Atlas/Beacon projects:
meeting creation, knowledge selection, draft preparation, evidence review, confirmation,
and saved-answer source inspection passed. The UI was checked at desktop and 375 px
mobile widths, with light/dark themes and reduced motion. A live model check with
synthetic project context returned a valid memory citation and three evidence-backed
update drafts, preserving that a revised release date had not been promised. This is
not a broad model-quality benchmark or a new live Zoom/Google Meet integration test.

The local application was started with the new schema after a SQLite backup. No
Attendee rebuild or new external service is required for project knowledge.


## Meeting transcript and project setup fixes — 2026-09-13

Completed Echooo speech now appears in the transcript as separate AI entries, including
historical replies beyond the recent activity limit. New playback anchors use recording
samples; historical positions are visibly approximate. Search includes AI replies;
private chat and uncompleted output remain in activity. AI entries are not human memory
evidence and do not offer misleading original-audio playback controls.

The new-meeting form exposes sharing alongside project selection, with an eligible
memory count and a clear disclosure checkbox. Settings include a select-all control;
empty grants and stale knowledge have visible feedback. The model receives the actual
access limitation instead of being left to infer why project knowledge is missing.

Verification: 231 Python tests passed, with one optional PostgreSQL test skipped;
68 JavaScript tests passed. Regression coverage includes repo retrieval and citations,
project isolation, expiration, legacy transcript recovery, completed audio anchors,
private/interrupted output exclusion and recording deletion.

The browser walkthrough verified creation-time sharing, repairing an empty selection,
and interleaved spoken replies on desktop/mobile and in dark mode. The configured
live model returned the expected repo URL with its authorized memory citation. The
running local app also returned historical spoken replies and the repaired knowledge
selection. No new external meeting call was made for this fix.


## Simplified project access and workspace UI — 2026-09-13

This update supersedes the manual selection and creation-time sharing checkbox above.
Choosing a meeting project now authorizes all its current eligible shareable memories.
Additions and edits apply automatically; visibility, restrictions, expiry and deletion
remain enforced before model access and during playback. Legacy empty or partial
selections no longer block project knowledge. Private chats and delegations retain
their existing permissions.

Project settings show the project, optional goal and a collapsed knowledge preview;
reference projects live under More options. Messages & activity moves from the main
meeting heading to the overflow menu, retaining private messages, errors and citations.
Home, domain, conversation, review and settings pages remove repeated explanatory copy.
Memory editing moves audience/expiry fields behind an expandable section, opened when
existing restrictions need attention. Essential disclosure and destructive-action
consequences remain visible. All interface text stays in English.

Validation: 234 Python tests passed (one optional PostgreSQL test skipped), and
68 JavaScript tests passed. The updated private-context presentation also passed its
10-test JavaScript suite. Browser checks covered project settings on desktop/mobile,
creation without sharing checkboxes, newly reviewed knowledge appearing in an existing
meeting, the secondary activity menu and focus return, and simplified home/domain/
review/conversation/settings pages in light and dark mode. The running local API
confirmed automatic project access. No external meeting call was started for this update.
