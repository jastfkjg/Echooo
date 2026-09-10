# Operations and deployment

## Local setup and upgrading from the old demo

Run `./start.sh` from the source checkout, or invoke the script by its full path.
It creates `.venv` when missing, installs project and development dependencies on
first use or when `pyproject.toml` changes, and creates a demo `.env` only if none
exists. Subsequent runs reuse the environment. Use `--install` to repair or refresh
dependencies, and Ctrl+C to stop. Set `PYTHON` to choose the interpreter when creating
the environment; an existing `.venv` is reused and must contain Python 3.11+.

`./start.sh --mock` temporarily selects demo providers without editing `.env`.
`./start.sh --port 8010` sets the port, binds to `127.0.0.1`, sets the matching HTTP
origin, and disables secure-only cookies for local HTTP. These flags affect only
the current run; without them, environment variables and existing `.env` settings
apply as usual. The launcher runs one server in the foreground and does not start
PostgreSQL, live model services, or a browser automatically.

For manual setup, use `python -m pip install -e '.[dev]'` and `python -m echooo`.
Web assets and prompts are loaded from the repository. This release is not a
standalone wheel that can run without the source tree.

The new version creates its database tables on first launch, with no seeded domains or personal information. The old demo had no persistent personal database, so its in-memory conversations do not need migration. Compare your existing `.env` with the examples: change the former `TTS_PROVIDER=mock` to `browser`. The generic `/ws` and voice-sample upload endpoints have been removed. Existing `.env` files and keys are not overwritten.

Data is stored at `DATABASE_URL`. Relative SQLite paths are resolved from the working directory, so start the application from the repository root. Changing databases does not transfer existing content. Startup includes an idempotent upgrade making the conversation memory destination optional. SQLite rebuilds only the sessions table in a transaction, preserving rows, dependent records, indexes, and triggers; PostgreSQL drops the column’s NOT NULL constraint. Stop existing application processes and keep a backup before upgrading, then restart normally. A full Alembic migration framework and JSON import/restore are not provided.

## Configuration

| Setting | Description |
| --- | --- |
| `DATABASE_URL` | SQLite or SQLAlchemy psycopg PostgreSQL URL; URL-encode special characters in passwords |
| `APP_HOST` / `APP_PORT` | Defaults to 127.0.0.1:8000; keep development servers private |
| `PUBLIC_ORIGIN` | Full browser-facing origin without a path, such as https://assistant.example.com |
| `COOKIE_SECURE` | Must be true for public HTTPS deployment; false for local HTTP |
| `STT_PROVIDER` | mock or assemblyai; mock supports text but does not recognize speech |
| `LLM_PROVIDER` | mock or openai_compatible |
| `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY` | Trusted chat/completions service; credentials remain server-side |
| `LLM_TIMEOUT_SECONDS` | HTTP timeout, default 60 seconds; public replies normally require both draft and checker calls |
| `TTS_PROVIDER` | browser, cosyvoice or dashscope; recording and playback require explicit user action |
| `COSYVOICE_*` | Trusted private service address, output sample rate, timeout, and preset speaker |
| `DASHSCOPE_API_KEY` | Required for dashscope; region/workspace-matched DashScope key, server-side only |
| `DASHSCOPE_VOICE_API_KEY` | Optional separate server-side key for voice cloning/list/delete; defaults to `DASHSCOPE_API_KEY` |
| `DASHSCOPE_TTS_URL` | WSS endpoint; defaults to the shared Beijing endpoint; supports workspace-specific Beijing/Singapore endpoints |
| `DASHSCOPE_TTS_MODEL` / `DASHSCOPE_TTS_VOICE` | Default cosyvoice-v3-flash / longanyang; voice must match model and region |
| `DASHSCOPE_TTS_CUSTOM_VOICES` | Optional comma-separated, pre-created DashScope custom voice IDs exposed in the web voice picker |
| `DASHSCOPE_TTS_CUSTOMIZATION_URL` | Optional HTTPS override for the DashScope voice cloning/list/delete endpoint; derived from `DASHSCOPE_TTS_URL` by default |
| `DASHSCOPE_UPLOAD_URL` | DashScope temporary-file upload credential endpoint used for browser voice samples |
| `DASHSCOPE_TTS_SAMPLE_RATE` | Mono PCM16 output; default 24000; supported rates: 8000, 16000, 22050, 24000, 44100, 48000 |
| `DASHSCOPE_TTS_TIMEOUT_SECONDS` | Positive finite setup/receive-idle timeout, default 60 seconds; connection handshake capped at 15 seconds |

