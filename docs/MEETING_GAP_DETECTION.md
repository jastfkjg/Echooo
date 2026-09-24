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
| Maximum batch wait | 30 seconds | Continuous transcript updates cannot postpone an eligible batch indefinitely. |
| Automatic call budget | 3 calls per rolling 60 seconds, per meeting | Includes generation, append-only relevance checks, and failed attempts. |
| Approval check reuse | 30 seconds | Reuse only for the same question, proposal revision, and exact transcript fingerprint. |

The maximum batch wait is a scheduling target, not an end-to-end latency promise.
Stable complete input, an available budget, and completion of an in-flight check
are still required. A model request and any necessary relevance check add latency.
Budget exhaustion takes precedence over the batch wait; work remains pending.
These scheduling counters are process-local and reset on server restart. Existing
suggestions, evidence, host reviews, and check audit records remain durable.

New speech arriving during a request joins one pending batch rather than creating
one request per utterance. A manual Check bypasses background timing and budget;
repeated clicks during an active check reuse that work. Manual checks also postpone
the next automatic generation. Directly addressed answers and host approval checks
remain separate from the automatic gap budget. Findings extraction is also still a
separate pipeline, so the limit is not a limit on all meeting model calls.

## Uncertainty and changed evidence

`needs_followup` now means wait for new or corrected speech. It no longer schedules
a second model call on unchanged evidence. The next batch tells the model that the
previous assessment was awaiting clarification. Clear material issues should still
be proposed on the first assessment; elapsed time alone does not prove a gap.

When speech arrives during generation, a candidate may need a relevance check
against the latest stable context. This check consumes the same automatic budget.
If no budget remains, the draft is not published and its input is not marked
processed; the next eligible batch reassesses the latest discussion.

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
2. Persist issue-level state and explicit links from a clarification to participant
   answers and resulting provisional findings. Keep human review and audit history.
3. Select incremental discussion and relevant original evidence using that state,
   retaining retrieval for older unresolved issues and conflicting commitments.
4. Evaluate shared batch analysis for findings and gaps. Do not make gap detection
   simply wait for the existing findings generation and verification chain; measure
   latency and semantic quality before replacing the separate pipelines.
