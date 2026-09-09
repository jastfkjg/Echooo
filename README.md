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
- Export workspace data and delete domains, sources, and dependent records. Private chats do not expire with time; delegated conversations retain an authorization deadline. Revocation, knowledge changes, and selected-memory expiry still invalidate affected conversations.

**Current scope: a working personal assistant MVP.** A delegation supports one guest with owner supervision. Meeting platforms, telephony, calendars, email, and payment tools are not connected yet. Approval authorizes the exact wording sent to the guest; it does not execute external transactions. The guest interface clearly identifies the assistant as AI.

## Meeting mode

Open **Meetings → New meeting** in the sidebar. Existing private chats, domains,
and delegations remain separate and available.

- **Start recording** captures the microphone and saves PCM audio to the workspace
  database approximately every second. The status reports acknowledged saved audio.
  Pause/resume creates separate playable recordings; a recording is limited to
  30 minutes, after which you can resume in the same meeting.
- Live STT displays interim text and final passages. Meeting capture enables
  AssemblyAI speaker labels (local to each recording, not verified identities).
  Use **Correct** to edit a name or transcript. Word timestamps are used when
  available; otherwise playback boundaries are approximate.
- Select a recording to see its **Recording summary**, **Live summaries**, and
  **Full transcript**, in that order. **Summarize recording** updates one overall
  overview; it does not create a chapter. Live summaries are separate incremental
  highlights, updated about every minute during capture and on pause, followed by
  an overview update. **Update highlights** processes saved text on demand.
- Expand a live summary's source or read the complete transcript below it.
  Continuous same-speaker speech is joined into compact, collapsible paragraphs;
  select a sentence to reveal playback and correction controls. Pending speaker
  IDs display as **Unidentified speaker**, not as a verified identity. Turn off
  **Follow live** when reading earlier content.
- Both summary paths send recognized text, speaker labels and evidence IDs, never
  audio. Each chapter request processes up to 12 passages / 6,000 text characters;
  each overview request folds up to 40 passages / 6,000 characters into the prior
  overview. Model calls have a 40-second limit, with visible progress and retries
  resuming from remaining text. Compatible hybrid models use non-thinking mode.
- Analysis proposes decisions, commitments, actions with owners/dates, open
  questions, possible contradictions, and missing action details, with clickable
  evidence. **Confirm chapter** or **Reject** records human review. Corrections
  invalidate previous analysis. No external actions or memory writes occur.
- Click a passage timestamp or an evidence link to play its recording at that
  position. Recordings can also be downloaded as WAV. Audio is the captured mono
  PCM signal at the configured STT sample rate, not synthesized speech; browser
  microphone processing/resampling still applies.
- The recordings list and player stay above evidence and follow-up. Switching
  recordings changes the overview, highlights, full transcript, findings and audio
  together. Each recording can be deleted with confirmation, removing its audio,
  transcript and associated summaries without deleting other recordings.
- Ending preserves the meeting for review. Deleting a meeting removes its audio,
  transcript and analysis from the application database. JSON workspace export
  includes meeting metadata and text; download audio separately.

Live recognition requires configured STT; AI analysis requires a live LLM.
Mock mode saves microphone audio and accepts manually entered passages, but its
chapter summaries are literal excerpts and it does not infer meeting findings.
Tell participants before recording. Current capture is the browser microphone,
not system audio or a meeting-platform bot. Keep the page open while recording;
leaving it stops capture. A sudden browser/network loss can lose unacknowledged
audio and the final partial transcript; previously acknowledged audio persists.
The existing single-worker deployment requirement also applies to meetings.

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
| Alibaba Cloud CosyVoice | `TTS_PROVIDER=dashscope` and `DASHSCOPE_API_KEY` | Async WebSocket streaming; defaults to `cosyvoice-v3-flash`, `longanyang`, 24 kHz PCM16; no local model required |

Public replies from a live LLM follow **structured draft → independent check → publication**. This increases first-response latency, an intentional tradeoff in this release. The server filters knowledge before inference; it does not send a complete personal profile and merely instruct the model to keep it secret.

