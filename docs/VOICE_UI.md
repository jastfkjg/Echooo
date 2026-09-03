# Conversation and voice controls

The conversation uses the full workspace height, with one scrolling transcript
and a persistent composer. The message column has a readable maximum width;
the conversation itself is not a nested card.

- **Start voice** explicitly enables microphone capture and reply playback.
  Recording never starts on navigation, reconnect, or page reload.
- **End voice** stops capture, releases tracks, cancels the current reply and
  playback, and leaves the text conversation open.
- **Pause microphone**, **Mute replies**, and **Interrupt reply** are distinct
  actions. Muting does not disable recording; interrupting does not end voice.
- **Dictation only**, under Conversation settings, transcribes into the existing
  draft. It does not generate a message or reply until the user sends the draft.
- Voice status comes from capture readiness, reply processing, and actual
  playback start/drain events. A server becoming idle does not imply recording.
- Playback and microphone failures remain visible near the voice controls until
  dismissed, retried, or voice ends. TTS retry reuses the last checked reply in
  the current authorized connection; it does not call the LLM again.
- Audio packets queued before interruption cannot restart playback. Microphone
  permission requests completed after cancellation immediately release tracks.

The prominent Domains control sits in its own row below the conversation header.
It shows domain names and an explicit Change domains action (View access for a
delegation). The private scope picker puts domain choices first, including Chat
without memory; memory access, suggestions, and advanced settings expand on
demand. It retains unchecked memories across domain changes. Its footer stays
visible while the content scrolls on small screens.

Conversation settings still contains domain selection and voice preferences.
Changing domains creates a new conversation with fresh authorization; it does not
silently change an existing conversation's knowledge scope. More actions contains
delegation, ending/review, renaming, deletion, and memory proposal creation.
Individual owner messages expose Save memory on hover or keyboard focus; touch
devices retain a compact accessible icon. Destination and review rules still apply.

## Conversation management

- The conversation list supports searching titles, domains, and audiences;
  filtering private/delegated/empty conversations; renaming; and confirmed deletion.
  Expired sessions display Expired, not Active · Expired.
- Talk with Echooo reuses the latest private conversation only when it is empty,
  active, unexpired, and has the same default knowledge snapshot and permissions.
  Otherwise it starts a fresh default conversation. It never revives expired or
  revoked authorization, reopens an older empty conversation, or imports another
  domain's history. Reusing the already open chat preserves its local draft and
  does not restart audio. Server-side transaction locking prevents duplicate empty
  chats from concurrent quick-chat requests.
- `PATCH /api/sessions/{id}` changes only the validated title. `DELETE` removes that
  owner's conversation, messages, proposals, actions, and conversation audit rows;
  it also revokes guest credentials and closes active connections. Pending replies
  or memory extraction cannot persist output after deletion.
- Deletion is permanent and requires a confirmation dialog. Confirmed memories,
  their saved evidence/version history, and other conversations are preserved.
  This is not the broader privacy purge used when deleting a domain or memory.

Chat context is closed by default. It opens as an accessible right-side dialog
and can be pinned beside the conversation on wide screens. Narrowing a pinned
layout returns it to an overlay. Delegated conversations retain visible invite,
revoke, and pending-approval indicators. Owner supervision cannot activate audio.

## WebSocket additions

- `playback.configure { enabled: boolean }`: client playback preference; skips
  synthesis when disabled. New clients send `false` on connection. Legacy
  clients retain their previous local playback gate.
- `playback.retry`: replays the connection's last checked reply when output is
  enabled and no reply task is running. All authorization checks remain active.
- `audio.enable { dictation?: boolean }` and `audio.mode { dictation: boolean }`:
  select draft transcription rather than automatic reply generation.
- `transcript.final { content }`: dictation result, not a persisted chat message.
- `session.state: idle`: no current text generation; not microphone state.
- `error { code: "tts_unavailable", message }`: persistent playback failure UI.

## Appearance

The default appearance is light: a white canvas, pale sidebar, dark primary
actions, and restrained green accents. The existing dark theme is available in
the sidebar and Workspace settings. Sign-in, invitation, and guest screens also
offer Light/Dark controls. The choice is stored under `echooo.theme` in browser
local storage, applied before first paint by an external CSP-safe script, and
synchronized across tabs. Missing/invalid preferences default to light regardless
of the OS. When storage is blocked, switching still works for the current page.
Theme changes do not rerender the conversation or interrupt drafts/audio.

Semantic palettes, including overlays, native form controls, status colors, and
hover states, live in `web/theme.css`. Contrast checks cover both modes.

## Verification commands

```sh
node --test tests/test_voice_controls.mjs tests/test_session_ui.mjs tests/test_theme.mjs
STT_PROVIDER=mock LLM_PROVIDER=mock TTS_PROVIDER=browser .venv/bin/python -m pytest -q
```

Use an isolated database for browser checks: desktop/mobile layout, native menu
keyboard behavior, context open/close/pin, message-level save prefill, domain
selection, text sending, and ended-session review. Never record from a physical
microphone without explicit permission. Audio control tests use fake capture,
synthesis, and playback objects; they do not validate external provider audio
quality. CosyVoice configuration and service deployment are unchanged.

Restart the application backend and reload the browser together to use the new
WebSocket controls. A browser-only refresh against an older server is insufficient.
