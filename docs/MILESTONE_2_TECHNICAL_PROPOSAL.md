# Milestone 2 Implementation Plan

**Scope:** [Milestone 2 Build Brief](https://github.com/jastfkjg/Echooo/blob/hackathon/assemblyai-2026/docs/MILESTONE_2_BUILD_BRIEF.md)

### Confirmed product decisions

- Directly addressed questions need no extra host approval. Answer briefly using meeting evidence and available approved context; state when information is unsupported.
- Proactive clarifications require private host review. The host can approve, edit, or dismiss; only the exact approved wording may be spoken.
- Use one consistent voice and matching displayed text. Resulting findings still require separate human review; summaries include only confirmed results.

### Architecture and end-to-end flow

**Meeting audio → AssemblyAI transcription → direct-address / gap detection → evidence retrieval → LLM answer / suggestion → host approval for proactive speech → TTS → Attendee playback.**

Retrieve current-meeting evidence and available approved context. Persist trigger reasons, source passages, speakers, timestamps, exact responses, reviews, and delivery status; link participant answers to provisional findings. Keep Echooo speech separate from human evidence.

### Direct-address detection and latency

Detect explicit questions to Echooo after STT commits the completed turn, rather than from partial text; ignore mentions, quotations, and duplicate turns. 

Aim to start speaking within 3–6 seconds after the question ends, subject to service latency and no one else speaking. 

Stay silent when addressing is uncertain and cancel stale responses.

### Private host-review flow

Only show in the authenticated host dashboard.

1. Echooo privately shows the host a suggested question, its reason, and supporting transcript evidence.
2. The host reviews it and chooses Ask in meeting, Edit, or Dismiss.
3. After approval, Echooo speaks the exact approved text. Dismissed suggestions are never spoken.
4. Save the original suggestion, edits, approval/dismissal, and delivery status.

### Failure and fallback behavior

- **Transcription:** pause voice responses if transcription fails, show an error, and attempt to reconnect.
- **Retrieval:** state when evidence is absent; report retrieval errors separately and block unsupported output.
- **LLM:** reject timeouts, invalid responses; show a retryable error.
- **TTS:** retain text and mark failed/incomplete speech; require explicit retry.
- **Attendee:** cancel on disconnection or uncertain delivery.

### Preventing self-triggered commands

For Attendee meetings, exclude Echooo’s own audio where supported; otherwise evaluate echo cancellation using the TTS playback signal. 

For browser recording, apply microphone echo cancellation and keep local playback separate from captured tab audio. 

Preserve participant speech and voice interruption during playback.

### Implementation tasks and stage demonstrations

Reuse the existing transcription, meeting agent, TTS, evidence storage, and Milestone 1 review flow.

| ID | Task and completion check |
| --- | --- |
| M2-1 | Complete direct-address detection on final transcripts. |
| M2-2 | Retrieve relevant current-meeting passages and approved context. Return brief answers with source links, or explicitly record insufficient evidence. |
| M2-3 | Detect material unresolved gaps and contradictions from context. Show a private suggested question, reason, and evidence; suppress repeated or already-resolved issues. |
| M2-4 | Complete approve, edit-and-approve, and dismiss. Persist review history and recheck relevance before speaking; changed evidence invalidates pending approval. |
| M2-5 | Deliver exact approved text through TTS and Attendee. Wait for a pause, support stop/interruption. |
| M2-6 | Persist trigger reasons, passages, speaker labels, timestamps, and exact responses. |
| M2-7 | Run regression tests and all three deployed acceptance scenarios: Telegram answer, approved owner/deadline clarification with a resulting action item, and unsupported budget answer. |

1. **M2-1–2:** demonstrate answering with evidence and stating when information is unavailable.
2. **M2-3–4:** demonstrate private suggestions, approve/edit/dismiss, and stale-approval rejection.
3. **M2-5–6:** demonstrate approved speech, stop/echo protection, linked participant answers and reload persistence.
4. **M2-7:** run regressions and deployed acceptance.

### APIs, infrastructure, credentials, and costs

- **APIs:** provide host-only APIs to list, generate, and review suggestions; include evidence, speech status, and linked participant answers in meeting details.
- **Infrastructure:** reuse FastAPI, the database, and and Attendee deployment; add storage fields as needed. No new service is proposed.
- **Credentials/costs:** server-side AssemblyAI, LLM, TTS, and Attendee configuration. Costs cover transcription, model calls, speech generation, and hosting.

### Testing and acceptance

- Automated tests: cover direct questions, evidence handling, host approval/edit/dismiss, persistence, failures, and echo protection.
- Deployed validation: demonstrate the sourced Telegram answer, host-approved clarification with a resulting action item, and an unsupported budget response.
- Persistence: verify records and evidence survive refresh/restart, speech is not replayed, and summaries include only confirmed results.
