# mail-ai — engineering rules

**A mailbox is a log, not a folder.** Gmail's model is a history stream with labels
projected over it. Every rule here follows from that; if a change starts treating the
mailbox as folders to poll, it is wrong before it is written.

**This is a Gmail client, not an email AI.** Triage, drafting and summarising are judgment
and belong in one declared seam above the store. Everything below it — sync, threading,
MIME, label state — is model-free, because a model that drifts on a message id sends mail
to the wrong person.

## The sync

- **Read the watermark BEFORE fetching, never after.** Afterwards skips every message that
  arrived during the fetch: the listing has paged past where they would appear, and a later
  watermark tells the next sync they were handled. Before can only cause a double-fetch,
  and the write is idempotent.
- **A 404 from `history.list` is a gap, not an error.** Gmail keeps history about a week;
  past that, full resync is the only correct answer. **Any other status is raised** —
  recovering from everything by refetching the whole mailbox hides real bugs behind a very
  expensive retry.
- **Write the watermark only after a full pass completes.** An interrupted run must start
  over rather than believe it finished.
- **Label changes never refetch.** They are the common case and they do not change the
  message.
- Resumability needs no extra state: re-list ids, skip what is already stored.
- **One watermark per label.** Gmail's history API takes a single label, so a shared
  watermark would let a sync of SENT tell the next sync of INBOX that its changes were
  handled. INBOX keeps the unsuffixed key so mailboxes synced before this existed do not
  silently full-resync.
- **SENT is synced by default, not just INBOX.** A sent message never carries INBOX, so
  INBOX-only meant sending mail the tool would never see again — a thread you replied to
  read as though you never answered. Only visible after actually sending one.

## MIME

- **Gmail strips base64url padding and the standard decoder rejects it.** Restore it, or
  every body whose length is not a multiple of four reads as empty.
- **Header names come back in inconsistent case.** Lowercase them on the way in.
- **An HTML-only message is stripped, not skipped.** Plenty of real senders never attach a
  plain alternative; skipping leaves silent holes in the mailbox.
- **A part with a filename is an attachment, not the body** — even when it is `text/plain`.
- Remove Gmail's `gmail_quote` wrapper *before* stripping tags, or the quoted history
  survives as unattributed prose.

## Live-verified against a real mailbox (2026-09-21)

First run on a real INBOX: 25 messages, 24 threads, full sync. Second run: incremental,
zero added, zero refetched. Gap recovery is unit-tested only — it needs a week-old
watermark to reproduce live.

Two things the real mailbox said that fixtures did not:

- **The HTML path is the main path, not the fallback.** 24 of 25 messages were
  Gmail-categorised automated mail, and **zero** messages came back with no extractable
  text — meaning `html_to_text` carried almost all of it. Treating HTML as a fallback is
  right by preference order and wrong by volume; it deserves the same care as the
  `text/plain` path, not less.
- **Extraction quality holds up.** Automated mail landed at ~3,800 chars over ~16 lines —
  roughly 236 characters per line, which is prose paragraphs rather than the short-line
  navigation soup that badly stripped HTML produces. Worth re-measuring the same way if the
  stripper is ever changed.

Quoted history was rare in this sample (1 message of 25), which is what an inbox of
automated mail looks like. It says nothing about the quoting rules; a mailbox of real
correspondence is still the test that matters for those.

## Quoting

Every rule is a convention, not a standard — only `-- ` is specified (RFC 3676). So each is
conservative, and the tests are mostly about what must NOT be cut: an em-dash in prose is
not a signature, a lone `From:` line is not a quote, and a subject beginning "Rebuild" is
not an accreted "Re:".

**Keep the quoted half.** It is how a mistake in reconstruction can be checked; discarding
it makes that unfalsifiable.

## Store

Threads are **derived by query, not stored**. A thread is not an independent fact — it is
whatever messages share a threadId — and a separate table is two things that can disagree
with no way to tell which is right.

## The send gate

