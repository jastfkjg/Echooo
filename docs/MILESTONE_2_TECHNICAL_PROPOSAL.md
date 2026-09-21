# Milestone 2 Implementation Plan

**Scope:** [Milestone 2 Build Brief](https://github.com/jastfkjg/Echooo/blob/hackathon/assemblyai-2026/docs/MILESTONE_2_BUILD_BRIEF.md) 

### Confirmed product decisions

- Directly addressed questions need no extra host approval. Answer briefly using meeting evidence and available approved context; state when information is unsupported.
- Proactive clarifications require private host review. The host can approve, edit, or dismiss; only the exact approved wording may be spoken.
- Use one consistent voice and matching displayed text. Resulting findings still require separate human review; summaries include only confirmed results.

### Implementation tasks

Reuse the existing transcription, meeting agent, TTS, evidence storage, and Milestone 1 review flow.

First complete **direct question → evidence-backed spoken answer → saved transcript**, then **private clarification → host approval → spoken question → participant answer → reviewed finding**.

| ID | Task and completion check |
| --- | --- |
| M2-1 | Complete direct-address detection on final transcripts. |
| M2-2 | Retrieve relevant current-meeting passages and approved context. Return brief answers with source links, or explicitly record insufficient evidence. |
| M2-3 | Detect material unresolved gaps and contradictions from context. Show a private suggested question, reason, and evidence; suppress repeated or already-resolved issues. |
| M2-4 | Complete approve, edit-and-approve, and dismiss. Persist review history and recheck relevance before speaking; changed evidence invalidates pending approval. |
| M2-5 | Deliver exact approved text through TTS and Attendee. Wait for a pause, support stop/interruption. |
| M2-6 | Persist trigger reasons, passages, speaker labels, timestamps, and exact responses. |
| M2-7 | Run regression tests and all three deployed acceptance scenarios: Telegram answer, approved owner/deadline clarification with a resulting action item, and unsupported budget answer. |
