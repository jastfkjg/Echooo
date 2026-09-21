# Hackathon implementation log

## 21 September 2026 — Readable intervention evidence

- Kept the intervention reason visible below the question and promoted its type
  into a bordered, theme-aware badge. Only supporting transcript/history is folded.
- Grouped adjacent same-speaker source excerpts chronologically, retaining one
  attribution, time range and source control per group. Unverified transitions use
  ellipses; intervening speech, recordings and long gaps remain separate. No source
  text is rewritten and all original evidence IDs remain available for navigation.
- Validation: all 106 frontend tests passed, including ordering, grouping boundaries,
  omissions, Chinese spacing, escaping and evidence immutability. Isolated browser
  inspection verified visible reasons, consolidated excerpts and multi-ID navigation.

## 21 September 2026 — Focused suggestion controls

- Replaced mandatory speech-review dialogs with explicit delivery-specific primary
  actions and inline editing. Kept server approval, exact-wording audit and relevance
  checks unchanged; drafts survive live refreshes at the same proposal revision.
- Folded rationale, evidence and review history under Why this question; moved
  Save for later into More and a separate collapsed saved section. Unified secondary
  controls and retained Stop during speech checks.
- Validation: 103 frontend tests and 34 related backend tests passed. Isolated
  browser checks covered direct edited approval, duplicate-submit prevention,
  refresh/focus preservation, saved grouping and 375px layout without overflow.
  Browser checks use mock API responses, not a real meeting or audible playback.

## 21 September 2026 — Stable and timely suggested questions

- Added chronological, versioned speech-unit assembly and exact cross-fragment
  evidence mapping; incomplete recording fragments never enter the detector.
- Replaced six-second batching with 1.2-second settling and incremental checks.
  Uncertain results receive at most one two-second delayed recheck within the
  original 15-second budget; append-only updates get bounded relevance validation.
- Added owner-scoped diagnostic check history and compact processing/empty states.
  Semantic criteria distinguish implicit changes from explicit supersession and
  compare commitments only within the same activity and scope.
- Validation: 325 backend tests passed (1 skipped), 102 frontend tests passed;
  11/11 synthetic live-model scenarios passed, including implicit schedule changes
  and incompatible commitments in a single speech unit. Added 8 automated cases
  for ordering, evidence mapping, incomplete input, incremental checks, bounded
  follow-up and append-only relevance. Physical microphone/end-to-end latency
  still requires local acceptance; punctuation-based completeness is heuristic.

## 21 September 2026 — Milestone 2, governed participation

- Added private, evidence-backed intervention proposals with persistent owner review
  history, editable speech approval, defer, dismiss and cancellation.
- Added semantic detection for material contradictions and missing details, duplicate
  suppression, automatic resolution checks and pre-approval/pre-speech revalidation.
- Reused the Attendee voice queue and interruption controls to speak the exact approved
  wording. Failed, cancelled or restarted deliveries never replay automatically.
- Added Suggested questions to the meeting dashboard, source navigation, review history
  and explicit failure/recovery states, following the existing compact UI patterns.
- Extended reviewed findings and confirmed records with contradictions and risks.
- Added isolated governance tests and a repeatable live-model semantic evaluation.
  See [Milestone 2](MILESTONE_2.md) for local commands and real-meeting acceptance.
- Validation: 306 backend tests passed (1 skipped), 95 frontend tests passed,
  and all 9 synthetic scenarios passed with the configured live LLM. Browser checks
  covered editable approval, missing-connector error recovery, deferred-state reload,
  evidence navigation and 390px layout without horizontal overflow. Real two-person
  audible intervention acceptance remains a separate manual check.

## 15 September 2026 — Milestone 1, batches 1–3

Pre-existing baseline: Attendee/browser capture, AssemblyAI streaming, transcript storage and playback, generated minutes, and workspace authentication.

Added a decision-only review path:

- Both capture paths notify one background extraction service after transcript persistence; partial transcripts do not trigger extraction.
- New owner-scoped tables store decisions, multiple evidence snapshots, review history, and extraction progress. Existing databases acquire these tables at startup.
- Authenticated APIs support listing, approve/edit-and-approve/reject, manual extraction retry, and an approved-only record. Meeting/workspace exports include the new data; deleting source recordings removes related findings and review snapshots.
- The meeting page shows provisional decisions, evidence, approval controls, and an approved record. A live LLM is required; mock mode does not pretend to extract decisions.
- Existing generated minutes remain separate. No new voice participation or proactive intervention behavior was added.

## 15 September 2026 — Remaining Milestone 1 implementation

- Added action items with optional owner/deadline and unresolved questions. Ambiguous dates remain text; unsupported owners and normalized dates stay empty.
- Added edit-and-approve/reject controls, review history, and an explicit re-review dialog showing original/current evidence. Confirmation uses an evidence token so newer corrections cannot be approved from an outdated dialog.
- Later changes and answered questions reconcile with existing findings. Approved content is preserved until a host approves its replacement; approved resolution removes a question from the unresolved section. Revision chains and original signatures prevent repeat input from restoring replaced items.
- Added bounded retries, startup recovery, and a final extraction flush. Final record generation checks that capture has stopped and saved-audio transcription is ready, without waiting for unrelated generated notes.
- Added an additive metadata migration. Existing review data is preserved, and the old decision-only processing checkpoint is reset once so action items/questions can be extracted from saved text.
- Validated automated tests, real configured-LLM extraction with synthetic three-type dialogue, and local browser edit/reject/record flows. Live two-person AssemblyAI/Attendee acceptance remains a separate verification step; no new voice intervention functionality was added.

## 16 September 2026 — Findings clarity

- Tightened reviewed rows and grouped final records with explicit meeting title, total and category counts. Edited approvals are labelled separately; final-record evidence is collapsible and navigable.
- Reused readable speaker names in evidence. Nearby fragments from the same raw speaker and recording share a presentation block, while exact quotes, individual transcript anchors and stored evidence remain intact.
- Strengthened extraction instructions against whole-turn summaries, ambiguous references and unsupported repairs of garbled transcription. Existing approved data is unchanged; live-model effectiveness of the revised prompt remains to be evaluated.
- Validation: 78 frontend tests and 20 findings backend tests passed. Desktop and 390px browser fixtures checked, including source callbacks and no horizontal overflow.

## 16 September 2026 — Dedicated Review tab

- Ordered meeting content as Transcript, Review, Summary & notes. Review displays a live pending count, including approvals needing re-review; completed findings remain folded.
- Moved approved records into Summary & notes above explicitly unreviewed AI notes. Successful record generation navigates there; existing approved items remain available after reload.
- Added a return-to-review action after source navigation, retaining review scroll and expanded evidence. Three-tab keyboard navigation supports arrows, Home and End.
- Validated the complete meeting UI with simulated data in a browser: source round trip, retained evidence, approval count update, generation navigation, keyboard navigation, and 390px layout without horizontal overflow. Frontend tests: 79 passed.
