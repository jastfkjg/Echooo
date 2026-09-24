# M2 direct answers: recent context and historical search

## Behavior

The live model first receives the question, recent saved passages, up to four recent
exchanges, and authorized project knowledge. It returns `answer`, `search`, or
`clarify`. Supported factual answers require source IDs; a clarification asks about
an ambiguous request without searching. An initial `insufficient` verdict also
triggers one historical check before it can be delivered.

A search uses 1–4 model-generated query variants, scoped by the server to the owner
and current meeting. The server retrieves original passages and adjacent context,
then makes one final model call. A second search request is rejected. The model must
distinguish supported facts, insufficient evidence, unresolved conflicts, and general
conversation; valid citations alone do not prove semantic correctness.

## Retrieval and limits

- Original transcripts stay in the existing database. Search builds a disposable
  lexical inverted index in a worker thread, using English/Unicode words and CJK
  bigrams with BM25 ranking. No embedding credentials or vector service are required.
- Search covers the saved meeting history, including text outside the recent window
  and beyond the beginning of long passages. Candidates include strong matches,
  later matches, and neighboring context. Adjacent same-speaker ASR fragments are
  joined before ranking, bounded by a 2-second gap, 30-second span and 1,500 characters.
  Each hit includes neighboring turns within 10 seconds in the same recording.
  Windows are ranked by relevance, with two candidate slots reserved for later matches;
  turns within each window retain recording/audio order. Long turns use overlapping excerpts.
- Recent discussion: at most 6 turns and 3,000 text characters, assembled from the
  latest 60 ASR rows. Search results: up to 8 evidence windows and 18,000 text characters. The serialized model context, including metadata, is capped
  at 40,000 characters; lower-priority history/knowledge is dropped first; evidence windows are removed whole. This is a
  character budget, not a provider-specific token guarantee.
- At most two model calls; generation plus search has a 12-second deadline, with a
  2-second search deadline. TTS and waiting for the floor are separate. Stop cancels
  the pending work; the retrieval worker cooperatively stops on cancellation.
- There is no persistent secondary index to become stale. Each search reads current
  rows. Evidence changes or new saved discussion during generation invalidate the
  answer; the discussion is checked again before voice playback.

Lexical retrieval can miss paraphrases even with query variants. “Insufficient” means
no supporting answer was found in the available evidence, not proof that the meeting
never discussed the subject. Independent semantic evaluation remains necessary.

## Model input boundaries

Initial and final synthesis calls use separate prompts. The final prompt contains no
search action schema or query rules. `action=answer` returns a final response;
`supported`, `insufficient`, `conflicting`, and `not_applicable` describe its support.
The model must inspect discussion, knowledge, and retrieved evidence, answer at the
precision actually stated, and distinguish missing evidence from an ambiguous question.
Explicit corrections may resolve a conflict; a later timestamp alone cannot.

The model receives an allowlisted payload. Transcript blocks carry a recording ID
once, with turns containing readable text, speaker/timing, and original `source_ids`.
Knowledge carries only ID, title, and content. Hashes, raw offsets, ranking scores,
counts, memory versions, project settings, and the search-enabled flag remain on the
server. Empty knowledge and conversation-history arrays are omitted. Truncation flags
are emitted only when true. Budgeting measures the actual serialized model payload.

`recent_questions` provides conversational background, never factual evidence. Assistant
speech/events are stored separately from human utterances and excluded from retrieval.
Previously captured assistant audio already saved as human ASR is not retrospectively
reclassified by this change. Source hashes and authorization checks still protect
original citations before delivery. Saved traces record the exact compact input, while
search diagnostics retain original rows for inspection.

## Feedback and persistence

The host sees **Checking earlier discussion…** during historical retrieval and final
answer generation. Insufficient and conflicting evidence have distinct messages;
provider/search failures remain errors and are never reported as absent evidence.

An additive `meeting_answer_checks` table records action, support state, search usage,
model-call count, candidate counts, and elapsed/search time, without model reasoning
or duplicate transcript text. It is available in activity, meeting detail/export,
and workspace export. Source references include a versioned hash. Restart cancels
pending searches without replay; deleting a meeting removes its check records.

## Automated verification

```bash
.venv/bin/pytest -q tests/test_meeting_answers.py tests/test_meeting_agent.py tests/test_meeting_turns.py tests/test_meeting_knowledge.py
node --test tests/*.mjs
```

Coverage includes recent answers without search, old evidence beyond 60 passages,
Chinese queries, long-passage tails, later revisions, cross-owner/meeting isolation,
invalid citations, unsupported states, search limits, timeout/stop, transcript changes,
restart, export, and deletion. Provider responses are simulated in these tests.

For the configured live model, using only synthetic data in a temporary database:

