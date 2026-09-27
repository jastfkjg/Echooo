# Meeting gap detection

## Current scheduling policy

Automatic gap detection groups durable transcript additions and corrections into a
single pending batch per meeting. It still uses complete, stable speech units and
contextual model judgment; scheduling rules do not classify gaps or infer owners,
deadlines, decisions, or resolutions.

| Control | Default | Behaviour |
| --- | --- | --- |
| Transcript stability | 1.2 seconds | Recently changed speech waits before entering detection. |
| Quiet interval | 4 seconds | Prefer a pause in transcript updates before assessing a batch. This is not an audio silence detector. |
| Minimum generation interval | 20 seconds | New automatic generations cannot start more frequently. |
| Task clarification grace | 20 seconds from the assessment start | One bounded reassessment for unqueued waiting tasks, even without new speech; subject to quiet time, model latency and the call budget. |
| Maximum batch wait | 30 seconds | Continuous transcript updates cannot postpone an eligible batch indefinitely. |
| Automatic call budget | 6 calls per rolling 60 seconds, per meeting | Includes generation, append-only relevance checks, task publication reviews, and failed attempts. New generations require at least two available calls. |
| Approval check reuse | 30 seconds | Reuse only for the same question, proposal revision, and exact transcript fingerprint. |

The maximum batch wait is a scheduling target, not an end-to-end latency promise.
Stable complete input, an available budget, and completion of an in-flight check
are still required. A model request and any necessary relevance check add latency.
Budget exhaustion takes precedence over the batch wait; work remains pending.
The generation interval still limits new automatic generations to one every 20
seconds. Reserving capacity for generation plus review prevents fresh generations
from repeatedly consuming the only available call. A pending draft resumes its
remaining checks as soon as a call is available, without another generation delay.
These scheduling counters and pending drafts are process-local and reset on server restart. Existing
suggestions, evidence, host reviews, and check audit records remain durable. Grace
timers are also process-local: after restarting with an existing active meeting,
use **Check** once or add new speech to rearm waiting tasks.

Budget scheduling validation on 2026-09-27: 474 Python tests passed (1 skipped),
including 73 intervention/task tests; all 141 JavaScript tests passed. Simulated
clock tests cover both 3-call and 6-call limits, repeated budget waits, review-only
resumption, appended answers, invalidated drafts, failed attempts, manual overrides,
meeting termination, and sustained two-call batches across rolling windows. These
tests validate scheduling and publication guards with mock model judgments; they
do not measure live model classification accuracy.

New speech arriving during a request joins one pending batch rather than creating
one request per utterance. A manual Check bypasses background timing and budget;
repeated clicks during an active check reuse that work. Manual checks also postpone
the next automatic generation. Directly addressed answers and host approval checks
remain separate from the automatic gap budget. Findings extraction is also still a
separate pipeline, so the limit is not a limit on all meeting model calls.

## Task memory and reminder policy

Concrete tasks are now tracked in owner-scoped `meeting_task_gaps`, separately from
visible questions and reviewed findings. The same detection call returns task
updates and, when appropriate, a suggested question. Waiting tasks survive reload
and later discussion; their source passages are retained in context alongside recent
speech. Task memory never approves an action item or authorizes playback.

Recognized gaps and ready questions are displayed separately. The collapsed header
shows **Suggested questions N · Tracked gaps M** when there are unqueued open tasks
with current evidence. Opening the panel shows their task, assessed missing fields,
and expandable context with transcript links. These read-only entries do not offer
speech approval controls. A missing field is shown only when the stored semantic
assessment identifies it; the UI does not infer owners or deadlines from text.

Resolved/dropped tasks and tasks with obsolete evidence are hidden from tracking.
Tasks already represented by queued, saved, dismissed, or spoken questions are not
duplicated there; persisted semantic links to legacy questions also count. Corrected
tasks awaiting a replacement can remain visible until a reviewed question is ready.
New speech updates tracking and can produce a question through the existing review
pipeline. An unqueued waiting task also receives one bounded reassessment after the
clarification grace window. If supported, a question enters **Suggested questions**,
where the host can approve or dismiss it. Silence never starts speech.

