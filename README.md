# Echooo

A personal voice assistant for private conversations, domain-based memory, delegated conversations, and meeting notes. You control what the assistant can read, disclose, and save.

## Features

- **Private chat:** start a text or voice conversation with **Talk with Echooo**. Quick chats use confirmed, unexpired memories in `default`; **Choose domains** lets you start a chat with other domains or no memory.
- **Knowledge and memory:** organize information into domains, add memories, or import TXT, Markdown, CSV, JSON, PDF, and DOCX files. Review proposals before saving, control sharing and expiry, and inspect or restore versions.
- **Delegation:** invite one guest into a time-limited conversation with an explicit audience, goal, and knowledge scope. Follow the transcript, approve commitments, and revoke access.
- **Meetings:** invite Echooo AI as an independent online meeting participant through self-hosted Attendee, or record tab audio and microphone together. Follow transcripts, edit passages, play original audio, and generate notes linked to supporting passages.

Reading, disclosure, commitments, and memory updates have separate permissions. Guest replies are checked before publication and speech synthesis; proposed memories require review. Delegation currently supports one guest with owner supervision. External services such as calendars, email, telephony, and payments are not connected; approving a commitment does not execute a transaction.

## Quick start

Requires **Python 3.11+** and a modern browser with AudioWorklet support. No model credentials are needed for the text demo.

```bash
./start.sh
```

Open [localhost:8000](http://127.0.0.1:8000) and create your workspace credentials. The launcher creates `.venv`, installs dependencies, and copies [.env.mock.example](.env.mock.example) to `.env` if missing. Existing settings are preserved. Data persists in `data/echooo.db` by default.

```bash
./start.sh --mock       # Use demo providers for this run
./start.sh --port 8010  # Use a different local port
./start.sh --install    # Refresh dependencies
```

Stop with **Ctrl+C**. To choose Python when creating the environment, use `PYTHON=python3.12 ./start.sh`.

Demo replies are deterministic. Mock STT does not transcribe microphone audio; optional browser speech can read replies aloud.

## Connect live providers

Use [.env.example](.env.example) as a reference to update `.env`, then restart without `--mock`.

| Capability | Settings |
| --- | --- |
| Speech recognition | `STT_PROVIDER=assemblyai`, `ASSEMBLYAI_API_KEY` |
| Language model | `LLM_PROVIDER=openai_compatible`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` |
| Browser speech | `TTS_PROVIDER=browser` |
| Self-hosted CosyVoice | `TTS_PROVIDER=cosyvoice`, `COSYVOICE_BASE_URL`, compatible `COSYVOICE_SPEAKER_ID` |
| DashScope speech | `TTS_PROVIDER=dashscope`, `DASHSCOPE_API_KEY`; model and voice configured with `DASHSCOPE_TTS_*` |

The LLM endpoint must support streaming `/chat/completions` and reliable JSON instruction following. API keys stay on the server; audio and authorized text are sent to the configured providers as needed.

See [Operations](docs/OPERATIONS.md#configuration) for all settings and [DashScope setup](docs/OPERATIONS.md#alibaba-cloud-cosyvoice-setup) for cloud speech and custom voices. Model prompts live in [config/prompts.toml](config/prompts.toml).

## Record a meeting

To have **Echooo AI join as a separate participant**, start the [self-hosted Attendee connector](docs/ATTENDEE.md), then use **Meetings → New meeting → Join online meeting**. It records silently and keeps participating when you close the page; the server and Docker must remain running. Use **Leave online meeting** to remove it.

For browser capture:

1. Open **Meetings → New meeting**.
2. Choose **Tab + microphone** in desktop Chrome, select the meeting or video tab, and enable **Share tab audio**. Use **Microphone only** for in-person meetings.
3. Start recording, follow the transcript, and open **Summary & notes** for notes with source references.
4. Stop recording to finish transcription and, with AssemblyAI configured, check saved audio for gaps. Select a passage to play its original audio; download recordings as WAV.

Tell participants before recording and keep the page open. Each recording is limited to 30 minutes; start another in the same meeting to continue. Tab sharing captures the selected tab's audio, not other desktop apps. Only audio is saved.

Live transcription requires STT; AI notes require a live LLM and should be reviewed. Mock mode saves audio and accepts manual passages, but only produces excerpt-based notes. Workspace JSON exports include meeting text and metadata; download audio separately.

## Deployment

SQLite is the local default. For PostgreSQL, set `POSTGRES_PASSWORD` in `.env` and start the included database:

```bash
docker compose up -d db
```

Then set `DATABASE_URL=postgresql+psycopg://echooo:URL_ENCODED_PASSWORD@127.0.0.1:5433/echooo` and restart. Changing databases does not migrate existing data.

Use **one application worker**. Before public access, complete workspace setup and configure HTTPS, the correct `PUBLIC_ORIGIN`, and `COOKIE_SECURE=true`. See [Operations](docs/OPERATIONS.md) for deployment and backups.

## Development

After `./start.sh` has installed dependencies:

```bash
STT_PROVIDER=mock LLM_PROVIDER=mock TTS_PROVIDER=browser .venv/bin/python -m pytest -q
node --test tests/*.mjs
```

Optional PostgreSQL tests use `ECHO_TEST_POSTGRES_URL` and require an isolated database named `echooo_test*`. They clear application tables; never use your working database.

## Documentation

- [Architecture and information boundaries](docs/ARCHITECTURE.md)
- [Configuration, operations, and backups](docs/OPERATIONS.md)
- [Roadmap and acceptance criteria](docs/ROADMAP.md)
- [Implementation and verification record](docs/IMPLEMENTATION.md)
