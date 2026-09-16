# Hackathon implementation log

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