The model assesses each task's remaining ownership, timing or assignment-scope gap
from context. A first-person commitment from an unnamed participant is not by itself
missing ownership. Useful relative timing can be sufficient. Speculative work does
not need an invented deadline. During an ongoing allocation exchange, the task is
initially held internally. After the grace window, a concrete committed deliverable
with a material unresolved assignment or coordination detail can use `readiness=review`
and enter the private queue without an explicit topic transition. Generation and
independent review both apply this rule. Unfinished speech, speculative work and an
allocation answer demonstrably in progress still wait. Elapsed time is scheduling
context, not evidence of a task, missing field or urgency. A relevant topic transition or verbal meeting wrap-up can make a
reminder appropriate; a current blocker can justify an earlier question. The end
of the available transcript and elapsed silence do not prove a discussion boundary.

New task reminders combine related gaps and follow a separate publication policy:

- All material ready tasks can enter the private queue in the same assessment
  (up to 12 task questions plus two non-task questions). They share a single
  publication review call. There is no cross-task cooldown or active-question cap.
- The UI quietly updates its count without opening the panel. When opened, the
  first three questions are shown, prioritizing delivery in progress and blockers;
  the rest remain available under **More questions**. Saved items stay separate.
- A linked task cannot produce another paraphrased reminder after dismissal,
  deferral or speech without a semantic material-change judgment and new evidence.
- Task state is reassessed with new or corrected speech. Host deferral, dismissal,
  cancellation or completed speech also schedules one budgeted check if ready tasks
  still lack queue items. This is not new semantic evidence or permission to repeat
  a dismissed question. Waiting tasks receive at most one grace reassessment per
  unchanged transcript fingerprint. A still-unready result waits for new evidence;
  there is no recurring model polling. Ended meetings, deleted/corrected evidence,
  resolved tasks and questions already handled by the host cannot be promoted by
  the timer.
- Resolved/cancelled work withdraws pending questions. Partial answers invalidate
  questions asking about known details. A verified replacement refreshes the same
  queue item with only the remaining gaps, preserving **Saved for later** and an
  audit of its previous wording. Until verification succeeds, outdated wording is
  not available for approval. Approved or spoken questions are never auto-rewritten.
- Publication never starts speech. Each question still requires host approval and
  the existing current-context check before playback; audio delivery stays serialized.

Before a task-linked draft becomes visible, an independent semantic review checks
the current discussion stage and compares it with prior questions. Waiting tasks do
not incur this extra call. The review consumes the same automatic call budget, with
a 10-second call limit and a 25-second total task-assessment window for ordinary
batches. Timed private follow-ups allow up to 25 seconds for generation, 15 seconds
for review and 45 seconds for the whole assessment, because several saved tasks
can require more output. Approval and voice-check limits are unchanged. Budget or
context changes defer publication. Ordinary non-task detection retains its earlier window.
This is a deliberate cost/latency tradeoff to reduce premature and duplicate reminders.

Task identity, materiality and discussion boundaries are semantic model judgments,
not keyword rules. The server validates IDs, exact evidence and transcript versions,
then enforces lifecycle and duplicate guards for task-linked questions. Existing
non-task clarification and contradiction handling remain available. Legacy suggestions
without task IDs are also supplied to the independent review for semantic duplicate
suppression. Validated matches on an individual task are saved, so later checks retain
that human disposition. Task matching itself is still model-dependent.

Meeting detail/export expose `tracked_tasks` for inspection, and workspace export
includes the storage table. Check audit records include `task_updates`, `task_reviews` and
`held_reminders`, distinguishing waiting and duplicate holds. `followup_task_ids`
identifies tasks reassessed after the grace window. Historical interval
and active-slot holds remain in earlier audit records.

### Bounded follow-up verification (2026-09-27)

The scheduler now arms one follow-up for unqueued waiting tasks, checks current
meeting/evidence/disposition at expiry, and preserves eligibility while the call
budget is exhausted. Dedicated generation and independent review prompts assess
private queue readiness without importing the ordinary topic-boundary requirement.
New speech during generation uses the ordinary contextual recheck instead of
retaining permission from the old quiet window.

