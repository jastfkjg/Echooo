# Architecture and information boundaries

## Product model

A domain is a user-managed data object. Each workspace starts with an ordinary `default` domain, and each source, memory, and proposed update belongs to one domain. Quick chats read and propose updates within `default`. Users may explicitly choose other domains, or disable memory by selecting none. Automatic proposals use one destination domain and require owner review. A discussion scoped to a single project reads and writes only that domain.

```mermaid
flowchart TD
    Owner[Owner] --> Domains[User-defined domains and confirmed memories]
    Owner --> Grant[Conversation authorization]
    Domains --> Select[Check domains, audience, versions, and expiry]
    Grant --> Select
    Guest[Guest text or speech] --> Input[Text input or STT]
    Input --> Scoped[Conversation-scoped context]
    Select --> Scoped
    Scoped --> Draft[Reply draft]
    Draft --> Check[Output check and citation validation]
    Check --> Approval[Owner approval for new decisions]
    Check --> Output[Checked text and TTS]
    Approval --> Output
    Scoped --> Evidence[Attributed memory proposals after the conversation]
    Evidence --> Review[Owner edits, approves, or rejects]
    Review --> Write[Versioned memory in the authorized domain]
```

## Four permissions

| Permission | Current implementation |
| --- | --- |
| read | Valid memories in `default` for quick chats, or individually selected memories in explicitly enabled domains |
| disclose | A subset of read, marked shareable and matching the audience; **the delegated reply model receives only this subset** |
| act | `ask`: new commitments await owner approval; `none`: share information without accepting decisions |
| write | One selected domain and a separate learning switch; only proposes updates until the owner approves them |

Private information selected for read but not disclose never enters the public reply model. This release does not implement a separate internal decision agent that reasons over a private reservation price. Read permission alone does not expose that price to the public model. An audience is an owner-defined authorization label, not a verified organization identity. Invitations are bearer credentials and should be delivered to the intended person.

Domains, selected memories, audience, destination domain, and action policy are fixed when a conversation is created. Delegations also have a fixed authorization expiry; private chats have no time-based expiry (`expires_at = null`) and retain their transcript for later continuation. Startup migration clears legacy private-chat deadlines without reopening ended or revoked conversations. The authorization snapshots memory versions. Editing a selected memory or domain revokes active conversations using it. Delegation expiry, selected-memory expiry, deletion, and revocation also stop replies and playback. Changing domains starts a new conversation with an empty transcript; the previous chat remains in history. A private chat cannot be converted into a delegation.

## Code responsibilities

| File | Responsibility |
| --- | --- |
| `database.py` | Persistent tables, owner-scoped repository, PostgreSQL RLS |
| `auth.py` | Password verification, hashed credentials, one-time invitations, expiry, revocation |
| `contracts.py` | Strict input validation; rejects additional authority fields |
| `service.py` | Domain, memory, authorization, reply, approval, learning, and deletion rules |
| `intelligence.py` | Retrieval within authorized facts, model calls, draft checking, read-only extraction |
| `rooms.py` | WebSocket identity revalidation, STT, interruption, checked speech output |
| `ingestion.py` | Bounded file-to-text extraction without automatic remote fetching |
| `app.py` | HTTP and WebSocket routes, same-origin restrictions, static interface |
| `web/app.js`, `web/voice.js` | Owner and guest interfaces, explicit recording and playback |

All browser paths share the Service permission checks. Models have no database connection, dynamic SQL, arbitrary domain query, filesystem access, or external side-effect tools. They return structured proposals and cannot grant authority.

## Identity and storage isolation

- This release is a single-owner deployment. Registration closes after initial setup. Tables still have owner_id, and repository queries always use the authenticated owner.
- Owner and guest use separate HttpOnly, SameSite=Strict cookies. Only SHA-256 hashes of random tokens are stored. Passwords use scrypt. Invitation tokens arrive in a URL fragment, which is removed on page load; redemption atomically consumes the original token.
- A guest credential is bound to one conversation. It does not grant owner APIs, domain lists, private notes, authorization details, or other rooms. Issuing another invitation invalidates previous guest credentials.
- PostgreSQL application-data transactions switch to the `echooo_scoped` role, which has no login or BYPASSRLS privilege. RLS restricts reads and writes using the trusted owner scope. SQLite relies on repository and service checks.
- RLS is currently **owner-level**; domain and disclosure restrictions are explicit Service checks. Initialization and authentication connections retain elevated privileges. Database administrators, server administrators, and a fully compromised application process are outside this boundary. Production hardening requires separate migration and runtime accounts.
- Mutating HTTP requests and WebSocket connections check origins. Responses prohibit caching and set a CSP. There is no cross-site CORS interface. Non-browser API clients may omit Origin but still require valid credentials.

## Reply path