```bash
.venv/bin/python scripts/evaluate_meeting_answers.py
```

This uses provider credits and does not read or modify application meetings. Review
printed answers as well as the structured assertions. It covers recent/old decisions,
missing budget, proposal versus approval, revised decisions, ambiguous questions,
untrusted instructions, and Mandarin evidence.

Local measurements during development: a 3,000-passage synthetic search took
95–100 ms across three runs. One live-model evaluation passed 8/8 cases, taking
1.78–2.45 seconds for recent-answer/clarification paths and 3.48–4.86 seconds for
search paths. These exclude STT/TTS and are not deployed latency guarantees.

## Manual deployed test flow

For online meetings, use a live LLM, AssemblyAI, server TTS, and Attendee with
**Answer when called** enabled. For local Recording, use a live LLM and AssemblyAI;
server TTS generates the audio and the recording browser plays it, without Attendee credentials.

1. State a team communication decision, then ask Echooo which platform was selected.
   Expect a brief spoken answer and a source link without host approval.
2. Repeat after enough unrelated discussion to move the decision outside recent
   context (more than 60 saved passages). Expect historical search and the original
   decision as evidence. Also test a later change to the decision.
3. Ask for an approved budget when none exists. Expect an uncertainty response, an
   `insufficient` check, and no invented amount. A proposed-but-unapproved budget
   must not become an approved one.
4. Ask an ambiguous question. Expect a short clarification. Interrupt a pending
   search with Stop; no delayed answer should be played.
5. Refresh/reopen the meeting and inspect activity, sources, and exported
   `answer_checks`. Responses and support states should remain without replay.
6. Disconnect the model/connector and retry. Expect a failure state, not a false
   “no evidence” result. Record end-of-question and first-audio time separately from
   the stored generation timing.

Real meeting audio, echo behavior, and deployed acceptance require this manual run;
synthetic model evaluation does not certify them.

## Browser Recording

- Each recording socket owns an independent direct-answer session. Only newly saved
  final transcripts with an opening address such as “Hello, Echooo” start a
  conversation through the shared recent-context/search/answer pipeline. A 15-second
  follow-up window uses the same semantic respond/listen/end classifier as Attendee;
  acknowledgements and unrelated discussion do not automatically trigger replies.
  Partial transcripts never initiate answers. Turn deduplication and speaker revisions cannot replay earlier questions.
- **Answer when called** defaults on; **Stop speaking** cancels generation or speech.
  The page shows progress and reply text, including when browser sound is blocked.
  Completed replies appear as separate Echooo transcript entries. Open a reply to see
  its sources, speaker, timestamps and original passage. Activity/export retain
  failed/interrupted replies, citations and support checks as well.
- A one-use token is delivered only to the recording socket. Playback requires a
  fresh start acknowledgement, checks evidence/knowledge again, and reports completion
  only after the browser's first-output and drained-stream reports. Heartbeats renew an 8-second server
  lease; start waits at most 5 seconds in the browser and total speech at most 120
  seconds on the server. Disconnect, stop or navigation cancels; history never plays.
- Capture and human transcripts continue during speech. Microphone AEC is requested,
  preferring `all` when supported; the browser reports its effective setting for
  diagnostics. Shared tab audio is not filtered. AEC is not proof of speaker identity.
- Direct replies reuse Attendee's text echo filter, conversational turn classifier
  and tentative-interruption controller. Audio timestamps exclude pre-playback speech;
  untimed partials cannot interrupt. Matching output inside recorded playback windows
  remains filtered even when STT arrives late. This filters control decisions only,
  never deletes human words or PCM. Text matching remains heuristic, especially when
  humans repeat the assistant or echo is mistranscribed.
- New partial speech pauses playback for 550 ms; continued development across at
  least 300 ms with sufficient text stops it, otherwise the same utterance resumes.
  Final speech follows the existing meeting interruption/turn rules. Browser pause
  and resume are receipt-scoped and heartbeats reconcile playback state. Manual Stop,
  disabling replies and disconnect cancel pending follow-up decisions and end the
  conversation. Approved local suggestions retain their separate host-review flow
  and command guard; they do not acquire the direct-answer follow-up window.
- Both transports use the owner’s server TTS selection. Local replies and approved
  local suggestions now make TTS API calls; browser speech synthesis is not a fallback.
  Eligible follow-ups add one fast
  turn-classification model call before answering. Demo STT does not transcribe.

Run `.venv/bin/pytest -q tests/test_browser_answers.py` and
`node --test tests/test_browser_answer_speech.mjs tests/test_local_question_speech.mjs`.
These cover the live capture socket with simulated STT, historical retrieval,
one-shot receipts, stale evidence, interruption, delayed echo, disconnect, expiry,
browser errors, persistence and byte-for-byte PCM preservation.