- **`send` has no content parameter, and a test asserts it.** If `to` or `body` ever appears
  on it, compose-and-send becomes possible in one call and every other guarantee here is
  decoration.
- **Drafting and sending live in separate modules.** Nothing in `drafts.py` puts mail in
  front of anyone, so nothing there can be called by accident and have it leave.
- **The confirmation fingerprints content, not the draft id.** The id does not change when
  the draft does, so an id alone would authorise sending something nobody read. `bcc` is
  inside the fingerprint deliberately — silently adding a recipient is the edit a rendered
  review is least likely to reveal.
- A refusal is the mechanism working. It gets its own exception type and its own exit code
  so it never reads as a fault.
- **`review` must stay read-only.** If reading a draft needs approval, approving becomes two
  approvals and people stop reading the thing they are approving.

## Attachments (2026-10-29)

A CV goes out as a file, and a file is the part of an application nobody re-reads, so the gate
covers files the way it covers `bcc`.

- **The fingerprint covers every file's name and content, in order.** Adding, removing, renaming,
  replacing or reordering one changes it. With files, every field sits behind its own length, after a
  `0xFF` byte that can never start UTF-8 text, so two messages cannot be made to hash the same by moving
  characters between fields, or between a body and a file. **A message with no files hashes exactly as it
  did before** (a test pins two literals), so nothing already reviewed changes meaning.
- **Gmail keeps a file's bytes apart from the draft.** A draft names its files and sizes; the bytes come
  from a second call (`messages.attachments.get`). `review` makes that call, and `send` makes it again
  when it recomputes the fingerprint, so the check is on the file as it is at send time. The call lives
  in `drafts.py` and is a read. `compose.py` stays pure: it is handed a `fetch` function.
- **If a file's bytes cannot be read, nothing is reviewed or sent** (`AttachmentUnreadable`). A short
  read counts as unreadable: Gmail says how big each file is, and a fingerprint of part of a file is no
  check on the whole one that goes out.
- **Base64 is strict, both ways in.** The standard decoder quietly drops characters outside the
  alphabet, so a damaged file arrives looking whole. `Attachment.from_base64` and `mime.decode_bytes`
  refuse instead.
- **Refused at the door, before Gmail:** an empty file (a failed export must not go out as a CV), and a
  name that is empty, over 255 characters, `.`/`..`, has a slash, a control character (a line break would
  add a header), a line or paragraph separator, or a right-to-left override. One bad file means no draft
  at all, not a draft without it.
- **`send` still takes only a draft id and a confirmation**; a test says no function in `sending.py`
  can take a file.