Every STT, LLM, and TTS provider uses the same authorization and memory-writing layer. That layer is the core of Echooo; speech APIs are replaceable infrastructure.

- [AssemblyAI Streaming documentation](https://www.assemblyai.com/docs/streaming)
- [CosyVoice repository](https://github.com/FunAudioLLM/CosyVoice)
- [DashScope CosyVoice WebSocket API](https://help.aliyun.com/zh/model-studio/cosyvoice-websocket-api)
- Model behavior: [config/prompts.toml](config/prompts.toml)

### Alibaba Cloud CosyVoice setup

Add these settings to your server's `.env`, using a Beijing-region DashScope API key:

```dotenv
TTS_PROVIDER=dashscope
DASHSCOPE_API_KEY=your-api-key
DASHSCOPE_TTS_URL=wss://dashscope.aliyuncs.com/api-ws/v1/inference
DASHSCOPE_TTS_MODEL=cosyvoice-v3-flash
DASHSCOPE_TTS_VOICE=longanyang
DASHSCOPE_TTS_SAMPLE_RATE=24000
DASHSCOPE_TTS_TIMEOUT_SECONDS=60
```

The shared Beijing endpoint remains supported. For a workspace-specific endpoint, use
`wss://YOUR_WORKSPACE_ID.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference`.
For Singapore, use `wss://YOUR_WORKSPACE_ID.ap-southeast-1.maas.aliyuncs.com/api-ws/v1/inference`
with that region's key and available model/voice. See the official API documentation above.
Use a **DashScope API key**, not an Alibaba Cloud AccessKey ID/Secret.

Restart with `./start.sh` (preserve any existing `--port` option). Do not use `--mock`,
which overrides TTS to browser speech. Start voice and unmute output in a conversation.
Microphone transcription still requires a configured STT provider; enabling cloud TTS
does not enable speech recognition. API keys remain on the server.

`longanyang` is a Mandarin/English male voice; `longanhuan` is a female alternative.
Choose a [voice compatible with the model and region](https://help.aliyun.com/zh/model-studio/cosyvoice-voice-list).
For supported Qwen-Audio-TTS and CosyVoice models, the conversation's **Voice options**
menu offers model-matched presets and saves the selection for that conversation. The session API can also
override the cloud voice with `voice: {"dashscope_voice": "longanhuan"}`;
the self-hosted `speaker_id` (such as `中文女`) is not sent to DashScope.
Existing sessions without this override use `DASHSCOPE_TTS_VOICE`.

Echooo can upload a WAV, MP3, or M4A sample from **Voice options → Manage custom voices**,
create a model-bound cloned voice, query the account's compatible cloned voices, and delete
them. Uploaded samples use Alibaba Cloud's temporary OSS flow and are not saved by Echooo;
Alibaba removes those temporary objects after 48 hours. This flow is intended for development
and light use. Configure long-lived OSS for production or high-concurrency deployments.
The DashScope workspace must expose the `voice-enrollment` service. If the TTS inference key
does not have that model, configure a same-account management key with
`DASHSCOPE_VOICE_API_KEY` and, when needed, override `DASHSCOPE_TTS_CUSTOMIZATION_URL`.
For a Beijing shared-domain management key, use:

```env
DASHSCOPE_VOICE_API_KEY=sk-your-model-studio-key
DASHSCOPE_TTS_CUSTOMIZATION_URL=https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization
DASHSCOPE_UPLOAD_URL=https://dashscope.aliyuncs.com/api/v1/uploads
```

To expose a voice created outside Echooo without querying it first, add its `voice_id`
to the comma-separated `DASHSCOPE_TTS_CUSTOM_VOICES` setting and restart Echooo. It will
then appear in Voice options. Custom voices remain bound to the model and region used
when they were created.

Only checked replies are synthesized. Audio streams directly as mono PCM16 through the
existing browser player; no temporary audio files or decoding dependencies are required.
Interrupting, muting, ending a session, or losing authorization closes the active cloud
connection. Retry audio reuses the checked reply without calling the LLM again.
Missing keys fail startup; synthesis, network, or quota failures preserve the text and
show the existing playback error. The timeout bounds connection setup and time waiting
for incoming events, rather than the total spoken duration.

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
