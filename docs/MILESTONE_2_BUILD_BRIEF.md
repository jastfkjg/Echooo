# Echooo Milestone 2 Build Brief

## Controlled Voice Participation

### 1. Objective

Milestone 2 turns Echooo from a meeting observer into a controlled meeting participant.

Echooo may answer when directly addressed. It may also identify an important gap and prepare a clarification, but it must not speak proactively without host approval.

The goal is useful voice participation without allowing the agent to interrupt, invent information, or take control of the meeting.

---

### 2. Required Behaviour

#### A. Direct questions

When a participant directly addresses Echooo, for example:

> "Echooo, what communication platform did we choose?"

Echooo should:

1. Recognise that it has been directly addressed.
2. Use the current meeting transcript and available approved context.
3. Give a short, relevant spoken answer.
4. State clearly when the answer is unknown or unsupported.
5. Record its response in the transcript.

Directly addressed questions do not require separate host approval before Echooo answers.

#### B. Proactive clarification

Echooo should detect important gaps such as:

- An action item without an owner.
- An action item without a deadline.
- A decision that remains unclear.
- A question that has not been answered.
- Conflicting statements about an important decision or commitment.

When a gap is detected, Echooo should:

1. Prepare a short suggested clarification.
2. Show the suggestion privately to the host.
3. Explain what triggered the suggestion.
4. Allow the host to approve, edit, or dismiss it.
5. Speak only after the host approves it.

Example:

> "Who owns this action, and when is it due?"

Dismissed suggestions must not be spoken.

---

### 3. Evidence and Traceability

Every Echooo intervention must preserve:

- The reason it responded.
- The triggering transcript passage or passages.
- Speaker labels and timestamps.
- Whether it was directly addressed or host-approved.
- The exact response Echooo gave.
- Any answer received after Echooo asked a clarification.

The host must be able to open the supporting transcript evidence.

---

### 4. Human Control

The host remains in control.

Echooo must:

- Never interrupt ordinary conversation.
- Never speak proactively without host approval.
- Never present an unsupported assumption as fact.
- Allow the host to edit or dismiss a proposed intervention.
- Allow resulting decisions, actions, and questions to be approved, edited, or rejected through the existing review flow.

---

### 5. Voice Requirements

For the Milestone 2 prototype:

- Echooo should use one consistent voice.
- Responses should be brief and natural.
- Echooo should not give speeches or repeat the full meeting history.
- If evidence is insufficient, it should say so naturally.
- The spoken response and displayed text should match.

---

### 6. Acceptance Scenario A: Direct Question

During a recorded meeting:

1. Speaker A says:  
   "We have decided to use Telegram for team communication."

2. Later, Speaker B asks:  
   "Echooo, what communication platform did we choose?"

Expected result:

- Echooo answers that Telegram was selected.
- The answer is based on the earlier transcript.
- The response is spoken and added to the transcript.
- The source links to the original Telegram decision.
- No additional host approval is required because Echooo was directly addressed.

---

### 7. Acceptance Scenario B: Missing Owner and Deadline

During a recorded meeting:

1. Speaker A says:  
   "We need to prepare the final presentation."

2. Nobody assigns an owner or deadline.

Expected result:

- Echooo detects the missing owner and deadline.
- It prepares a clarification for the host.
- It does not speak automatically.
- The host can approve, edit, or dismiss the clarification.
- After approval, Echooo asks:  
  "Who will prepare the presentation, and when is it due?"
- The spoken question appears in the transcript.
- The participants' answer is captured and may create a provisional action item.
- The action item still goes through the existing human review flow.

---

### 8. Acceptance Scenario C: Insufficient Information

A participant asks:

> "Echooo, what budget did we approve?"

No approved budget appears in the meeting transcript or available approved context.

Expected result:

- Echooo does not invent a budget.
- It responds briefly that no approved budget was found.
- Its response appears in the transcript.
- The evidence state shows that no supported answer was available.

---

### 9. Persistence Requirements

After refreshing or reopening the meeting:

- Echooo's spoken interventions remain visible.
- Host approvals, edits, and dismissals remain saved.
- Evidence links and timestamps remain available.
- Resulting reviewed findings remain unchanged.
- The meeting summary includes only confirmed results.

---

### 10. Out of Scope for Milestone 2

Do not add the following yet:

- Autonomous interruptions.
- Continuous proactive speaking.
- External business integrations.
- Long-term cross-meeting memory.
- Automatic execution of actions.
- Full identity recognition.
- A complete production security or permissions system.
- Any wider ShieldOn or Orion functionality not defined in this brief.

---

### 11. Required Delivery From Zilong

Before implementation, please add a short Milestone 2 technical proposal covering:

- Proposed architecture and end-to-end flow.
- Direct-address detection.
- Host approval flow for proactive interventions.
- Voice generation and playback.
- Evidence and transcript storage.
- Failure handling and fallback behaviour.
- Implementation tasks.
- Any required API, infrastructure, or cost changes.
- Estimated delivery order.

Please do not begin major implementation until we align on the technical proposal.

Milestone 2 will be approved only after all three acceptance scenarios pass on the deployed test environment.
