# Hackathon Technical Proposal

**Authors:** Zilong (technical), Fahmi Al Mughairy (product)  
**Date:** 14 September 2026 · **Branch:** `hackathon/assemblyai-2026`  
**Status:** Proposed for agreement; implementation and live validation pending.  
**Scope:** [Build brief](HACKATHON_BUILD_BRIEF.md), with Milestone 1 first.

## 1. Approach and reuse

Build on the existing FastAPI application, browser frontend, and database. Use browser microphone or tab + microphone capture for Milestone 1.

- **Reuse:** audio capture, AssemblyAI streaming, transcript storage/playback, authentication, and the LLM interface.
- **Extend:** structured extraction and the meeting UI to support live provisional findings and individual review.
- **Add:** persistent findings, evidence snapshots, review history, and approved-only record generation.

## 2. Real-time flow

**Browser audio → AssemblyAI → timestamped, speaker-labelled transcript → structured findings → host review → approved meeting record.**

Display partial transcripts immediately, but extract decisions, action items, and unresolved questions only from saved final transcripts in short batches. Validate evidence and deduplicate candidates before displaying them as provisional. Finish pending extraction at meeting end, then generate the record.

## 3. Storage and review rules

Reuse transcript storage and add findings with stable IDs, review status, evidence references, and review history. Each finding can reference multiple passages; preserve quoted text, speaker labels, and timestamps as evidence snapshots.

All findings start as `provisional`. The host can approve, edit-and-approve, or reject; only explicitly approved items enter the final record. Preserve original extractions and edits.

## 4. Controlled participation — Milestone 2

Privately show a proposed question and its evidence to the host; speak the approved wording only after approval, reusing existing TTS and stop/interruption controls. 
Before implementation, agree whether directly addressed questions require a separate approval click. Proactive interventions always require explicit approval.

## 5. Risks and reliable alternatives

| Requirement and risk | Recommended alternative |
| --- | --- |
| **Consistent live speaker separation:** the STT model's diarization accuracy alone is insufficient for reliable speaker attribution. The current input lacks separate participant audio streams and their identity mappings, making it difficult to determine accurately who said what from mixed audio. | For bot-joined meetings, first validate Attendee's per-participant audio and UUID-to-display-name mapping on the deployed adapter; Echooo currently consumes mixed audio. If validated, transcribe participants separately and merge by timestamp. Use diarization with host corrections and Unknown labels for mixed audio or shared microphones. |
| **Detecting important contradictions or omissions and deciding when to intervene:** “important” is subjective, and apparent gaps or conflicts may be resolved by the next utterance. | Maintain structured task/decision state, use rules to flag missing owners or conflicting deadlines, and use the LLM to distinguish unresolved conflicts from explicit decision changes. Recheck after a few completed turns, suppress resolved or repeated suggestions, and privately show an evidence-backed question for the host to approve, defer, or dismiss. Recheck relevance before speaking. |


## 6. Milestone 1 implementation plan

### Confirmed product decisions

- Use AssemblyAI diarization. Separate participant audio does not block Milestone 1.
- Direct host questions need no extra approval; clarify or decline when evidence is insufficient. Proactive speech always requires private review and explicit approval.

### Implementation tasks

First complete **live transcript → one evidence-linked decision → host approval → final record**, then extend to all required finding types.

| ID | Task and completion check |
| --- | --- |
| M1-1 | Verify two-speaker live transcription, timestamps, Unknown labels, and host name corrections. |
| M1-2 | Add persistent findings, evidence snapshots, and review history; verify data survives reload. |
| M1-3 | Extract one decision from final transcripts, display its evidence, approve it, and generate an approved-only record. |
| M1-4 | Add action items and unresolved questions, short-batch extraction, deduplication, and end-of-meeting processing. |
| M1-5 | Add evidence navigation, edit-and-approve, and reject. Preserve original evidence and exclude unapproved items. |
| M1-6 | Add retries and error states; prevent duplicate findings and overwritten reviews; flag corrected evidence for re-review. |
| M1-7 | Run local tests, and complete the live two-person acceptance demo. |

### Deployment approach

Start and test the existing application locally. Validate live capture, the full review flow, and data persistence. Cloud deployment can be considered after the local flow is reliable; it is not required for Milestone 1. Attendee is also not required.

### Technical risks and mitigations

- **Speaker errors:** leave uncertain owners unspecified.
- **Extraction errors or latency:** batch final transcripts, validate evidence, retry failures, and show processing status.
- **Duplicates or stale evidence:** preserve review history and snapshots, deduplicate retries, and require re-review after relevant corrections.