Browser input is fixed at 16 kHz mono PCM16 in 100 ms frames. This release rejects other STT input sample rates. CosyVoice output rate must match the checkpoint. Preset mode requires a compatible SFT checkpoint; do not assume every checkpoint provides preset voices. Speaker IDs are literal provider values and should not be translated.

DashScope setup and endpoint examples are in the README. Cloud synthesis uses the configured
default voice or the session's `voice.dashscope_voice`, independently of self-hosted
`voice.speaker_id`. Restart after configuration changes; `./start.sh --mock` overrides TTS
to browser speech. Each checked reply owns one cloud connection, which is closed on
completion, mute, interruption, disconnection or authorization revocation. Failed calls
are not automatically retried; the explicit Retry audio action reuses the last checked text.

Upload limits: 5 MB per file; 100,000 extracted characters; up to 100 PDF pages. Encrypted PDFs and image-only scans are unsupported. DOCX uncompressed content is limited to 20 MB. Only extracted text is stored, not the original binary file. Conversations may select up to 12 domains and 100 memories, last up to 100 turns, and be authorized for 5 minutes to 24 hours. Extraction has a proposal-count limit; it does not guarantee exhaustive coverage of long sources. Important facts can be entered manually.

## PostgreSQL

Use an existing instance or the local `docker compose` database described in the README. Compose starts only a database, bound to localhost; it is not a complete production deployment. Stop it with `docker compose down`. Adding `-v` deletes its persistent volume.

The initialization connection needs privileges to create tables, create or grant the `echooo_scoped` role, and manage RLS policies. Application-data transactions switch to that restricted role; authentication and initialization remain trusted administrative paths. If a managed database prohibits CREATE ROLE, an administrator must create the role and grant the required privileges. This release does not separate migration and runtime accounts and should not be exposed as a publicly registered multi-tenant SaaS.

## Public access

1. Complete initial owner setup locally and use a long random password. There is no email recovery flow in this release, so keep the credential safe.
2. Use trusted model endpoints. Audio goes to STT; authorized facts and conversation text go to the LLM; checked replies go to the configured TTS provider. Selecting private facts for a private conversation allows those facts to be sent to that LLM.
3. Provide HTTPS and WebSocket upgrades through a trusted reverse proxy. Set `PUBLIC_ORIGIN` accurately and enable `COOKIE_SECURE=true`. Trust forwarded headers only from your proxy and avoid exposing the backend port directly.
4. Run one application worker. Scaling requires shared revocation notices, cancellation, room distribution, and rate-limit state.
5. Configure connection limits, request rates, body-size limits, and timeouts at the proxy. The application has login-attempt and content limits, but not comprehensive public abuse controls or model-spending quotas.
6. Keep CosyVoice on a private network with restricted management ports. Do not expose unauthenticated inference servers publicly.

Full audio is not logged to files. Current logs are basic web-service logs. Avoid adding tokens, message content, or full model requests while debugging. Invitation fragments do not enter HTTP URL logs, but proxies should also avoid logging the redemption request body.

## Revocation, deletion, export, and backups

