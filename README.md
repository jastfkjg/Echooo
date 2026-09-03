# Echooo

A personal voice assistant built around **user-defined knowledge domains and explicit delegation**. Organize your own information or authorize the assistant to speak with someone on your behalf. Each conversation has separate permissions for reading, disclosure, actions, and memory updates.

Each workspace starts with a `default` domain for everyday conversations and memories. You can create, name, edit, and delete additional domains for your own contexts, such as personal life, work, or individual projects.

The interface and project documentation use English by default. Your domain names, sources, memories, and conversation records retain their original language. Live model replies follow the language of the latest message.

## What this release supports

- Create a private workspace and sign in to manage any domains you choose.
- Enter memories in a specific domain or import TXT, Markdown, CSV, JSON, PDF, and DOCX files. Extracted information becomes a proposal for review, not immediately available knowledge for public replies.
- Mark memories as private or shareable, restrict their audiences, set expiry dates, inspect provenance and versions, and edit or restore earlier content.
- Create private conversations or time-limited delegations with a specific audience, goal, knowledge scope, and destination domain for memory updates.
- Invite one participant to speak with the AI assistant. The owner can follow the transcript, keep private notes, approve new commitments, and end or revoke access.
- Use text or a microphone. Public replies are checked before reaching the browser or speech synthesis, and can be interrupted.
- Review attributed statements, approval records, and proposed memories after a conversation. Edit, reject, or save proposals as new or replacement memories in the **authorized destination domain**.
- Export workspace data and delete domains, sources, and dependent records. Revocation, knowledge changes, and expiry invalidate affected conversations.

**Current scope: a working personal assistant MVP.** A delegation supports one guest with owner supervision. Meeting platforms, telephony, calendars, email, and payment tools are not connected yet. Approval authorizes the exact wording sent to the guest; it does not execute external transactions. The guest interface clearly identifies the assistant as AI.

## Start a conversation

Click **Talk with Echooo** on the home page, in the sidebar, or in Conversations.
A private chat opens immediately in `default`; no manual domain selection or conversation title is required.
The title is generated from your first message. Turn on the microphone and enable
**Read replies aloud** for voice interaction when real STT is configured.

Quick chats use the confirmed, unexpired memories in `default` and propose updates
to that domain when the conversation ends. Proposals require review before they
become memories. Other domains are never included automatically. **Choose domains**
opens a selector for a fresh private chat with explicitly selected memories; you
can also deselect all domains to chat without memory. Previous transcripts remain
in their original conversations and are not copied into the new context. The
domain page still offers a shortcut with that domain selected.

Existing workspaces with no domains receive `default` at startup. It is an ordinary
editable domain. If you rename or delete it, the next quick chat creates a new,
empty `default`; deleted information is not restored.

Use **Save memory** to choose one of your own messages, edit the information, and
pick a destination domain (or create your first domain). This creates a proposal
for review; it does not expand the current chat's reading permissions. In scoped
chats, the destination must belong to the selected domains. **Delegate** always
creates a separately authorized guest conversation without copying private history.

## Run locally

Requirements: Python 3.11+ and a modern browser with AudioWorklet support. The text demo requires no model credentials.

```bash
./start.sh
```

The launcher creates `.venv` if needed, installs project and development dependencies,
and copies `.env.mock.example` only when `.env` is missing. Later runs reuse the
environment, reinstalling dependencies only when `pyproject.toml` changes or you
pass `--install`. Existing `.env` settings are preserved. No manual activation is needed.

```bash
./start.sh --mock             # Use demo providers for this run
./start.sh --port 8010        # Use localhost:8010 with matching origin/cookie settings
./start.sh --install          # Refresh dependencies
./start.sh --help
```

Stop with **Ctrl+C**. You can also invoke `/path/to/echooo/start.sh` from another
directory; the script starts from the repository root so data paths stay consistent.
To choose Python when creating `.venv`, use `PYTHON=python3.12 ./start.sh`.