1. Revalidate the caller credential and active authorization on both HTTP and WebSocket paths.
2. Load only valid facts selected for this conversation. Delegated replies use disclose; private replies use read. Private supervision notes are excluded.
3. Rank within the authorized set by lexical relevance. Live models receive at most 12 memories, totaling approximately 36,000 characters, plus the latest 12 messages from this conversation. Additional authorized candidates without exact lexical overlap are retained within that budget so the model can interpret paraphrases. **There is no vector index or cross-domain semantic search yet.**
4. Generate a JSON draft and validate its structure and citations. Delegated replies also call a checker. A denied check, invalid structure, unknown citation, or provider failure produces a limited fallback, without provider errors, keys, or request context.
5. Route new commitments to owner approval using a one-time state update. The owner supplies the exact message authorized for the guest.
6. Revalidate authorization and caller credentials after generation to catch expiry, revocation, or invitation rotation during the model call.
7. Publish only checked text, then play it. Interruption cancels the current generation or synthesis. Active connections also revalidate periodically and before sending audio chunks.

Database and input-context scope restrictions are deterministic. Model attribution, implicit commitment detection, and output checks can be wrong; this is not a guarantee of zero disclosure. Information volunteered by participants, entered in a conversation goal, or explicitly included in an approval may enter the conversation context. The goal field therefore asks users not to include secrets, while private supervision notes are stored separately.

## Learning and corrections

Files are first stored as domain-bound sources. Extraction creates pending proposals only. Conversation learning runs after a normal ending and includes speaker attribution and evidence IDs. Revoked conversations do not automatically produce memories. Private supervision notes and the assistant's own replies are not evidence for new memories. A client's request retains its attribution instead of becoming the owner's commitment.

On approval, the owner may edit the title, content, disclosure setting, audience, and expiry, then add or replace a memory. New memories default to private. Replacements validate the destination domain and expected_version. A version mismatch returns a conflict rather than silently overwriting changes. Earlier versions retain provenance and evidence; restoring earlier content creates a new version.

## Deletion and traceability

Deleting a domain removes its sources, memories, versions, proposals, and conversations using that domain, including messages and approvals. Deleting a source or memory also removes conversations that read it. Deletion follows memories derived from those conversations and their historical versions, preventing retrievable copies from surviving deletion of their source. Mixed-domain conversations and derived memories may therefore be removed together, even if a derived memory was saved in another domain.

This is application-level deletion propagation. Already heard, captured, or exported information cannot be recalled. Database WAL, backups, and provider-retained data need separate lifecycle policies; see Operations. Audit records support local traceability and are not tamper-proof legal evidence. Conversation review currently provides attributed statements and decisions, not automatically organized meeting minutes.

## Language, speech, and deployment boundaries

The interface, application-owned notices, and documentation default to English. Stored user content is not translated or rewritten. Live model prompts continue to follow the latest message language; browser speech chooses a matching voice for English or Chinese text. Chinese recognition patterns and literal provider speaker IDs are retained for compatibility.

The current media layer uses a PCM WebSocket connection between the browser and FastAPI. STT, LLM, and TTS remain replaceable. Using AssemblyAI for STT keeps personal data and authority orchestration independent of the speech service. Browser synthesis prefers a local device voice, but the device may use cloud speech; a private CosyVoice service provides explicit control over the synthesis location.

This release has no LiveKit, multiple participant tracks, or meeting bot. First validate a single guest's authorized conversation, then connect the same Service to WebRTC or LiveKit. Broadcasts, cancellation tasks, and locks live in one process, so deployment requires one worker. The transcript records the full published text; it does not prove that a participant heard every audio segment. Exact played-text accounting after interruption remains a future acceptance item.

## Global private-chat entry

The home page, sidebar, and conversation list share an immediate private-chat
entry, `POST /api/sessions/quick-chat`. The server resolves or creates the owner's
`default` domain and snapshots its confirmed, unexpired memories in the same
transaction as session creation. Only that domain is authorized for reads and
end-of-chat proposals; disclosure remains empty. It uses the normal authenticated
text and voice paths, version checks, and owner review. Neither other domains nor
previous transcripts are inherited.

Initial setup creates `default` atomically with the owner. Startup also provisions
existing owners with no domains. The ordinary domain CRUD rules still apply; a
renamed or deleted `default` is replaced by a fresh empty domain on the next quick
chat. An existing domain named `default` is reused without changing its content.
Explicit custom sessions can still set empty `domain_ids` and `read_ids`, with
`write_domain_id=null` and `allow_learning=false`, to disable personal memory.

The owner can explicitly save one of their own messages through
`POST /api/sessions/{id}/memory-proposals`, supplying a destination, title, and
content. This creates a pending proposal with the original message as evidence.
It cannot copy assistant messages, another conversation's messages, or another
owner's domain. Scoped chats only allow destinations in their selected domains;
a general chat can target any domain the owner explicitly chooses. Creating the
proposal does not change the chat's permissions. Manual proposals do not prevent
normal end-of-chat extraction in sessions where it was separately enabled.