Local manual check: start Recording with **Microphone only**, say “Echooo, what did
we decide?”, and wait for the final transcript. Check progress, text and spoken reply.
Let a reply play through on speakers without speaking; verify echo does not stop
it or create another answer. Then interrupt with a sustained new request; playback
should stop and the final request should be considered as a follow-up. Test a brief
false start (pause/resume), an unaddressed follow-up within 15 seconds, unrelated
human discussion, and a question after the window expires. Verify that manual
**Stop speaking** cancels playback and follow-up decisions. Repeat using speakers, headphones and Tab + microphone,
then refresh during playback and confirm there is no replay. Also test sound blocked,
network loss and Stop while searching. Real acoustic/autoplay behavior requires this
device/browser check; automated tests use simulated server TTS, browser audio playback, and STT.

### Answer diagnostics

New direct answers persist an owner-scoped `meeting_answer_traces` record linked by
`event_id`, shared by browser and meeting modes. Restart the backend to create the
new table. Existing answers cannot be reconstructed retroactively.

The meeting JSON export includes `answer_traces`; live polling omits these larger
records. Each trace contains:

- `search.queries`, its model/fallback trigger, and the full bounded retrieval result.
- `calls[].context`: the final context after budget trimming for each model call.
- `calls[].request`: the actual model request payload, including system/user messages
  and model settings, without authorization headers or API credentials.
- `calls[].response`: raw model content and finish reason before JSON parsing;
  content over 24,000 characters is explicitly marked truncated.
- Parsed `result`, validation status and failure stage/type, including cancellation.

For a missing answer, compare the returned passage text with the second call's
context/request and then its response. A retrieved passage alone does not prove it
reached the model. An incomplete trace identifies where execution stopped.
These records contain meeting and authorized knowledge text: they share meeting
owner access, are included in explicit exports, and cascade-delete with their
answer event or meeting. They are not printed to server logs.

### Debug page

Open **Debug** beside **Project & knowledge**, or `#meetings/<id>/debug`.
Select a recording and question to inspect the original answer, validation,
retrieval scores, model calls and a retrieved-versus-sent evidence comparison.
Refresh manually; export a single answer as JSON when reporting an issue.
The index lists the latest 100 answer events; older durable traces remain in the
meeting export. Owner authentication and meeting scope apply to both endpoints.

Live STT, transcript, turn decisions and delivery/playback diagnostics use a bounded
in-memory ring (500 events per meeting, 32 recently active meetings per process).
They reset on restart/eviction and are cleared on meeting or recording deletion.
They are nearby activity, not a guaranteed causal association with a question.
Browser STT includes connection number, audio anchors and lag behind the saved-audio
cursor where timed words exist; this is not a network latency measurement.
Partial hypotheses are not durable and the page does not record raw audio or secrets.
Follow-up classification input/output is included when it occurs; this is not a
trace of every background LLM operation (such as findings or summaries).

Answer inputs omit absent project configuration and knowledge-status UI strings.
An empty knowledge list has no bearing on meeting evidence. Server-side knowledge
scope, citation checks and authorization remain authoritative.

### Input simplification verification (2026-09-23)

- Python suite: 398 passed, 1 skipped. JavaScript suite: 128 passed.
- Configured live model (`deepseek-v4-pro`): 13/13 synthetic checks passed after
  clarifying the general distinction between missing evidence and ambiguous intent,
  and between explicit replacement and unresolved conflict. Cases include month-only
  and seasonal dates, Mandarin evidence, missing facts, proposals, corrections,
  conflicts, general advice, and injected source instructions.
- Replayed the supplied incident's final stage using its original retrieved evidence,
  six recent turns, the compact payload, and the final-stage prompt. The model returned
  `answer / supported`, “The project started in January.”, citing original source
  `69719218e358ff34b71791529440e0a2`. Serialized user input decreased from 26,495 to
  4,806 characters (about 82%). This replay checks synthesis over the supplied evidence;
  the full original meeting database was not available for replaying historical search.
- The live evaluation checks action, support, and required citations; replies were also
  inspected manually. These finite checks do not guarantee semantic recall or eliminate
  future model errors. No running deployment or historical transcript data was changed.


## Shared assistant voice

Settings → Assistant voice selects a server speech service and voice for both local
recording and online meeting assistants. Preview uses the current unsaved selection;
Save persists an owner-scoped preference in `assistant_voice_settings` (added on startup,
with the same PostgreSQL RLS rules as other owned tables). Each reply snapshots the
selection when speech generation starts. An active audio reply does not change voice.
The meeting page opens Voice settings in a separate tab so recording can continue.

