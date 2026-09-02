# Roadmap

Domains remain user-managed. The product focus is a controllable personal representative: communicate within the right information scope, know when to involve the owner, and leave memories that can be inspected and corrected.

## Priority 1: Live speech pilot

Connect the current text, permission, and approval flow to live STT, LLM, and TTS providers. Start with one-to-one project discussions, including Mandarin. Build a repeatable evaluation set covering cross-domain probing, prompt injection, implicit commitments, noise, and revocation during a turn. Measure first-audio latency, incorrect disclosure, unapproved commitments, owner takeover, and memory correction rates.

Acceptance criteria: deterministic authorization tests remain passing; no known cross-domain leaks in the pilot attack set; every side-effecting decision has explicit authorization; real users assess recognition and voice quality. Passing a finite evaluation set is not proof of absolute safety.

Speech improvements include exact played-text accounting after interruptions so context does not assume the guest heard everything, more natural silence detection, reconnection and backpressure, and first-response latency improvements that preserve output checks. Measure before choosing sentence-by-sentence checking and synthesis.

## Priority 2: More useful memory

- Add source chunking and pgvector semantic retrieval. **Filter owner, domain, and disclosure scope before retrieval.** Bind retrieval caches to authorization versions too.
- Add memory types, effective dates, source confidence, expiry reminders, and conflict comparisons. Automatic classification proposes changes; it does not move information between domains on its own.
- Support bulk import, incremental synchronization, reversible batch review, data import and export, and formal schema migrations.
- Support domain hierarchies or tags without implicitly inheriting disclosure permissions. Shared facts require explicit authorized references.
- Optional low-risk automatic memory updates must be enabled separately by the owner for each domain and retain evidence, versions, and rollback. New commitments, sensitive information, and conflicts still require review.

Acceptance criteria: new retrieval paths pass the same cross-domain tests; reducing permissions invalidates access immediately; deletion covers indexes, caches, and derived data; labeled evaluations demonstrate improved semantic recall.

## Priority 3: Meeting participation and private decisions

- Integrate LiveKit or WebRTC for multiple participant tracks, identity, and speaker attribution, followed by specific meeting platforms. The bot identifies itself as AI and respects participant recording and data choices.
- Let the owner observe, take over, pause the agent, and submit one-time public instructions. Clearly distinguish private notes from statements authorized for disclosure.
- Introduce a separate internal decision component that can read private constraints and emit typed action proposals. The public reply model still does not receive reservation prices, private schedules, or other raw secrets.
- Give negotiations enforceable limits on amounts, time slots, or attempts. Escalate when limits are exceeded. Validate each action type by its parameters and results instead of relying on a broad instruction to negotiate.

Acceptance criteria: new participants do not inherit excess access; uncertain identity or speaker attribution blocks attributed learning; internal and public agents exchange only necessary, validated information.

## Priority 4: Real tools and deployment hardening

Start calendar, email, and project integrations with read-only queries, then add individually approved writes. Use explicit parameters, short-lived authority, idempotency keys, verified execution results, and bounded retries. Expired approval or changed tool parameters requires a new review.

Separate migration and runtime database accounts. Add formal schema migrations, shared conversation and revocation coordination, background jobs, spending quotas, detailed auditing, backup and restore drills, and a deletion ledger. Complete this work before considering public multi-owner deployment.

## Not an immediate priority

Do not rush into training STT or TTS models, cloning a person's voice, making unsupervised commitments, or connecting every meeting platform at once. Before adopting an integrated Voice Agent API, demonstrate domain filtering before model access, permission checks before speech publication, complete revocation, and controlled memory writes. Otherwise, keep the independent orchestration layer.
