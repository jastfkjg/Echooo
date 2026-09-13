# Project meetings

Echooo is a personally managed project meeting assistant. In a meeting it is an
independent AI participant, using the discussion and explicitly selected project
knowledge. Personal advice and private knowledge remain in the private workspace.
This release does not provide shared team administration or verified attendee groups.

## Before the meeting

1. Create a knowledge domain for the project in **My domains**. Existing domains
   already work as projects; there is no duplicate project catalogue.
2. Add confirmed memories, or import a document and review its extracted memories.
   Only unexpired memories marked **Shareable**, with no audience restriction, are
   eligible for meeting disclosure in this version. Raw uploads and pending proposals
   are not included automatically.
3. Create a meeting and optionally select its project. Existing meetings start with
   no project or shared knowledge. The meeting URL never determines the project.
4. Open **Project & knowledge**, add an optional meeting goal, and select the memories
   that everyone in this meeting may hear. **Reference domains** provides optional
   additional sources. Confirm the disclosure checkbox and save.

A project association alone grants no knowledge access. No project means the bot uses
only the meeting discussion; it does not fall back to the `default` domain. The goal
is public assistant context, so it must not contain private supervision instructions.
A private message to the meeting bot does not authenticate someone as the owner or
unlock private knowledge.

The main project is fixed once recording, transcript entry, or bot participation
begins. Start another meeting to change it. Knowledge selections and the goal can
still be revised, including revoking all shared knowledge. Saving settings cancels
pending bot replies. Changing or expiring a selected memory invalidates its grant;
reopen settings to review its current version before sharing again.

## During the meeting

The bot retrieves only from the selected, still-valid memories. Retrieval uses the
existing lexical ranking with a bounded fallback for paraphrases: at most 12 memories
and 30,000 content characters. There is no global search or vector index in this release.
Public replies and private meeting-chat replies use the same approved project scope;
private replies may additionally use only that sender's private chat history.

Open **Assistant activity → Sources** to inspect the memories and transcript passages
cited by a reply. Memory references carry a version; changed sources are labelled
instead of displaying new text as if it supported the old answer. Transcript references
can open the supporting conversation. References persist after the bot leaves.

Citation IDs are checked against the exact input supplied to the model. This validates
source membership, not whether every claim is entailed by a source. Answers and
attribution still need evaluation. The audio transport, wake word, follow-up model,
and interruption controls continue to work as before.

Grants are revalidated after generation and on outgoing audio commands. Earlier
knowledge-bearing replies are excluded from model history after their scope changes.
Revocation cannot retract speech already heard, an in-flight chat delivery, or words
that participants have repeated into the public transcript.

## After the meeting

1. End the meeting.
2. In **Summary & notes → Project updates**, select **Prepare updates**.
3. Review each draft's wording and supporting passages. It may add a memory or propose
   replacing one in the main project. Reference domains are never write destinations.
4. Choose **Confirm & save**, or **Dismiss**. New memories default to private. The
   optional **Make available for future meeting sharing** checkbox makes them eligible
   for explicit selection in a future meeting; it does not automatically share them.

Extraction processes the transcript in bounded batches and compares it with relevant
memories from the main project. This owner-only review process may read private
project memories for comparison; they never enter public bot replies through that
path. Private meeting chat is excluded. Known assistant speakers and text matching
recorded bot answers are excluded conservatively; mixed-audio attribution is imperfect,
so review the speaker and original evidence before accepting a draft.

Proposals retain passage IDs, speaker attribution, recording positions, and a content
fingerprint. Corrected or removed evidence blocks approval. A changed replacement
version also blocks saving over the newer memory. Dismiss stale drafts before preparing
new ones. Repeated preparation returns existing unreviewed or approved drafts rather
than adding duplicates. If every previous draft was dismissed, an explicit preparation
request can create a fresh set.

Approving a memory confirms a record; it does not approve a business commitment or
execute an external action. Statements of possibility, personal promises, adopted
decisions and unresolved conflicts must remain distinct. Model classification is not
proof of consensus. Compare related passages across the meeting during review,
especially when a later discussion reverses an earlier proposal.

Deleting a meeting or recording removes its linked proposals and reviewed memory
derivatives, including dependent conversation copies handled by the existing deletion
logic. Recording deletion can therefore affect project memories. Original audio,
transcript retention, backups and provider retention follow the existing operations
policies. Knowledge-source revocation does not delete the public meeting recording.

## Implementation

The upgrade adds three owner-scoped tables without changing existing recording tables:

| Table | Purpose |
| --- | --- |
| `meeting_knowledge` | Primary domain, references, public goal, versioned disclosure grants and settings revision |
| `meeting_answer_sources` | Reply scope and validated source references |
| `meeting_proposal_links` | Meeting provenance and fingerprints for reviewed memory proposals |

`meeting_knowledge.py` owns scope validation, restricted retrieval and draft extraction.
`meeting_agent.py` integrates project context and playback revalidation. The existing
proposal review and memory-version machinery handles approved writes.

| Endpoint | Purpose |
| --- | --- |
| `POST /api/meetings` | Optional `project_id` on creation |
| `GET /api/meetings/{id}/knowledge` | Project settings, grant health and linked drafts |
| `PUT /api/meetings/{id}/knowledge` | Revision-checked settings and explicit disclosure consent |
| `POST /api/meetings/{id}/memory-proposals` | Owner-triggered extraction after the meeting ends |
| `POST /api/proposals/{id}/review` | Existing approval/rejection route, with meeting-evidence validation |

The detail/export response includes `knowledge`; the meeting library includes project
names. All new tables participate in owner scoping and PostgreSQL RLS. Project/domain
and disclosure restrictions are application checks in addition to owner-level RLS.

Restart Echooo after upgrading. The new tables are created on startup. Existing meetings
retain all recordings and remain unscoped until configured; meetings that have already
started cannot acquire a different project retrospectively. No Attendee rebuild is
required for this feature.

## Validation and limits

Integration tests cover project isolation, explicit disclosure, reference-only domains,
project locking, revision conflicts, cited answers, revoked generation/playback,
source changes, draft review, evidence correction, assistant-text exclusion, foreign
citations, and a two-meeting memory cycle. Mock extraction is explicitly a local demo;
it is not a semantic quality evaluation. Multi-owner collaboration, automatic sharing,
verified meeting identities, automatic writes, external actions and raw-document
retrieval are outside this first version.

Release checks: 224 Python tests passed (one optional PostgreSQL test skipped), and
66 JavaScript tests passed. The isolated browser walkthrough covered creation, sharing,
review and citations on desktop/mobile in light/dark themes. A synthetic live-model
check exercised grounded answers and updates. The existing meeting transport was not
retested in a new external call for this release.
