# Project meetings

Echooo is a personally managed assistant that joins a meeting as an independent AI
participant. Selecting a project makes its current shareable knowledge available to
that meeting. There is no separate memory-selection or disclosure checkbox.

## Set up a project meeting

1. Expand **Project knowledge** in the sidebar to create a project or use an existing one.
2. Add confirmed memories. Mark information **Shareable** if it may be used in project
   meetings. Private, audience-restricted, expired and unreviewed information is excluded.
3. Create a meeting and select the project. Its eligible memories are available immediately.
4. Open the project name to set an optional meeting goal. **Knowledge** previews available
   memories; **More options** adds reference projects.

New shareable memories and edits become available automatically on the next request.
Marking a memory private, restricting it, expiring it or deleting it removes access.
The meeting header shows the current available count. Projects with more than 100
memories are supported; there is no per-meeting selection limit.

Existing project meetings adopt this behavior too, including meetings whose legacy
selection was empty or partial. No-project meetings still use only their discussion;
they never inherit the `default` domain. The main project is fixed after the meeting
starts. Reference projects are read-only; reviewed updates go to the main project.

Raw source documents are currently private. Import a source, extract memories and review
them before making them shareable. This release does not infer attendee group membership
or give private knowledge to someone who sends the bot a private message.

## During a meeting

**Transcript** includes completed spoken replies under **Echooo AI**. Older reply times
are approximate (`~`); new replies have recording-clock anchors. Outbound speech may
not be in the mixed recording, so these entries do not offer **Play original**. They
are searchable and export as `assistant_utterances`, separately from human evidence.

Use **… → Messages & activity** for private chat, delivery errors and reply sources.
Interrupted or failed output stays there rather than appearing as completed speech.
Memory citations retain their version and show when the source changed. Passage
citations open the supporting conversation.

All eligible project memories participate in retrieval. Each answer receives a relevant
subset of at most 12 memories and 30,000 content characters, using lexical ranking and
a bounded fallback. Access is checked before generation, after generation and during
outgoing audio. Changes during a reply can stop that reply; the next request uses
current knowledge. Older answers with an obsolete knowledge scope are excluded from
model history. Revocation cannot retract words already heard or repeated publicly.

Citation validation checks that supplied sources exist in the model input; it does
not prove every claim is supported. Meeting summaries and answers still need review.

## Save meeting outcomes

1. End the meeting.
2. In **Summary & notes → Project updates**, choose **Prepare updates**.
3. Review wording, attribution and supporting passages.
4. **Confirm & save**, or **Dismiss**.

New memories default to private. Choosing **Shareable in project meetings** makes the
saved memory available to meetings using that project. Assistant replies and private
chat are excluded from human evidence. Changes to evidence or replacement targets
block stale approvals. Drafts preserve proposals, decisions and uncertainties as
separate concepts; approving a memory does not authorize an external action.

Extraction processes the full transcript in bounded batches. Later statements can
change earlier conclusions, so review the source context. Deleting a meeting or
recording also removes linked proposals and reviewed memory derivatives. Existing
recording and provider retention policies continue to apply.

## API and upgrade

- `POST /api/meetings`: `title` and optional `project_id`.
- `GET /api/meetings/{id}/knowledge`: current settings, eligible memories and drafts.
- `PUT /api/meetings/{id}/knowledge`: `project_id`, `goal`, `reference_ids`, `revision`.
- `POST /api/meetings/{id}/memory-proposals`: prepare updates after ending.
- `POST /api/proposals/{id}/review`: approve or reject a draft.

The former `memory_ids`, `share_with_meeting` and `share_project_knowledge` input fields
are no longer accepted. Legacy stored grants remain for schema compatibility but no
longer restrict project retrieval. Per-answer receipts still record the exact scope
and source versions used. All reads remain owner-scoped; private-chat and delegation
permissions are unchanged.

Restart the local app and refresh browser tabs after upgrading. No Attendee rebuild
is required. Regression tests cover live additions, updates, permission revocation,
large projects, references, citations, cross-owner isolation and reviewed writes.
