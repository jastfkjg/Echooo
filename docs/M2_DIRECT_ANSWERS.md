# M2 direct answers: recent context and historical search

## Behavior

The live model first receives the question, recent saved passages, up to four recent
exchanges, and authorized project knowledge. It returns `answer`, `search`, or
`clarify`. Supported factual answers require source IDs; a clarification asks about
an ambiguous request without searching. An initial `insufficient` verdict also
triggers one historical check before it can be delivered.

A search uses 1–4 model-generated query variants, scoped by the server to the owner
and current meeting. The server retrieves original passages and adjacent context,
then makes one final model call. A second search request is rejected. The model must
distinguish supported facts, insufficient evidence, unresolved conflicts, and general
conversation; valid citations alone do not prove semantic correctness.

## Retrieval and limits

- Original transcripts stay in the existing database. Search builds a disposable
  lexical inverted index in a worker thread, using English/Unicode words and CJK
  bigrams with BM25 ranking. No embedding credentials or vector service are required.
- Search covers the saved meeting history, including text outside the recent window
  and beyond the beginning of long passages. Candidates include strong matches,
  later matches, and neighboring context, ordered by recording/audio time.
- Recent passages: at most 60 and 12,000 text characters. Search results: at most
  18,000 text characters. The serialized model context, including metadata, is capped
  at 40,000 characters; lower-priority history/knowledge is dropped first. This is a
  character budget, not a provider-specific token guarantee.
- At most two model calls; generation plus search has a 12-second deadline, with a
  2-second search deadline. TTS and waiting for the floor are separate. Stop cancels
  the pending work; the retrieval worker cooperatively stops on cancellation.
- There is no persistent secondary index to become stale. Each search reads current
  rows. Evidence changes or new saved discussion during generation invalidate the
  answer; the discussion is checked again before voice playback.

Lexical retrieval can miss paraphrases even with query variants. “Insufficient” means
no supporting answer was found in the available evidence, not proof that the meeting
never discussed the subject. Independent semantic evaluation remains necessary.

## Feedback and persistence

The host sees **Checking earlier discussion…** during historical retrieval and final
answer generation. Insufficient and conflicting evidence have distinct messages;
provider/search failures remain errors and are never reported as absent evidence.

An additive `meeting_answer_checks` table records action, support state, search usage,
model-call count, candidate counts, and elapsed/search time, without model reasoning
or duplicate transcript text. It is available in activity, meeting detail/export,
and workspace export. Source references include a versioned hash. Restart cancels
pending searches without replay; deleting a meeting removes its check records.

## Automated verification

```bash
.venv/bin/pytest -q tests/test_meeting_answers.py tests/test_meeting_agent.py tests/test_meeting_turns.py tests/test_meeting_knowledge.py
node --test tests/*.mjs
```

Coverage includes recent answers without search, old evidence beyond 60 passages,
Chinese queries, long-passage tails, later revisions, cross-owner/meeting isolation,
invalid citations, unsupported states, search limits, timeout/stop, transcript changes,
restart, export, and deletion. Provider responses are simulated in these tests.

For the configured live model, using only synthetic data in a temporary database:

```bash
.venv/bin/python scripts/evaluate_meeting_answers.py
```

This uses provider credits and does not read or modify application meetings. Review
printed answers as well as the structured assertions. It covers recent/old decisions,
missing budget, proposal versus approval, revised decisions, ambiguous questions,
untrusted instructions, and Mandarin evidence.

Local measurements during development: a 3,000-passage synthetic search took
95–100 ms across three runs. One live-model evaluation passed 8/8 cases, taking
1.78–2.45 seconds for recent-answer/clarification paths and 3.48–4.86 seconds for
search paths. These exclude STT/TTS and are not deployed latency guarantees.

## Manual deployed test flow

Use a live LLM, AssemblyAI, server TTS, and the Attendee connector, with **Answer when
called** enabled. Browser-only local recording does not exercise this direct-answer
path.

1. State a team communication decision, then ask Echooo which platform was selected.
   Expect a brief spoken answer and a source link without host approval.
2. Repeat after enough unrelated discussion to move the decision outside recent
   context (more than 60 saved passages). Expect historical search and the original
   decision as evidence. Also test a later change to the decision.
3. Ask for an approved budget when none exists. Expect an uncertainty response, an
   `insufficient` check, and no invented amount. A proposed-but-unapproved budget
   must not become an approved one.
4. Ask an ambiguous question. Expect a short clarification. Interrupt a pending
   search with Stop; no delayed answer should be played.
5. Refresh/reopen the meeting and inspect activity, sources, and exported
   `answer_checks`. Responses and support states should remain without replay.
6. Disconnect the model/connector and retry. Expect a failure state, not a false
   “no evidence” result. Record end-of-question and first-audio time separately from
   the stored generation timing.

Real meeting audio, echo behavior, and deployed acceptance require this manual run;
synthetic model evaluation does not certify them.
