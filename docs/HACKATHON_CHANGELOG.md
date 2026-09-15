# Hackathon implementation log

## 15 September 2026 — Milestone 1, batches 1–3

Pre-existing baseline: Attendee/browser capture, AssemblyAI streaming, transcript storage and playback, generated minutes, and workspace authentication.

Added a decision-only review path:

- Both capture paths notify one background extraction service after transcript persistence; partial transcripts do not trigger extraction.
- New owner-scoped tables store decisions, multiple evidence snapshots, review history, and extraction progress. Existing databases acquire these tables at startup.
- Authenticated APIs support listing, approve/edit-and-approve/reject, manual extraction retry, and an approved-only record. Meeting/workspace exports include the new data; deleting source recordings removes related findings and review snapshots.
- The meeting page shows provisional decisions, evidence, approval controls, and an approved record. A live LLM is required; mock mode does not pretend to extract decisions.
- Existing generated minutes remain separate. No new voice participation or proactive intervention behavior was added.

Validation: backend lifecycle/permissions/evidence tests, frontend escaping/control tests, browser approval-to-record flow with synthetic data, and a live configured-LLM check using a synthetic proposal followed by an explicit decision. These do not constitute live two-person AssemblyAI/Attendee acceptance.

Remaining Milestone 1 work: action items and unresolved questions, edit/reject UI, complete re-review workflow for corrected evidence, stronger cross-batch reconciliation/recovery and end-of-meeting flush, then the continuous live acceptance demo. Currently stale evidence is visibly flagged and excluded from newly generated approved records; re-approval of a corrected finding is not yet implemented.

Contributors: Zilong (technical), Fahmi Al Mughairy (product).
