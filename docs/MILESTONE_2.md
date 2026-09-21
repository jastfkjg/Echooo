# Milestone 2 — Governed participation

Echooo privately suggests evidence-backed questions about material contradictions
or missing decision details. The meeting owner can edit and approve the exact
wording, defer it, dismiss it or cancel pending speech. Generating a suggestion
never authorizes speaking or adds anything to the approved meeting record.

## Behavior

- Both browser and bot transcripts trigger a separate background check of saved
  final passages. A chronological projection joins same-speaker fragments into
  versioned speech units; late repairs are placed by audio timestamps, not insertion
  order. Terminal STT punctuation (or a standalone text note) marks a boundary;
  this is a conservative heuristic, not a grammatical completeness guarantee.
  Complete units settle for 1.2 seconds, with a 0.4-second scheduling tick. Incomplete
  speech is never force-submitted on timeout: polling stops after 3 seconds and
  resumes when new transcript arrives. A live LLM is required.
- New/revised units drive incremental checks, with up to 40 recent complete units
  plus older proposal/finding evidence (48,000-character total bound). Cross-fragment quotes
  map back to independently validated original evidence. Detection uses semantic
  model judgment, not keyword classification. Implicit changes invite neutral
  confirmation; explicit supersession, different activities and scopes are distinct.
- Clear issues need no additional turn. Only an uncertain model result can request
  one recheck after 2 seconds. The original check and recheck share a 15-second
  deadline; an individual first model call is capped at 12 seconds. These are
  service time limits, not a guarantee of successful suggestions within that time.
  Append-only discussion gets one bounded relevance refresh instead of unconditional
  cancellation. Changed source evidence still invalidates drafts. Approval and speech
  retain fresh relevance checks. Model failures are visible, not treated as no issue.
- Owner-only check history records outcome, latency, input versions and source IDs.
  It does not store model reasoning or duplicate private transcript text.
- Questions, reasons, original wording, evidence snapshots and owner reviews are
  stored independently of findings. Reloading preserves them. Dismissed, deferred
  and delivered suggestions participate in semantic duplicate suppression; identical
  issue/evidence combinations also have a deterministic duplicate check.
- Later discussion can mark a proposal obsolete. Corrections to its evidence or
  ending the meeting invalidate pending proposals. Approving and delivering both
  require a fresh semantic relevance check against the current discussion.
- **Ask in meeting** or **Play locally** directly authorizes the displayed wording,
  without a confirmation dialog. **Edit** opens an inline draft; the primary action
  submits that exact draft. It is sent to TTS, not to the answer
  generator for rewriting. The owner review and original wording remain inspectable.
- The issue type is a visible badge and its reason stays below the question.
  **Supporting conversation** folds detailed evidence and review history. Adjacent
  same-speaker evidence fragments are grouped chronologically with one attribution,
  time range and source control per group. Exact continuous excerpts are joined;
  omitted or unverifiable transitions remain marked or separate. Source controls
  retain every original evidence ID; transcript data and approval checks are unchanged.
  **More → Save for later** moves an item into a collapsed saved section, without
  reminders or automatic speech. **Dismiss** moves it into history. Drafts survive
  live updates while the proposal revision is unchanged; changed revisions require
  reviewing the latest question. Duplicate submissions are blocked while checking.
- Online meeting speech requires an active Attendee participant, live STT, server
  TTS and **Answer when called** enabled.
- During browser-only recording, **Play locally** uses the browser's
  speech synthesis and the device's audio output. It requires no Attendee or server
  TTS. Approval checks relevance; pre-playback reuses that verdict only when the
  complete transcript fingerprint is unchanged and the short-lived receipt remains
  valid. Otherwise it checks the latest context again. A one-shot receipt
  limits playback to the approving tab; refresh never automatically replays it.
  The browser reports completion, failure or cancellation, with a short heartbeat
  lease so disconnected playback is not recorded as completed.
