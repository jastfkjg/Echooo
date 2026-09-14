# AssemblyAI Voice Agent Hackathon — Build Brief

**Repository:** `jastfkjg/Echooo`  
**Working branch:** `hackathon/assemblyai-2026`  
**Team:** Fahmi Al Mughairy and Zilong  
**Status:** Approved to begin  
**Date:** 14 September 2026

## 1. Product Goal

Build a governed meeting voice agent that listens to a live conversation, understands what is happening, and produces an evidence-backed meeting record.

This is not only a transcription or note-taking tool. The prototype must identify:

- speakers;
- decisions;
- action items, owners, and deadlines;
- commitments;
- unresolved questions;
- important contradictions or missing information.

The host remains in control. The agent should speak only when:

1. it is directly addressed;
2. the host invites it to contribute; or
3. it detects a materially important issue and the host approves the proposed intervention.

For this prototype, an intervention must never be spoken automatically without host approval.

## 2. Target Use Case

A founder, project lead, or small team holds a working meeting. The agent follows the conversation in real time, captures the important outcomes, and presents them to the host for review before they become part of the official meeting record.

The value is not “we recorded the meeting.” The value is “we know what was decided, who owns the next action, what remains unresolved, and which evidence supports every item.”

## 3. Existing Echooo Baseline

Reuse existing Echooo components wherever they are reliable and relevant, including:

- meeting and audio capture;
- AssemblyAI streaming transcription;
- speaker diarization;
- transcript storage;
- structured extraction;
- meeting-attendee bot capability;
- voice-response and interruption handling;
- evidence-linked notes;
- project knowledge and reviewed memory.

The baseline tag created before hackathon development must remain unchanged. New hackathon work belongs on `hackathon/assemblyai-2026`.

## 4. First Acceptance Scenario

During a test meeting between two people:

1. The agent captures and transcribes the conversation live using AssemblyAI.
2. It separates the two speakers consistently.
3. The conversation contains:
   - one clear decision;
   - one action item with a named owner;
   - one unresolved question.
4. The system extracts all three items.
5. Each extracted item links to its supporting transcript segment and timestamp.
6. A host dashboard displays each item as provisional.
7. The host can approve, edit, or reject each item.
8. Rejected items do not enter the final record.
9. Edited items retain their link to the original transcript evidence.
10. The system generates a final meeting summary containing only host-approved items.

### Acceptance Result

The milestone passes only when the full journey works in one continuous demo:

**Live conversation → transcription → speaker separation → structured extraction → evidence link → human review → approved meeting record**

## 5. Functional Requirements

### Live Meeting Intelligence

- Stream live audio to AssemblyAI.
- Display partial and final transcripts.
- Preserve timestamps.
- Separate speakers.
- Allow the host to correct speaker names.

### Structured Extraction

Use predictable structured output for at least:

```json
{
  "type": "decision | action_item | unresolved_question | contradiction",
  "statement": "string",
  "speaker": "string",
  "owner": "string or null",
  "deadline": "ISO date/time or null",
  "confidence": "internal value",
  "evidence": {
    "transcript_segment_id": "string",
    "start_time": "number",
    "end_time": "number",
    "quote": "short supporting excerpt"
  },
  "review_status": "provisional | approved | edited | rejected"
}
```

Confidence may guide system behavior internally but should not be presented as a promise of correctness.

### Host Governance

- All extracted items begin as `provisional`.
- The host can approve, edit, or reject them.
- Only approved or host-edited items enter the final record.
- Preserve an audit trail of the original extraction and host action.
- Never invent a speaker, owner, deadline, decision, or supporting quote.

### Controlled Participation

- Silent by default.
- Respond when directly asked.
- If an important contradiction or missing decision detail is detected, show a proposed question privately to the host.
- Speak only after the host approves.
- Support interruption or cancellation by the host.

### Final Meeting Record

Produce:

- concise summary;
- approved decisions;
- approved action items with owners and deadlines;
- unresolved questions;
- approved risks or contradictions;
- transcript evidence references.

## 6. Prototype Interface

A functional interface is sufficient. It should include:

1. Meeting status and audio/transcription state.
2. Live transcript with speaker labels.
3. Provisional findings panel.
4. Approve, edit, and reject controls.
5. Proposed agent-intervention panel.
6. Final approved meeting record.
7. Clear error or disconnected states.

Polish comes after the end-to-end flow is reliable.

## 7. Out of Scope for the First Milestone

Do not delay the core demo for:

- enterprise multi-tenancy;
- billing;
- complex authentication;
- mobile applications;
- facial recognition;
- fully autonomous interventions;
- large-scale production infrastructure;
- deep integrations with multiple meeting platforms;
- long-term business analytics.

These may be considered only after the first acceptance scenario passes.

## 8. Responsibilities

### Zilong — Technical Ownership

- review the current Echooo architecture;
- propose the simplest end-to-end technical flow;
- own the backend and AssemblyAI integration;
- implement the agent and structured-extraction pipeline;
- implement persistence and evidence traceability;
- build the functional frontend;
- deploy the working prototype;
- own technical tests and reliability.

### Fahmi — Product Ownership

- define product behavior and boundaries;
- define host-control and agent-speaking rules;
- provide realistic meeting scenarios;
- review UX and extracted outputs;
- run acceptance testing;
- prepare the product story, demo narrative, pitch, and submission;
- approve scope changes and final product behavior.

Both team members may challenge decisions and contribute across areas, but every task should have one clear owner.

## 9. Immediate Technical Deliverable

Before expanding the scope, Zilong should add a short technical proposal covering:

1. What existing Echooo components can be reused unchanged.
2. What existing components require modification.
3. What new components must be built.
4. The proposed real-time data flow.
5. The storage model for transcript evidence and reviewed findings.
6. How host-approved interventions will work.
7. Deployment approach.
8. A task breakdown for the first acceptance scenario.
9. Technical risks and the fastest safe fallback for each.

Technical choices that do not change the agreed product behavior may be made by Zilong and documented in the repository. Product-scope or governance changes should be agreed together.

## 10. Working Rules

- Do not build new hackathon work directly on `main`.
- Keep the original baseline tag unchanged.
- Use small, reviewable commits.
- Never commit API keys, credentials, meeting recordings, or private participant data.
- Keep the repository private unless public access becomes necessary for submission.
- Both Fahmi and Zilong must be credited in the project and submission.
- The intended cash-prize split is 50/50 between the two team members. Non-cash credits or benefits will be allocated fairly according to organizer rules.
- Keep a short change log separating the pre-existing Echooo baseline from joint hackathon work.

## 11. Delivery Sequence

### Milestone 1 — Reliable Core

Pass the first acceptance scenario end to end.

### Milestone 2 — Governed Participation

Add host-approved intervention and controlled voice response.

### Milestone 3 — Demo Readiness

Improve reliability, error handling, interface clarity, deployment, and the scripted demonstration.

### Milestone 4 — Submission

Complete the demo video, pitch deck, project description, architecture summary, credits, and required submission materials.

## 12. Definition of Done

The prototype is ready for submission when a judge can see, without explanation:

1. a live conversation being transcribed;
2. the speakers being separated;
3. decisions, actions, and unresolved questions being extracted;
4. evidence supporting each item;
5. a human approving, editing, or rejecting the agent’s work;
6. the approved final record;
7. AssemblyAI being essential to the product rather than a superficial integration.