The final full deterministic run passed 492 Python tests (1 skipped); all 146
JavaScript tests passed. The 91 focused intervention/task tests cover grace expiry,
no recurring same-context polling, a natural answer during the grace window and
in flight, budget waiting, ended meetings, deleted evidence, shutdown and preventing
an ineligible model-generated `review` state. Publication leaves speech unapproved.

A full live semantic run passed 26/28 cases before the dedicated follow-up prompts;
the failures involved natural completion and an allocation answer in progress in
the new follow-up scenarios. The focused dedicated-prompt run passed 4/5: English
and Mandarin concrete tasks entered the queue, completed and speculative tasks
were suppressed, but one active-allocation case was queued prematurely. This is a
known semantic limitation, not fixed by the scheduler; host review remains required.
An isolated in-memory replay of the reported multi-deliverable transcript also
exposed the former 12-second follow-up generation timeout; the larger private-batch
window addressed that failure. A later replay with the final prompts and an
accelerated scheduling clock completed the actual persistence/review pipeline:
three tasks were linked to one proposed question asking for ownership and timing,
with zero new transcript units at reassessment. No approval or playback was invoked.
One preceding real-time replay still held all tasks, so model decisions remain
variable; a passing observation is not a recall guarantee. These synthetic checks
do not establish end-to-end microphone/playback reliability.

### Private queue verification (2026-09-27)

A subsequent local replay of the 11:44 detection exposed a visibility gap: two
tasks had `missing=[owner,timing]`, but review set both to `readiness=wait` because
the allocation exchange was continuing. Zero suggested questions therefore did not
mean zero detected gaps. The tracking UI now displays both from the saved snapshot,
without a new model call. All 146 JavaScript tests passed, including waiting-gap
visibility, partial resolution, disposition filtering and safe evidence links.
Browser replay verified the two-count header, both assessed fields, context and
transcript navigation, and a 375px viewport without horizontal overflow.

The full regression run passed 482 Python tests (1 skipped) and 142 JavaScript
tests. After adding the material-change refresh case, the focused intervention/task
suite passed 82 tests. Browser checks verified count-only updates while collapsed,
three visible questions, expandable overflow and saved items, and no horizontal
overflow at 375px width.

The first live semantic evaluation passed 22/23 checks. The new queue scenario
revealed that independently assignable deliverables were collapsed into one task.
The policy now distinguishes task identity from question grouping using general
responsibility/completion criteria. The focused live rerun passed both stages:
separate task tracking with queue coverage, followed by updating a saved question
after ownership was supplied. The entire 23-case suite was not rerun after that
prompt refinement; these finite checks are not a classification guarantee.

To verify locally, restart the backend and refresh the meeting page:

1. In a fresh meeting, discuss several committed deliverables with consequential
   missing assignments or timing. Leave a pause without explicitly moving on.
   After the 20-second grace window plus quiet time and generation/review latency,
   supported questions should enter the private queue. A budget wait may delay this.
   No question should speak until the host approves it.
2. Open **Suggested questions**. At most three are initially visible; additional
   questions are available under **More questions**. New arrivals must not reopen
   a panel that the host has collapsed.
3. Save a question for later, supply its owner, and conclude that allocation
   exchange. A verified timing-only question should keep the same queue item and
   remain in **Saved for later**, with its wording change in review history.
4. Dismiss a question and repeat the same information. It should not return absent
   a substantive evidenced change. No queue action should speak without approval.

Run deterministic regression checks without live provider calls:

```bash
STT_PROVIDER=mock LLM_PROVIDER=mock TTS_PROVIDER=browser .venv/bin/pytest -q tests/test_meeting_interventions.py tests/test_meeting_task_gaps.py
node --test tests/test_meeting_interventions.mjs
```
Deleting source recordings removes affected task memory and associated suggestions;
meeting deletion cascades. Normal startup creates the additive table in existing databases.

## Uncertainty and changed evidence

`needs_followup` now means wait for new or corrected speech. It no longer schedules
a second model call on unchanged evidence by itself. Concrete waiting tasks have
the separate, one-shot grace reassessment described above. The next batch tells the model that the
previous assessment was awaiting clarification. Blocking issues and material
contradictions can still be proposed on the first assessment; elapsed time alone
does not prove a gap.