- Exact repeated questions with overlapping unchanged evidence are suppressed even
  when citation subsets differ; existing active duplicates are grouped in the API
  view without deleting their audit records. Semantic paraphrase suppression still
  depends on the model. Internal speech handles are removed from displayed prose.
- Speech checks record allowed/blocked/invalid outcomes and model reason codes.
  Boolean/code contradictions fail closed without declaring the topic resolved.
  Rejected approval stays reviewable with a persistent explanation; playback failures
  remain in the current list for retry. Browser sound-policy errors are explicit,
  paused synthesis is resumed, and missing recording fields in partial snapshots
  do not by themselves cancel playback.
- Local playback keeps microphone and selected-tab capture running without blanking
  audio. Microphone echo cancellation requests `all` when the track advertises that
  capability, otherwise it keeps ordinary browser AEC. Shared-tab audio is unchanged.
  Assistant output remains in separate speech events, not human utterances. No text
  similarity filter deletes participants' repetitions, quotations or objections.
  Browser AEC is best-effort: residual acoustic echo can still be transcribed; this
  is not an application-level residual-echo classifier. Use headphones if needed.
  **Stop** stops playback; new saved transcript changes also stop it through
  the heartbeat check, not immediate voice activity detection. Stopping recording
  or leaving the page also stops local speech.
  Local voices/languages depend on the browser and operating system. This path
  plays through the device; it does not inject audio into a remote meeting.

- The existing Stop, voice interruption, disable-voice and leave controls cancel
  speech. **Stop** also cancels one queued suggestion. New saved transcript
  changes during approved speech stop further output conservatively. Words already
  played cannot be retracted. Interrupted delivery is never marked completed.
- Failed or cancelled delivery can be explicitly reviewed again in **Previous
  suggestions**. It requires new approval and a fresh relevance check. Restarted
  servers cancel approved/in-flight suggestions instead of replaying them.
- Completed questions appear as Echooo AI speech, separately from human evidence.
  Approving speech does not approve a finding or save a project memory.
- Findings now also support **Contradiction** and **Risk**, including category
  corrections with review history and approved-only record/export sections.

The dashboard is owner-only. Platform private chat is not used for this workflow.
The prototype uses the application's existing single-process task coordination;
running multiple API workers requires shared queue/locking work.

## Continuous-capture local playback check

1. Refresh the app and start a new recording (new microphone constraints apply
   when capture opens). Test both microphone-only and shared-tab recording.
2. Approve a local question. Speak during playback and have someone in the shared
   meeting tab speak too. Replay the saved recording: neither input should have a
   silence gap inserted by Echooo. New final transcript text may cancel playback.
3. Repeat or quote the question, then disagree with it. Confirm those human words
   remain in the transcript. A fully completed question should appear separately
   as Echooo AI; a cancelled question must not be marked completed.
4. Repeat with headphones and speakers, at normal and louder volume. Check for
   assistant voice leaking into human transcription. Automated tests cannot verify
   physical AEC performance; record browser/OS/device details if echo remains.

## Local automated tests

From the repository root, with the development environment installed:

```bash
.venv/bin/pytest -q tests/test_meeting_interventions.py tests/test_meeting_agent.py tests/test_meeting_findings.py
node --test tests/test_meeting_interventions.mjs tests/test_meeting_findings.mjs
```

These use isolated temporary databases and simulated model/connector/audio responses.
They verify private suggestions, owner authorization, exact approved wording,
revision conflicts, stale evidence, cancellation, restart recovery, source deletion,
delivery state, escaping, review history and approved record categories.

For the complete regression suite:

```bash
.venv/bin/pytest -q
node --test tests/*.mjs
```

To evaluate semantic behavior with the configured live model:

```bash
.venv/bin/python scripts/evaluate_interventions.py
```