By default the configured server `TTS_PROVIDER` is offered. To expose multiple configured
services, set `ASSISTANT_TTS_PROVIDERS=dashscope,cosyvoice` on the server. DashScope requires
its API key and exposes preset voices plus ready custom voices when voice management is
available. Self-hosted CosyVoice exposes `COSYVOICE_SPEAKER_ID` as its configured preset.
Endpoints and credentials remain server-managed, never user-supplied URLs or keys.
`TTS_PROVIDER=browser` alone does not enable meeting speech; configure a server service.
Ordinary conversation-specific voice controls are unchanged.

Browser direct answers stream server-generated PCM after a one-shot playback authorization.
The complete answer and citations are validated before synthesis; playback no longer
waits for the complete WAV. A 200 ms AudioWorklet prebuffer absorbs ordinary jitter,
with roughly one second of unplayed audio allowed in flight and a four-second hard
worklet buffer limit. Short replies drain on the end marker. PCM continues across
packet boundaries; pause retains queued samples and Stop discards the stream.
Approved local suggestions retain their existing bounded WAV transport.

Each offer/PCM/end packet belongs to the active capture socket and receipt. The
server rechecks evidence before authorization and knowledge during delivery. Audio,
receipts and tokens never enter history. First output is reported separately from
start authorization; completion requires the synthesis end marker, first-output
report and all sent samples consumed. Heartbeats report sample progress and renew
the eight-second lease. Synthesis has a 30-second idle timeout and the whole stream
is bounded to 120 seconds. Failure/Stop/disconnect cancels the producer and playback,
retains the text, and never retries or switches voices automatically.

### Answer timing and evidence (2026-09-24)

Open a completed Echooo transcript entry or **View answer & sources** in the latest
reply / Messages & activity. The owner-only `GET /api/meetings/{mid}/answers/{eid}`
loads any saved answer by ID, independently of the latest-20 activity window.
The first cited passage is visible immediately; additional citations expand under
**More sources**. Sources show speaker, recording-relative start/end timestamps,
**View transcript**, **Play original** (after capture ends), and **Copy source link**.
Source links use `#meetings/<mid>/answers/<eid>/sources/<sid>`; transcript links use
`#meetings/<mid>/passages/<sid>`. Refresh restores the selected evidence/recording.
Changed sources show **Source changed** with an explicitly labeled current-transcript
link; deleted sources remain **Source unavailable** placeholders. Original text is
not reconstructed when no original snapshot exists. Insufficient/uncited replies do
not acquire invented sources. The meeting export's `answers` includes all saved
answer events and resolved citations, not only the recent activity list.

New answer traces include a `timing` object, visible in **Debug → Answer timing**
and in answer/meeting/workspace JSON exports. No database table migration is needed.
Server milestones cover STT final receipt, queue, context preparation, each LLM call,
retrieval, validation, floor waiting (Attendee), TTS request/first chunk/end,
playback authorization, first output report and completion/failure. Follow-up
classification is included in final-receipt-to-queue time. Server durations use
one process's monotonic clock; only relative milliseconds are persisted.

Question end is an STT word-end offset in the recording. A bounded in-memory audio
arrival ring records server receipt of the frame containing the last word; its
monotonic duration to STT final receipt includes STT queueing/provider/transport,
excludes capture uplink, and has the recorded frame duration as its resolution.
This survives silence without mistaking a stationary sample cursor for low latency.
STT audio backlog is
explicitly an **estimate**, not isolated provider/network latency. Browser capture
worklet anchors and playback worklet timestamps share the same AudioContext clock,
allowing question-end-to-first-output-frame measurement without subtracting host
clocks. Browser output-device latency is reported separately when available.
Attendee reports its own start-to-first-output-frame duration; server receipt of
that report includes transport/polling delay and is not participant audibility.
TTS stream duration includes playback backpressure, so overlapping stages must not
be added. Missing timestamps remain missing, including older records and untimed
STT events. Physical speaker/acoustic and meeting-platform delivery latency still
require a real recording-based acceptance run.

Validation covers partial delivery before synthesis finishes, bounded backpressure,
separate authorization/first-output events, stop/failure cancellation, stale evidence,
one-use tokens, interruption, historical source access, changed/deleted citations,
owner/meeting isolation, export, readable source rendering, and browser audio-clock
reports. Provider-backed 3–6 second acceptance must be measured in the deployment;
these tests do not assert a service latency guarantee.

Normal live transcription is represented in the header as `Recording · Transcribing`.
The separate transcription area is reserved for connecting, verification, and error states.

Verification: 404 Python tests passed (1 skipped), 128 JavaScript tests passed; a live
DashScope smoke test produced a valid WAV. Browser checks used an isolated test database
and synthetic audio for service selection, saving/reloading, preview, and narrow layouts.
Real meeting acoustics and online Attendee playback still require device integration checks.