Open the [local workspace](http://127.0.0.1:8000) and set a username and a nonempty password. Data is saved to `data/echooo.db` by default and survives restarts. Complete initial setup before exposing the service publicly.

If your package mirror is missing a dependency, use the official index for this installation:

```bash
PIP_INDEX_URL=https://pypi.org/simple ./start.sh --install
```

Manual setup remains available: create and activate a Python virtual environment,
install with `python -m pip install -e '.[dev]'`, create `.env` from the example if
needed, and run `python -m echooo` from the repository root.

Suggested first walkthrough:

1. Create a domain, such as “Northstar product research.”
2. Add two memories: mark an internal resource plan as **Private**, and a progress update as shareable with the audience **Client**.
3. Select **Delegate**, enter **Client** as the audience, choose the domain, and explicitly select **Disclose** for the progress update.
4. Create an invitation and open it in another browser or private window. Keep the owner view open for supervision.
5. Ask about progress and internal resources, then request a new commitment. Observe the disclosure boundary and approval flow.
6. Select **End and review**, then edit, approve, or dismiss the proposed memories in **Review**.

Demo mode uses deterministic matching against authorized facts; it does not represent live model conversation quality. Mock STT cannot transcribe microphone input. **Read replies aloud** enables optional browser speech. Each invitation can be redeemed once; creating another invitation revokes previous guest credentials.

## Connect speech and language models

Update `.env` using [.env.example](.env.example), then restart the service:

| Capability | Configuration | Notes |
| --- | --- | --- |
| Speech recognition | `STT_PROVIDER=assemblyai` and `ASSEMBLYAI_API_KEY` | AssemblyAI v3 WebSocket; browser input is 16 kHz mono PCM16 |
| Understanding and replies | `LLM_PROVIDER=openai_compatible`, URL, model, and API key | Streaming `/chat/completions`; requires reliable JSON instruction following |
| Browser speech | `TTS_PROVIDER=browser` | Opt-in playback; prefers local voices, but the device may use cloud speech |
| Self-hosted synthesis | `TTS_PROVIDER=cosyvoice` | Official FastAPI protocol; this release uses a preset speaker and requires a compatible SFT model and speaker ID |

Public replies from a live LLM follow **structured draft → independent check → publication**. This increases first-response latency, an intentional tradeoff in this release. The server filters knowledge before inference; it does not send a complete personal profile and merely instruct the model to keep it secret.

Every STT, LLM, and TTS provider uses the same authorization and memory-writing layer. That layer is the core of Echooo; speech APIs are replaceable infrastructure.

- [AssemblyAI Streaming documentation](https://www.assemblyai.com/docs/streaming)
- [CosyVoice repository](https://github.com/FunAudioLLM/CosyVoice)
- Model behavior: [config/prompts.toml](config/prompts.toml)

## PostgreSQL and deployment

SQLite supports a simple local setup. PostgreSQL is recommended for deployment. Owner-level row-level security (RLS) is implemented and has been tested against a real PostgreSQL instance. Domain and disclosure permissions are still enforced by the application service; RLS is not a model safety guarantee.

An optional local database service is included. Set `POSTGRES_PASSWORD` in `.env`, then run:

```bash
docker compose up -d db
```

Set `DATABASE_URL` to `postgresql+psycopg://echooo:URL_ENCODED_PASSWORD@127.0.0.1:5433/echooo` and restart the application. SQLite and PostgreSQL are separate data sources: **changing the connection does not migrate existing data**.

See [Operations](docs/OPERATIONS.md). Room coordination and cancellation currently run in one process, so use **one application worker**. Public access requires HTTPS, the correct `PUBLIC_ORIGIN`, and `COOKIE_SECURE=true`.

## Tests

```bash
STT_PROVIDER=mock LLM_PROVIDER=mock TTS_PROVIDER=browser python -m pytest -q
python -m compileall -q src tests
node --check web/app.js
node --check web/voice.js
```

PostgreSQL integration tests require an isolated database named `echooo_test*`. Tests clear its application tables; never point them at your working database:

```bash
ECHO_TEST_POSTGRES_URL='postgresql+psycopg://USER:PASSWORD@HOST/echooo_test' \
STT_PROVIDER=mock LLM_PROVIDER=mock TTS_PROVIDER=browser \
python -m pytest tests/test_product.py -q
```

Tests cover domain isolation, separate disclosure permissions, one-time invitations, credential and conversation revocation, revocation during generation, private notes, commitment approval, attributed learning, version conflicts, deletion propagation, STT-to-checked-audio flow, interruption, persistence, and PostgreSQL RLS. Recognition accuracy, voice quality, and network latency require acceptance testing with your actual providers.

## Documentation and direction

- [Architecture and information boundaries](docs/ARCHITECTURE.md)
- [Configuration, operations, deletion, and backups](docs/OPERATIONS.md)
- [Roadmap and acceptance criteria](docs/ROADMAP.md)
- [Implementation scope and verification record](docs/IMPLEMENTATION.md)

The previous unauthenticated `/ws` demo, unchecked streamed output, and voice-sample upload flow have been removed. The new endpoint is `/ws/sessions/{id}`, with identity and scope checks. Do not combine the old frontend with the new service.