This reads LLM configuration from `.env`, sends only synthetic English/Mandarin
dialogue, uses provider credits and does not modify the database. It checks missing
responsibility, genuine conflict, already-resolved questions, explicit decision
changes, optional details, different scopes, prompt injection, semantic duplicates
and pre-speech relevance. A finite evaluation does not establish universal accuracy.

## Local manual acceptance

1. Start Echooo with the existing live provider configuration:

   ```bash
   ./start.sh --port 8000
   ```

   Configure AssemblyAI STT, the live LLM and server TTS as described in `.env.example`.
   Do not use `--mock` for this acceptance scenario. The new tables are added on startup.

2. For online audible participation, start the existing Attendee setup as described in
   [ATTENDEE.md](ATTENDEE.md). Invite Echooo into a test meeting, wait for audio to
   connect, and keep **Answer when called** enabled. No adapter rebuild is required
   solely for this change if the current streaming-audio adapter is already installed.

3. Speak a short conversation establishing an important unresolved issue. For example,
   agree that a checklist is necessary before release, leave responsibility explicitly
   unassigned, then move to another topic. Wait for the background check, or choose
   **Check again** under **Suggested questions**. Ordinary gaps need not produce a
   proposal: the model must judge that clarification materially affects the outcome.

4. Inspect **Supporting conversation** and **Open transcript**. Verify Echooo has
   stayed silent. Choose **More → Save for later**, reload, and verify it remains saved.

5. Choose **Edit**, edit the wording, then **Ask in meeting**. Verify the spoken
   question matches that wording and **Review history** preserves the original. The
   completed question should appear under Echooo AI in the transcript.

6. On another proposal, answer the question naturally before approving it. Approval
   should be refused as obsolete, or the background check should already have marked
   it **No longer current**. Also test correcting its supporting transcript.

7. Approve another question and immediately use **Stop speaking** or **Stop**.
   Check that it does not continue or replay after refresh/restart. A failed provider
   should show **Failed**, with manual review needed before a retry.

8. Discuss a genuine contradiction with evidence on both sides and an explicit risk.
   Review those findings in **Review**. Verify only approved entries appear under
   **Contradictions** / **Risks** in the confirmed record. Approving a suggested
   spoken question alone must not add a confirmed finding.

For a local-only acceptance, use **Record audio → Microphone only → Start recording**
without inviting Echooo. Follow steps 3–5, choosing **Play locally**. Check
that the device speaks the approved wording, input resumes afterwards, cancellation
works and the question is not extracted as a human finding. Browser/OS audio must be
available. Automated tests simulate browser speech callbacks; real audible playback
must also be checked on the target device.

The online end-to-end audible acceptance requires the real meeting, STT and TTS
providers. Unit/browser checks and synthetic model evaluations are recorded separately.

## API

- `GET /api/meetings/{id}/interventions`: proposals, reviews and processing status.
- `POST /api/meetings/{id}/interventions/check`: enqueue a check; returns 202.
- `GET /api/meetings/{id}/interventions/checks`: latest 50 diagnostic checks.
- `POST /api/meetings/{id}/interventions/{proposal_id}/review`:
  `{ "action": "approve|defer|reject|cancel", "revision": 1, "question": "optional approved wording" }`.
  Only `approve` accepts changed wording. Stale revisions return 409.
- Browser approval adds `delivery: "browser"` and the current `recording_id`; its
  response includes a one-time `browser_speech` receipt. Only the approving client
  retains that receipt. `POST .../interventions/{proposal_id}/browser-speech` accepts
  its `revision`, `token` and action (`start`, `heartbeat`, `spoken`, `failed`,
  `cancelled`). Start rechecks relevance; subsequent callbacks validate the current
  approval, recording, evidence context and lease. Duplicate starts are rejected.
- Meeting detail/export and workspace export include intervention records and reviews.
- Source recording deletion removes linked proposals, review snapshots and their speech
  events. Meeting deletion cascades through the new tables.