- Initial setup includes an empty `default` domain. On startup, existing workspaces with no domains receive one without changes to their conversations. Quick chat reuses the owner's domain named `default`, or creates an empty one if it was deleted or renamed; no deleted memories are restored.
- Revocation stops further conversation and playback. A normal ending also attempts memory extraction. If extraction fails, the transcript remains available and the owner can retry.
- Updating a domain or an authorized memory revokes affected active conversations. Create a new authorization to use the latest knowledge and scope.
- Domain, source, and memory deletion propagates to dependent conversations and derived memories. A mixed-domain conversation is removed as a whole, not sentence by sentence. Review the consequences in the interface.
- Owner-only JSON exports include private sources and evidence, but exclude passwords, keys, and login tokens. Export is for inspection and portability, not automatic restore.
- SQLite enables foreign_keys, WAL, and secure_delete, but does not guarantee irrecoverable disk erasure. Use disk encryption and restricted permissions for database files and backups.
- Back up SQLite consistently with a backup tool or by stopping the application. Do not copy only a live main database file while ignoring WAL. Use a tested pg_dump and restore process for PostgreSQL.
- Deletion does not rewrite old backups, provider logs, or downloaded files. Production needs backup retention and provider policies, plus replay of required deletions after restore. There is no independent deletion-ledger service yet.

## Live-service acceptance

Start with synthetic data and enable STT, the live LLM, and TTS separately. Validate:

- English, Mandarin, mixed-language speech, pauses, and noise, including transcription and turn boundaries.
- Questions about other domains, attempts to change permissions, and malicious source content.
- Implicit commitments and the distinction between historical and new commitments; fallbacks when checks fail.
- Speaking during playback, revocation during generation, invitation rotation, refresh, and network recovery.
- P50 and P95 latency from the end of speech to first audible reply, false interruptions, and useful-answer rate.
- Attribution in memory proposals, incorrect merges, and the proportion requiring owner edits.

Automated tests use simulated provider events or HTTP transports to verify protocols and authorization. They have not submitted acceptance audio to live AssemblyAI, LLM, or CosyVoice services or measured actual voice quality. `/health` reports that the web service is running, not that every provider is connected.


## Meeting transcription recovery

Live audio saving does not wait for the STT socket. Reconnects use absolute audio
sample offsets and connection-scoped turn IDs. When a recording stops, a durable
verification job checks the saved audio and fills uncovered word intervals;
existing text and edits remain intact. Summary refresh happens after verification.
The `meeting_recording_transcriptions` table is created on startup without a
recordings-table rewrite. In-flight jobs resume at startup or when the meeting is
opened. Run only one application worker, including recovery workers.

Use `POST /api/meetings/{mid}/recordings/{rid}/transcribe` to check a saved recording
or retry a failed check. It returns 202 with meeting state; poll the existing
meeting detail endpoint for `recordings[].transcription`. `verified_samples`
tracks audio processing coverage, not the time of the final recognized word.
`phase=complete` does not certify speech recognition accuracy. Summary errors
are independent (`summary_phase`, `summary_error`) and can be retried from the UI.

`ASSEMBLYAI_API_URL` defaults to `https://api.assemblyai.com`; set the appropriate
regional REST endpoint alongside the streaming endpoint when using regional data
residency. API credentials are server-only. Uploads use bounded chunks, and an
optional `ffmpeg` installation converts WAV to lossless FLAC in memory. Submitted
job IDs are retained for retries. Logs contain recording IDs and error types,
not provider keys or transcript contents. Back up SQLite with its backup API
(or stop the service before copying); an ordinary copy can miss committed WAL data.


## Topic-based meeting notes

The `meeting_minutes` table is created on startup, owner scoped with the same
meeting/recording deletion boundaries as the transcript. One document is stored
per meeting and recording scope; legacy chapters and overviews are retained for
compatibility but no longer rendered in the reading view.

`POST /api/meetings/{mid}/minutes?recording_id={rid}` folds pending transcript
passages into the current document. Repeat while `summary_remaining` is nonzero.
`force=true` rebuilds from the beginning; use it on the first request only, then
continue normally. Transcript revisions automatically trigger rebuilding. Failed
model calls retain the last saved document or completed batch. Audio verification
refreshes these minutes automatically. Detail responses include `minutes`; use
revision, evidence coverage and status to identify outdated or partial documents.

`PATCH /api/meetings/{mid}` renames a meeting, and `GET /api/meetings/{mid}/export`
downloads meeting JSON without binary audio or provider job details. Both use the
existing owner authentication. The library owns these management actions; the
recording selector owns audio download/deletion. Source dialogs retain original
passage IDs and navigate without autoplaying audio.