When speech arrives during generation, a candidate may need a relevance check
against the latest stable context. This check consumes the same automatic budget.
If no budget remains, the draft is not published and its input is not marked
processed. The validated draft is retained and resumes its unfinished checks when
capacity returns, rather than spending another call regenerating the same candidate.
Appended speech still requires a relevance/task-state recheck before publication.
Corrected or deleted input, changed findings/tasks/host reviews, an explicit manual
check, or a draft age of 120 seconds invalidates the retained draft and requires a
fresh generation. Ending the meeting or closing the scheduler also clears it.
For task updates, the append-only recheck reassesses the task state as well as the
question, so an answer arriving during generation cannot leave a stale gap saved.

The host must still approve the exact question before any proactive speech. Online
and browser playback can reuse a recent approval check only if the question,
proposal revision, and transcript fingerprint match. New speech or an expired or
legacy receipt requires a new semantic check. Corrected supporting evidence blocks
the old proposal. Cancellation, meeting status, and outgoing audio guards continue
to apply even when a semantic check is reused.

## Observability and validation

Intervention check records include `model_calls`, elapsed time, and
`input_characters` for their recorded transcript snapshot. They distinguish
`awaiting_evidence`, `budget_deferred`, `speech_check_reused`, and failed speech
checks. Character counts are not token counts or a complete provider cost estimate.

Regression coverage exercises continuous speech, batched corrections, cooldowns,
rolling budgets including rechecks and failures, manual overrides, in-flight request
coalescing, no-change uncertainty, and approval reuse/expiry/invalidation. The live
semantic evaluation remains `scripts/evaluate_interventions.py`; deployed meeting
acceptance scenarios still require end-to-end validation.

Validation on 2026-09-24: 422 Python tests passed (1 skipped), and 18 related
JavaScript tests passed. The expanded live semantic evaluation passed 13 of 14
cases with the original detection prompt retained. The remaining failure was a
paraphrased suggestion about an already-dismissed issue. Semantic deduplication is
still model-dependent; this scheduling change does not establish full Milestone 2
acceptance or eliminate that failure. The evaluation now supplies the same input
fields as live detection and reports the actual response on failure.

## Follow-on work

1. Replay representative meetings and compare calls, tokens, time to suggestion,
   missed important gaps, premature suggestions, and duplicate suggestions. Tune
   the scheduling defaults from these measurements.
2. Measure task identity, boundary timing, answer-link precision and recall across
   longer real discussions while retaining independent human review and audit history.
3. Refine bounded retrieval for meetings with more tracked tasks and original
   evidence than fit in the existing context budget.
4. Evaluate shared batch analysis for findings and gaps. Do not make gap detection
   simply wait for the existing findings generation and verification chain; measure
   latency and semantic quality before replacing the separate pipelines.

## Local task-gap checks

Run `.venv/bin/pytest -q tests/test_meeting_task_gaps.py tests/test_meeting_interventions.py`.
These use simulated semantic judgments to check persistence, natural resolution,
deduplication, human disposition, reminder limits, source deletion and concurrent
speech. Run `scripts/evaluate_interventions.py` with the configured live LLM to
evaluate semantic judgments, including multi-batch completion and wrap-up scenarios.

For a manual recording test, introduce a concrete deliverable. Then either assign
it with sufficient timing during the grace window, or leave its material assignment
gap open. The first path should close the task silently; the second can surface a
private question after the bounded reassessment, without requiring a topic change. Dismiss it and repeat the same unresolved
point to check suppression. A new substantive requirement can justify reassessment.
Refresh between turns to verify persistence. The intervention checks endpoint and
`tracked_tasks` in the meeting export show why a task was held or resolved.

Validation on 2026-09-26: the full regression suite passed 462 Python tests (1 skipped)
and 141 JavaScript tests. The final focused intervention/task suite passed 61 tests.
The expanded live evaluation covers 22 cases, including unnamed commitments,
relative timing, ongoing allocation, legacy dismissal, and multi-batch wrap-up.
The final full live run passed 19/22: two provider calls timed out and the existing
pre-speech resolution check failed once. A focused rerun of those three passed 3/3.
All scenarios therefore have passing observations, but there was no single clean
22/22 run; this does not establish deterministic model behavior or real audio latency.