- **A file arrives by path, from one folder (2026-10-30, the user's call).** A model cannot carry a file's
  bytes: one reply holds 16,000 tokens, a cover-letter PDF is at least 17,000 as base64, a Word CV at least
  217,000. So `draft_new` also takes `{path}`, read by `attach.py` (not `compose.py`, which stays pure) from
  `MAIL_AI_ATTACH_ROOT` only, which `tools.yaml` sets to the folder docu-ai's `save_export` writes to. A link
  is refused wherever it points (one to a file in the same folder would otherwise pass), as is a path that
  resolves outside the folder, a folder, and a file over the limit (checked by size before it is read).
  Each attachment is `data` or `path`, never both. **All files together are at most 10 MB** (`check_total`,
  in `draft_new` before Gmail), however they arrived. Base64 `data` still works for a small file.
- **Seen on a real draft (2026-10-30).** The real African Languages Lab CV and letter, saved as Word files
  (654,050 and 651,163 bytes), attached by path to a draft to the user's own address: `review_draft` read both
  files back from Gmail and its confirmation equalled `draft_new`'s, so Gmail held the same bytes. The draft
  was discarded through the gate. The attachment shape the stand-in uses is now an observed one.

## For the Mail page (2026-10-30)

- **`status` says when the last sync finished (`synced_at`)**, written once every label's pass is done, never
  part-way. The newest message is not that: a quiet day brings no mail, and the page said "newest 6 h ago" of a
  mailbox the schedule had synced minutes before.
- **`list_drafts` says who each draft is to, its subject, first words and when it changed**, read as `metadata`
  (headers and Gmail's snippet), so a listing never fetches a file: a job-application draft carries 1.3 MB of
  them. It is one read per draft. A draft deleted between the listing and its read is left out, not an error.
- **The page's own find, not this tool's:** an HTML newsletter's text is mostly empty lines (one was 431 of 462,
  122 in a row). The page folds them when it shows a message (`web/src/components/mailText.ts`); the stored text
  is untouched, so a model reading the thread sees what was synced.
- **Run for real:** the page saved a draft to the user's own address through `draft_new`, showed it whole at the
  first press of Send, was cancelled, opened it from Drafts and discarded it through the gate; the audit log has
  `draft_new` and `discard_draft` and no `send_draft`, Gmail held its 6 drafts again, and a sync found nothing sent.

## Is the login still accepted? (`login_status`, 2026-10-31)

Settings could not say whether Gmail was signed out, only that a call had failed. `check_login` (in `auth.py`) offers Google the
saved refresh token once, at the token endpoint, which every Gmail call does anyway, and reports `ok`, `dead`, `missing` or
`unknown`; the `login_status` tool wraps it for the reading login and, when drafting is on, the drafting one (`state` is the worst).

- **It writes nothing.** The answer is thrown away, so a check never rewrites the token and a good login stays exactly as it was.
  A test compares the file byte for byte after every kind of answer.
- **Only `invalid_grant` is dead.** Any other word from Google (`invalid_client`, a wrong secret) says something is wrong without
  saying the login is gone, and signing in again would not fix it, so it is `unknown` with Google's word attached.
- **Google out of reach is `unknown`, not dead**: no network must not tell anyone to sign in.
- **Read-only, and a test says so** (`test_only_sync_is_marked_as_writing`): the assistant calls only read-only tools for this.
- Run for real: a token Google never issued -> `dead` (`invalid_grant`); the real token -> `ok`.

## Approval previews

`send_draft` and `discard_draft` declare, in MCP's `_meta`, that a caller should show
`review_draft`'s output before asking anyone to approve them. Their arguments are opaque
identifiers — `{draft_id, confirmation}` names no recipient and no subject — so a gate that
shows arguments shows nothing worth approving.

The declaration is advisory: a caller may ignore it, and one that honours it must still
check the named tool is read-only itself. What this side owes is that `review_draft` stays
read-only and keeps rendering every recipient it fingerprints, including `bcc`.

## Scopes

Narrowest that works, added by the milestone that earns them, and each in **its own token
file** so a read-only run cannot silently pick up a send-capable credential.

**`gmail.compose` grants sending, not just drafting** — "Manage drafts and send emails",
and there is no draft-only scope. The scope therefore cannot separate drafting from
sending; only the code can. This was checked against Google's scope reference before the
design was written, and it inverted the plan: the original sequencing assumed compose for
M2 and send for M3 would provide the separation, and it provides none.

**Only `auth` may open a browser.** `load_credentials` raises unless `interactive=True`, and
only the auth command passes it. Found the hard way: `send` with no cached token launched a
consent flow and hung. From the MCP door that would block a model's tool call on a window
nobody is looking at.

## Testing

No network, no credentials, no mailbox. The sync is tested against a fake Gmail that pages
and keeps a history stream.

**A test that passes proves nothing until it has failed on purpose.** Thirteen deliberate breaks of the
attachment code were each run against a copy of the source, and one got through: a loosely-read base64
test whose stray character shifted the padding, so the loose decoder failed for the wrong reason and the
test passed either way. The fix was a payload whose base64 has no padding, so only strictness can refuse
it. Break a copy, never the source.

**Name fake state so it cannot collide with the API surface it also presents.** `self.messages`
shadows `messages()` and `self.history` shadows `history()`; both surface as
"'dict' object is not callable" a long way from the cause. That bit twice in one sitting.
