# assistant — engineering rules

The smallest component in Shelby. It classifies, calls, gates, and logs. **No domain
logic, ever** — if a change here needs to know what a timeline or a heading index is, it
belongs in a tool instead.

## Boundaries

- **Never import from a tool's repo.** The provider seam in `config.py` is a deliberate
  copy of meet-ai's, not an import. Sharing code across a repository boundary is how a suite
  of independent tools quietly becomes a monolith again — which is the exact failure this
  whole architecture was a response to. A little duplication at a boundary is the cheaper
  mistake.
- **`tools.yaml` is the only file that knows every tool exists.** Adding a tool is an entry
  there; no module gets edited. (The one exception is `watchers.py`, which names the tools whose
  long jobs deserve a "finished" notice: meet-ai's transcription and audiobook's jobs.)
- **Credentials and paths are injected into tools, never discovered by them.** The `env` on
  a server entry is that mechanism.

## The gate

- Approval is decided from the tool's own `readOnlyHint`, never from a list here.
- **Absent annotations fail closed.** A tool that forgot to annotate itself must not get a
  free pass; `read_only=bool(annotations and annotations.read_only_hint)`.
- Anything that is not an explicit `y`/`yes` is a decline.
- **The model must not ask permission in prose.** The system prompt says so explicitly.
  Without that, you get two gates: the model asks, the user answers the model, and the turn
  ends before the gate ever fires. Found live at M0 — the first two runs of a two-tool chain
  both stalled this way.

## MCP SDK — two traps, both sprung

**mcp 2.x exposes snake_case attributes and keeps camelCase only as a wire alias.** The
Python objects have `input_schema` and `is_error`; `inputSchema` and `isError` are the
aliases. Reading an alias off the object does not raise — `getattr(result, "isError", False)`
returns the default — so **every tool failure was silently recorded as a success** until a
real `invalid_grant` made it visible. Check the field list before reaching for a name you
remember:

    .venv/bin/python -c "from mcp.types import CallToolResult; print(list(CallToolResult.model_fields))"

**An exception raised while starting servers hangs the process instead of surfacing.**
`ToolRegistry.__aenter__` builds an `AsyncExitStack` of child processes; a failure part-way
through leaves them attached to a half-built stack and the program deadlocks with no
traceback at all. The `except BaseException: await self._stack.__aexit__(*sys.exc_info());
raise` around that loop is what turns a silent hang into an error message. It cost an hour
to find once — an `AttributeError` from the rename above, presenting as a hang.

## Memory

- **It is the assistant's own state, and no tool may read it.** Tools take what they need as
  arguments. The moment a tool reaches into memory, it stops being usable alone and Shelby
  has a shared mutable centre again.
- **Not pgvector, on purpose.** Everything fits in a prompt at this scale, and sending all of
  it is more accurate than any retrieval. `relevant()` is the seam; narrow it only when the
  prompt genuinely gets too big.
- **Memory failing degrades what the assistant knows, never whether it runs.** A missing or
  malformed file loads as empty; a turn whose memory cannot be read (the database went away) goes ahead
  with the context it already had (`Hub.run`).
- **Memory is background, not instruction.** It is framed that way in the prompt because a
  remembered line is data the user wrote once, not an order outranking what they say now.
- **Both memory tools are gated.** Writing about a person should be visible as it happens.

## The database (`db.py`, `migrations/`)

Memory, the audit log and sign-in sessions live in PostgreSQL when `DATABASE_URL` is set, which only the
container setup does (`compose.yaml` builds it). Unset, they are the files they were -- `memory.json`,
`audit.jsonl`, sessions in a dict -- and that is what every test uses, so `./test` needs no database. Each
is an abstract store with two implementations (`MemoryStore`, `AuditStore`, `SessionStore`), and **every
store method is `async`**, which is why `LocalTool.handler`, `prepare`, `context_for`, `tools_status` and
`audit.record` are too. Raw asyncpg and plain SQL, no ORM, no Alembic.

- **Migrations are numbered files, applied once, never edited.** `migrate()` runs every file in
  `migrations/` not yet in the `migrations` table, each in its own transaction (a half-applied file leaves
  nothing and is retried), under an advisory lock. A change to the schema is a new, higher-numbered file.
- **`users`, `dossiers` and `dossier_refs` exist and nothing uses them.** They are the schema multi-user and
  dossiers will need (`../plan.md`), laid down so those are not a migration of live data. `user_id` is
  nullable on `facts` and `audit_log` until then.
- **The old files are imported once, then renamed `*.imported`** (`import_legacy_files`, on connect). Facts
  merge by id; the audit log is imported only into an empty table, so a file that could not be renamed is
  not imported twice. A fact whose kind the table refuses (a hand-edited file) is kept as `fact`. Nothing is
  deleted: to go back, rename the files and drop the database.
- **The stores read the pool when called, not when built**, so `create_app` builds them before the event
  loop exists and the lifespan connects. `app.state.database` is how `main()` prints which store is in use.
- **A tool must never get the database address.** Tools inherit the backend's environment, so
  `tool_environment()` removes `DATABASE_URL` (`WITHHELD_FROM_TOOLS`). Note that it does not remove the other
  secrets the backend holds (`ASSISTANT_TOKEN`, `GOOGLE_CLIENT_SECRET`): they were inherited before and still are.
- **Failure modes follow the rules above.** `audit.record` never raises (a failed write is logged);
  audit reads that fail return nothing; a session lookup that fails is "not signed in" (the guard must answer,
  not crash); a memory write that fails raises, so the tool reports it.

Four things worth knowing, each checked directly against a real server (2026-10-28):

- **Facts keep their order through `updated_at`, which defaults to `clock_timestamp()`, not `now()`.**
  `now()` is one value for a whole transaction: six facts inserted as f e d c b a came back a b c d e f
  with `now()` (they tied, and the id broke the tie) and f e d c b a with `clock_timestamp()`. The import
  writes every fact in one transaction.
- **A subject is matched with Python's `lower()`, not SQL's.** SQL's follows the database's locale. In this
  image's `en_US.utf8` the two agree on `AYÉ`; in a database made with the `C` locale SQL gives `ayÉ` and a
  name with an accent would stop matching its own correction. Matching in Python is the same in every locale.
- **An asyncpg pool belongs to the event loop it was made in.** Used from a second `asyncio.run` it fails with
  `InterfaceError: another operation is in progress`. The tests therefore run each Postgres scenario inside
  one `asyncio.run`, and do not share a store across calls.
- **The postgres container runs as your uid, not its own.** Without `user:` the data folder on the host is
  owned by uid 70 and cannot be deleted or moved without sudo. The image needs the uid to exist in
  `/etc/passwd`, so compose mounts the host's, read-only.

Testing it: `tests/test_database.py`. The Postgres tests skip unless `TEST_DATABASE_URL` names a server they
may create databases on (each test makes one and drops it), so point it at a throwaway:
`docker run --rm -d -p 127.0.0.1:55432:5432 -e POSTGRES_PASSWORD=test postgres:16-alpine`, then
`TEST_DATABASE_URL=postgres://postgres:test@127.0.0.1:55432/postgres ../.venv/bin/python -m pytest tests/test_database.py`.

## Honest reporting

- **A tool reporting its own failure is a failure.** MCP returns that as `is_error` on an
  otherwise successful response, not as a raised exception. An audit log that records a
  failed build as `ok` is worse than no audit log.
- The audit log never raises. A broken log must not break the work.

## The web server

- **Chat and buttons are one state.** A button that changes something becomes a note handed
  to the model with the next message; a model's action streams to every view. Two apps that
  happen to share a backend would let "stop the recording" and "write it up" refer to
  different things.
- **Notes are held until a turn boundary.** Appended mid-turn, a note would sit between a
  tool call and its result, and the model's API rejects that shape.
- **Every call takes `session.execute`,** chat or button. Two paths would drift — the button
  one would quietly lose its audit row or its preview the first time only the other changed.
- **A failed turn rolls the conversation back** to before it, keeping the button notes. A
  turn that dies mid-way can leave a tool call without its result, which poisons every
  later turn.
- **Status polls from buttons are not noted.** Only calls that change something are; a poll
  every few seconds would bury the model's context.
- **Security:** 127.0.0.1 unless `ASSISTANT_HOST` says otherwise (only the container setup does, inside
  its own network, with the port published to 127.0.0.1, a Tailscale sidecar, and, when `SHELBY_HOME_ADDRESS` is set,
  one private home-network address for the TV app, never to the world; it prints that it is not
  localhost-only); a token on every `/api` request; Host must be localhost or an
  exact name in `ASSISTANT_HOSTS` (parsed by `parse_hosts`: names only, never patterns). The token may
  appear in a URL only for `/api/events`, because EventSource cannot send headers. Who may use the API
  is decided in one function, `authenticate()`, which says who a request is from: the whole API (`FULL`) or
  a scope (see "Scoped tokens").

## The interface is a separate program (`../web`)

**This server is the API only.** The web app lives in Shelby's top-level `web/`, is served
by its own process on its own port (8751; Vite's dev server on 5173), and calls this API across
origins. Separated completely on 2026-09-28. What that cost, and what it forced:

- **This server can no longer inject the token into the page**, since it serves no page. The
  first answer was a paste-the-token Connect screen, and it was rejected on sight: a step every
  launch is a cost nobody should pay for a local app. Now `../start` makes the token (random,
  per launch) and gives it to both programs, and the *web app's* server injects it at serve time
  — the same protection as before, moved to the program that serves the page. It must check
  `Host` itself (Vite's own check may run after it), send `no-store`, and never bake the token
  into `dist/`. A refused token makes the app re-fetch its own page and reload if the token
  there changed; the Connect screen remains only for the halves run separately with nothing
  shared. Google login was considered and is the wrong tool here: it proves *who*, and on one
  machine with one user the only question is whether a request comes from this app.
- **CORS is added after the token guard, so it runs outside it.** A browser's preflight
  carries no token and would otherwise be refused before CORS could answer; and the guard's
  own 401 needs CORS headers, or the browser hides the status and the app cannot tell "paste
  the new token" from "the server is down". Both are tested. Only `ASSISTANT_ORIGINS` (default:
  the web app's two origins) may read responses; the token is still required regardless.
- **No proxy.** Vite used to forward `/api` to this server, which quietly kept the two joined;
  the app now calls `VITE_API_URL` directly, the same in development as in use.

The web app itself: Vite + React + strict TypeScript. One state for both modes (`state.tsx`), fed by one event stream; the modes are views, never
separate stores. Assistant replies render as Markdown through react-markdown, which does not
render raw HTML — and approval previews are rendered as text, never markup, because they are
email bodies and transcripts someone else wrote.

Four things that only showed up by running it:

- **The event stream must send bytes the moment it opens.** EventSource fires `onopen` only
  when the first bytes arrive, and the server sent nothing until the first event or the
  15-second keepalive — so every page load showed "reconnecting" and disabled the message box
  for up to 15 s. An immediate `: connected` comment brought first byte to 6 ms.
- **uvicorn needs `timeout_graceful_shutdown`.** It waits for open connections to drain before
  stopping, and an event stream never drains — any open browser tab blocked shutdown forever,
  holding the three tool processes with it.
- **Memory is re-read every turn.** The server runs for days; a fact remembered mid-session
  must reach the next turn, not the next restart.
- **Headless Chrome cannot screenshot this page with `--virtual-time-budget` or `--timeout`.**
  The first waits for network idle, which an event stream never reaches; the second works by
  stopping all network activity, which kills the stream and makes the page report
  "reconnecting" — corrupting exactly what it is measuring. Drive a real browser session
  (Puppeteer against the installed Chrome) instead.

## Uploads, and the file store (`uploads.py`, `files.py`, `texts.py`, 2026-10-31)

Audio to transcribe, a book (PDF) and a voice sample arrive at `/api/uploads/*` and land in the
**file store**: `<ASSISTANT_FILES>/<id>/<name>` (`/data/files` in the containers, `files/` in a bare
checkout, never committed), each recorded in the `files` table (`migrations/002_files.sql`), or in
`index.json` at the store's root with no database. **Markdown goes into the database itself**, see below.
**An upload ends in a path, and a path is all any tool takes** — so meet-ai, docu-ai, audiobook and
apply-ai did not change and do not know the store or the database exists. The same file works from a
button or from chat. Layer 1b of `../plan.md`; this is its phase A.

**Markdown: the text is in the database, and a tool is lent a copy for one call (the user's call,
2026-10-31).** An uploaded or drafted document is a `docs` row in `files` plus one `file_texts` row per file
(`migrations/003_file_texts.sql`), written in one transaction; the database holds its only lasting copy, and
nothing of it is on disk between calls. Its path is `<ASSISTANT_TEXTS>/<id>/<name>/` (or that folder's one
file), which the listing, the model and the audit log see. **Every call to a tool runs inside
`registry.lend(arguments)`** (`ToolRegistry.call`, so chat, buttons, previews and schedules alike): any string
in the arguments, at any depth, that names a stored document gets a read-only copy written there just before
the call (whole, renamed into place) and removed when it ends, with a `.draft` marker in an assistant's draft.
Two calls naming one document share one copy. Nothing else is touched: a path naming no stored document reaches
the tool unchanged. Leftovers from a crash are cleared on start, and only names a lend makes (`texts.clear`).
The texts folder must not be, or hold, the file store (`create_app` refuses). In the containers it is
`/tmp/assistant-texts`, inside the container and deliberately not under `/data`. Why a lend and not a tool
reading the database: no tool may get `DATABASE_URL` (the user chose this, 2026-10-31, once it was clear the
backend needs no model to run). The assistant's own `read_document` and `write_draft` read and write the
database directly.

- **Uploading markdown**: a batch is held in memory (`DocBatches`) until `done`, then stored whole, so a broken-off
  upload stores nothing. 20 MB for a whole batch, at most 5 open, an hour each. A file must be UTF-8 with no NUL
  (PostgreSQL's text holds none); anything else is refused, never stored lossily. Run for real on a copy of the
  real data: the 4 drafts went in byte for byte, docu-ai and apply-ai (real processes) read lent copies, apply-ai
  refused a draft by its marker, neither tool process held `DATABASE_URL`, and nothing was left on disk.

- **A folder per file, named by an id, holding the file under its own name.** Not a content hash and
  not per-user folders: tools use the name (docu-ai titles a Doc after its folder or file, audiobook names a
  book's audio after its PDF, meet-ai a transcript after its recording), so it is kept exactly, and an
  upload of the same name again keeps it too, in a folder of its own (no more `name (2).ext`). The id says
  nothing about whose a file is; that will be `user_id` on its row. The SHA-256 is recorded for checking.
- **Deleting is by id** (`POST /api/uploads/delete {id}`), since two uploads may share a name, and a slot is
  removed only once empty: audiobook writes a book's `.corrections.txt` beside its PDF, and that stays.
- **`GET /api/files/{id}`** sends an upload (a PDF, a recording) for the app to play or download; the old
  `GET /api/files?path=` still serves what a tool made, from its declared folders, until phase B moves that.
- **The old `uploads/` folder is copied in once** (`import_old_uploads`, when `main()` passes it): each file
  into a slot of its own, checked by hash, recorded with its modification time as when it was uploaded; each
  markdown folder into the database, read back and checked by hash, a draft folder (`.draft`) as made by the
  assistant; then each old folder is renamed `.imported`. A markdown folder that is not UTF-8 text is left in
  `docs.imported` and said so at start. Safe to run again (same kind, name and hash is skipped).
  `uploads/exports/` stays: docu-ai saves files there for mail-ai to attach. Tests never import: `create_app`
  only does when given `legacy_uploads`, and `tests/test_server.app_for` always gives a temporary store.
- **apply-ai reads only where documents are lent** (`APPLY_AI_ROOTS` is `ASSISTANT_TEXTS`), and still refuses
  a folder holding `.draft`, which the lend writes into a draft's copy: the row says it too, but apply-ai reads
  folders, not the database.

- **The request body is the file**, streamed to disk; nothing is buffered whole, and no
  multipart parser is involved. The web app uses XMLHttpRequest, not fetch, for these: only it
  reports upload progress. (Markdown is the exception: held in memory, under its batch's limit.)
- **Every name is hostile.** Each path component is checked, the result must resolve inside
  the store, and a file is written to `.part` and renamed only once complete — a half-received
  recording is never listed or transcribed. Tested.
- **Markdown arrives as a batch** named for the uploaded folder (or file), because docu-ai uses
  the folder's name as the Doc's default title. One file builds as a file (one tab, no cover);
  several as a folder. docu-ai reads only a folder's top level, so the web app sends only
  top-level `.md` files and lists the rest as skipped, rather than uploading files that would
  silently do nothing.
- **Each upload is noted for the model** with the next message, like a button press — which is
  what makes "transcribe what I just uploaded" work, from either mode.

## Documents attached in chat (`convert.py`, `PUT /api/uploads/document`, 2026-11-20)

Chat refused anything but audio and `.md` ("only audio or markdown"). A PDF, a Word file (`.docx`) or plain text
(`.txt`) is now taken: its text is taken out and kept exactly as an uploaded markdown file is (a `docs` row and one
`file_texts` row, `CV.pdf` kept as `CV.md`), so `read_document`, apply-ai and docu-ai all take it, and the model is
told "its text was taken out (pictures and layout are not kept)". The user's choice over handing the PDF itself to
the model, which would have meant PDFs only, the whole file re-sent every turn, and nothing the CV checks could read.
The file itself is not kept: it is read from a temporary folder, under a name of ours, and that folder is removed
whatever happens. An old `.doc` is refused with "save it as .docx".

- **Intake, not domain logic.** It changes a file's format, as checking markdown is UTF-8 does, and knows nothing of
  what a document says.
- **A PDF or Word file is read in a child process**, `python -m assistant.convert FILE NAME`, never in the backend:
  PDFium (pypdfium2) and libxml2 (python-docx) are native code reading a stranger's file, and PDFium has crashed the
  audiobook tool before. The child gets no secrets (`CHILD_ENV`: no token, database address or model key), a 3 GB
  memory limit and 90 s, and answers one line of JSON. A crash, a hang, a library's exception or nonsense on stdout
  is that upload refused in plain words ("could not be read: the file may be damaged"). Plain text is read in-process.
- **A hyphen at a line end is kept.** PDFium joins a word that runs over a line end and marks the hyphen with
  U+FFFE, for "Role-Based" and "distin-guishes" alike (21 in a 36-page paper, about half real compounds; both in a
  real CV were). Dropping it makes words nobody wrote ("RoleBased"), and the CV checks match words, so it is "-".
- **Word headings come only from Word's own styles** (Title, Heading 1-6; lists from List styles or numbering;
  tables a row to a line). A file that makes headings by setting Normal text bold and large (a real one did) reads as
  plain lines: the text is all there, the `#` marks are not.
- **Not handled:** a scanned PDF (no text layer) is refused and says so, rather than read by OCR; a PDF with a
  password is refused; headers, footers, comments and pictures in a Word file are not read.
- **Run for real (2026-11-20)** on a throwaway backend (own folders, no tools, port 8760), not the containers (a
  render was running): the user's real CV PDF (0.3 s), a real 37,000-character Word file (0.9 s) and the 36-page
  arXiv paper (1.3 s); then a real turn on Sonnet 5.5 called `read_document` on both and answered from them
  correctly. The chat box in Chrome at 360-1440, both themes: the chip, the refusal, no overflow, axe clean but for
  the sidebar's "Search and jump" button (`label-content-name-mismatch`, there before this).

## What tools made, kept (`records.py`, `collect.py`, 2026-11-01)

Layer 1b, phase B of `../plan.md`, in the shape the user chose ("A", 2026-11-01): **a tool labels what it made; the
assistant files it under those labels without knowing what it is; the page that knows (Audiobooks) reads it back.**
The workshop and the warehouse: the tool keeps working at its own bench, alone or in Shelby, and finished work is
carried to the store and the database.

- **Two agreed names, like `login_status`.** A tool that keeps things offers a read-only `inventory` (items: `kind`,
  `key`, `labels`, `text`, `version`, `files: [{path, role}]`, `release`) and a `release` (delete these working
  copies, each named by path and the SHA-256 of the copy filed; the tool checks the hash first). Only the names are
  agreed. Only a read-only `inventory` is ever called. audiobook is the one tool that offers them (`keeping.py`).
- **Collecting** (`Collector`): at start (the first time, that is the taking-in of what is already there), after any
  call to the tool that may have changed something (`registry.changed`: not read-only, not failed; never the
  collector's own `inventory` or `release`, or it would set itself off for ever, which a test pins), and when the
  watcher sees one of its jobs finish a chapter or end (`watch(on_change=...)`). One at a time; asked again while one
  runs, it runs once more after. An item whose version is filed already is skipped (a restart files nothing twice).
- **Every file it takes is a plain file in a folder the tool declared** (`files:` in `tools.yaml`, now also the
  collection boundary): not a link (even to the tool's own file), not a relative path, not `..`. Copied into a slot of
  its own (`kind made`, `made_by tool`, never listed among uploads), checked by hash; a failed copy leaves nothing.
  Filing the same key again replaces the record and drops its old files (`files.drop_made`, which never touches an
  upload). Released only after filing, and only items the tool marked `release`.
- **The database:** `records` (unique on tool, kind, key; labels JSONB; body; version) and `record_files` (role ->
  file, `ON DELETE RESTRICT`, so a named file cannot be removed under its record), `migrations/004_records.sql`;
  `records.json` with no database. `GET /api/records?tool=`, `GET /api/records/{id}` (with its text), `POST
  /api/records/delete {ids}` (buttons only, audited as `assistant__delete_records`, noted); kept files play by id
  (`/api/files/{id}`). `assistant__list_kept` lets the model see them, since the tool no longer lists audio it gave up.
- **Run for real (2026-11-01)** in a container built from this code, on a copy of the real data and a throwaway
  Postgres: 105 audio files filed with their originals' SHA-256 and released, 3 voices filed and left at the bench,
  12 jobs filed with readable logs, nothing filed twice by a restart; the Audiobooks page showed what the live one
  shows, book for book and chapter for chapter; a real render of a chapter was filed with its exact text, replaced
  the old copy and left the bench. See `../plan.md` -> Built and verified.

## Drafting documents (`documents.py`)

`list_uploads`, `read_document` and `write_draft` let the model change what a document *says* —
tailor a CV, rewrite a report — which it could not do before: asked to "create a CV for an ML
engineer role" it formatted the upload as it was and replied as though it had tailored it. Local
tools, like memory, because stored documents are the assistant's own state (in the database, read and
written there directly). Four rules, each from something that went wrong live:

- **A draft is always a new file.** The original must survive to be compared against.
- **The approval shows the draft rendered, whole.** A local tool can now `render` its own
  preview; a document as a JSON string cannot be reviewed. And the browser's approval preview is
  no longer cut at the terminal's 4,000 characters (`WEB_PREVIEW_LIMIT`): a CV's approval
  stopped mid-word there, hiding Skills, Education and Certifications from the person approving.
- **A rewrite is measured against its original.** With `based_on`, the approval opens with the
  sections missing and points kept, and the model is told the same. A first "tailored" CV
  silently ended after its first project — 7 of 18 points — while the model said it had only
  reordered. The prompt already asked for honesty; the count is what caught it.
- **Say what was and was not done.** The system prompt now requires it, and forbids inventing
  experience, employers, dates, qualifications, figures or skills.

- **A draft is marked as the assistant's own** (2026-10-15). `write_draft` records it as made by the assistant,
  a lent copy of it carries a `.draft` file beside it (`texts.py`), and `list_uploads` reports `draft: true`. A check that compares a new draft with "the user's own material"
  (apply-ai) refuses a marked folder: on a second application the model passed its own earlier cover letter
  as a source, and a claim it had made would have been supported by itself. A convention in a filename, not an
  import. Drafts written before the marker have none (add `.draft` by hand).

A CV is built with `docu_ai__build` and `theme: "resume"`, a cover letter with `theme: "letter"` (a letter in the
CV look came out cramped, in the report look it ran onto a second page), both of which docu-ai's model door offers.

**What runs around a draft, and where it lives.** Before drafting, `apply_ai__requirements` sets the posting
against the material and the model asks every gap in one message; after drafting, `apply_ai__claims` traces the
draft's claims to source lines; after saving, `docu_ai__build` returns a page count and layout warnings and
`docu_ai__trash` clears the Doc a rebuild replaces. **None of that is in the system prompt**: it is in those
tools' own descriptions, which is where "no domain logic, ever" puts it. A real run followed it with no prompt
change. `MAX_TOOL_ROUNDS` is 30 for it: 12 stopped a legitimate tailoring mid-trim, with the answer to the
user not yet written (found live, 2026-10-15).

## Books and voices (audiobook)

`PUT /api/uploads/book` takes a PDF into `uploads/books/`, and `PUT /api/uploads/voice` a recording
to clone a voice from into `uploads/voices/` — **apart from `audio/`, which is meetings**, so a voice
sample never shows up as something to transcribe. Same rules as every upload: hostile names,
`.part` then rename, a path is all the tool gets, and each is noted for the model. The tool is
`audiobook`; the assistant knows nothing about books.

## Audio a tool made (`GET /api/files`)

How the web app plays and downloads what a tool rendered and has not yet handed over (since phase B, finished
audio is kept in the store and played by id; this serves only what is still at the tool's bench), without the
assistant learning where any tool keeps anything. Five rules, the first four tested in `tests/test_uploads.py`:

- **A tool declares what may be served, in `tools.yaml`** (`files: [output]`, relative to the tool's
  own folder). The API serves only audio files inside a declared folder; the registry's
  `media_roots` is the whole list.
- **The check is on where the file really is.** `resolve()` follows symlinks and `..` before the
  folder test, so a link inside `output/` that points outside it, or `output/../x.mp3`, is refused.
- **Only audio extensions** (`MEDIA_TYPES`): a declared folder is not a licence to send `.env`.
- **Every refusal is the same plain 404** — outside the folders, wrong kind, missing — so the answer
  says nothing about what exists elsewhere.
- **The token stays out of the URL.** Its rule is still "a URL only for `/api/events`", because
  EventSource cannot send headers; an `<audio>` tag could, but only by putting the token in its
  `src`, where it is kept in logs and history. So the web app `fetch`es the file with the header and
  plays a blob (`web/src/api.ts` → `fetchMedia`). The cost is that a file loads whole before it
  plays: a four-hour M4B is ~115 MB. Taking that over a token in a URL was deliberate.

## Authentication: what a Google sign-in changes

The next big feature, scoped here so the container and Tailscale setup would not have to be redone for
it. **Not built.** Today `authenticate(request)` accepts the launch's token; signing in adds a second way
to be recognised there.

- **The shape.** OpenID Connect (authorization code + PKCE) done by *this* backend: `/auth/login`,
  `/auth/callback`, `/auth/logout`, and `/api/me` for the page to ask "who am I". Verify the ID token's
  signature, `iss`, `aud`, `exp` and `email_verified`, then require the email to be in
  `ASSISTANT_ALLOWED_EMAILS` (one address to begin with). The session is a random id in a server-side
  store, sent as `HttpOnly; Secure; SameSite=Lax`, with an expiry.
- **Its own Google OAuth client, scopes `openid email` only.** Not the clients docu-ai and mail-ai use:
  credentials stay with their tool, and the sign-in belongs to the assistant. Those scopes are
  non-sensitive, so no Google verification is needed. (The existing OAuth app is in "Testing", which is
  why the Docs and Gmail tokens expire weekly; that does not touch signing in.)
- **The topology is already right.** The page is at `https://<SHELBY_HOST>` (443) and the API at
  `https://<SHELBY_HOST>:8443`: one host, so one *site* and a `SameSite=Lax` cookie goes to both; two
  ports, so two *origins*, which means `allow_credentials=True` with the exact origin list (never `*`),
  `credentials: 'include'` on every fetch, and `withCredentials` on the EventSource. With that the
  `?token=` exception for `/api/events` can go. Keep requiring a custom header on state-changing
  calls so a cookie alone cannot be replayed by another site.
- **The page stops carrying a secret.** `WEB_INJECT_TOKEN=0` (already supported) and the app shows
  "Sign in with Google" when `/api/me` says 401. Decide at build time whether the token still works for
  `127.0.0.1` as a break-glass; it should not work over the tailnet once sign-in exists.
- **First step, before any code: does Google accept `https://<SHELBY_HOST>:8443/auth/callback`?** Google
  wants redirect URIs on a public top-level domain and `*.ts.net` has not been tried. Register it in a
  test OAuth client and see. If it is refused, the options are a custom domain pointing at the tailnet
  node with its own certificate, or Tailscale's own verified identity headers (which `tailscale serve`
  adds for tailnet users) in place of Google. Don't build the rest until this is known.
- **One allowed account, not accounts.** Per-user data (`memory.json`, uploads, each tool's credentials)
  is the larger option (c) in `plan.md` and is not part of this.

## Scoped tokens: the TV (`ASSISTANT_TV_TOKEN`, `scopes` in `tools.yaml`, 2026-11-23)

The launch token can do everything: any tool through `/api/actions`, Mail's reading included. The TV app (`../tv`) has
its token built in and will reach the backend over the home network in plain http (step 9 of `../tv/plan.md`), so it
gets a token of its own that can play books and nothing else. Built and run for real on 2026-11-23, with the user's
yes to "audiobooks only".

- **The token.** `ASSISTANT_TV_TOKEN` in `.env`, passed to the backend only (`compose.yaml`). Fixed, not random per
  launch, because it is built into the APK. At least 24 characters and not the launch token, or the server does not
  start (the message never holds a token); unset means there is no such way in. No tool holds it
  (`WITHHELD_FROM_TOOLS`); checked in the running container, where only the backend and its init do.
- **The allowance is declared by the tool's entry in `tools.yaml`** (`scopes: {tv: {actions, records, files, uploads}}`,
  `config.Grant`, read as strictly as `schedule`: an unknown key or a bad name stops the server), so the server names no
  tool. `ToolRegistry.grants("tv")` adds it up. A token whose scope nothing grants stops the server at start too, rather
  than look like a working token that cannot do anything.
- **Two layers.** (1) `scoped_route()` in the guard: five routes (list records, one record, a file by id, the uploads
  list, actions); anything else under `/api` is a 403 before a handler runs, including `/api/events`, `/api/files` by
  path and everything that writes. (2) The handlers narrow what is left: records only of the granted tool and kinds
  (asking for no kind gets only those kinds); a record of another kind is the plain 404 a missing one gets; a file only if
  every record that keeps it is of a granted kind and keeps it in a granted role; the uploads list shows only the granted
  kinds, the other lists empty so the shape does not change; an action only if its name is granted **and** the tool is
  read-only (a mistaken grant cannot hand out a write), checked before the tool is looked up, so a name it may not use
  gets the same 403 whether or not it exists.
- **Why not "these routes" alone** (the plan's first design). The real data on 2026-11-23: the audiobook tool's records
  are 246 `chapter`, 10 `book`, but also 51 `job` (arguments and logs), 8 `sample`, 7 `voice` (each with its recording
  and consent label), 4 `other` and 1 whole-book file; the uploads are 9 books, 8 meeting recordings, 10 documents and
  4 voice samples. Routes alone would have let the TV token list and download all of them. So the grant is `records:
  [chapter, book]`, `files: [audio]`, `uploads: [book]`, `actions: [preview_book, read_chapter]` (the plan's list left out
  `preview_book`, which step 4 of the TV added).
- **Also fixed in passing:** `authenticate()` compared tokens with `compare_digest` on strings, which raises on a
  character that is not ASCII, so a stranger's header could make a 500. It compares bytes now (`same_token`).
- **Not built, said plainly.** A TV read through `/api/actions` is quiet like the web's button reads (not audited, not
  streamed), and a refusal is not logged anywhere. Nothing limits how fast a token may be guessed (it is 32 random
  characters). The two calls take a `pdf` path and the grant does not confine it to the uploaded books: the tool reads only
  a PDF it has analysed, and said "passwd is not a PDF" for `/etc/passwd`, but a PDF elsewhere that the tool had analysed
  was not tried.
- **Found, not changed: every tool holds the launch token.** `WITHHELD_FROM_TOOLS` keeps back the database address and
  the model's key but not `ASSISTANT_TOKEN`, so on 2026-11-23 all six tool processes (web-ai, which reads arbitrary web
  pages, and mail-ai among them) held it, and it can do everything. No tool's own code reads it. Adding it to the list is
  one word; it is the user's call.
- **Tests:** `tests/test_scoped_token.py` (27, on data shaped like the real records: voices with recordings, jobs, a
  whole-book file, another tool's records, a file two records keep, a chapter's second file in a role that is not
  granted) and `holders_of` in `test_collect.py` for both stores. Eight deliberate breaks of `server.py`, each caught;
  the first set of data missed one (the role check: the voice's file was already stopped by its kind), so a case was
  added. Whole suite with a throwaway Postgres: 480 pass, none skipped.
- **Run for real** (2026-11-23, the rebuilt backend, the real records and uploads, both tokens read by the script and
  never printed): 57 of 57 as designed. 246 chapters and 10 books listed, every other kind a 403 and a plain 404 by id;
  a chapter's audio plays by range (206, 100 bytes); a voice's recording, a sample, the whole-book file, an uploaded
  meeting recording, voice and book are all 404 to the TV and 200 to the launch token; `preview_book` and `read_chapter`
  on a real book and chapter return their text; `job_status`, Mail, a recording status, `recall` and an unknown name are
  403; `/api/state`, `/api/tools`, chat, delete and upload routes, `/api/events` are 403; a Host not on the list is 403.

## Deleting (2026-10-30)

Three things the person can delete from the web app, each only by a button they press, each audited
and asked about first (`web/src/ui/ConfirmDelete.tsx`). Run for real on throwaway files, in Chrome.

- **The chat** (`POST /api/chat/clear`). Clears what the model holds (`messages`), the button notes, and
  the conversation events (`is_conversation`: messages, replies, approvals, and tool calls made from chat)
  from the live history; keeps notices, uploads and a button's own result, which Overview and Activity
  list. It emits `chat_cleared` and every open page fetches the pruned history, so the rule lives only
  here. Chat itself shows nothing from before the last `chat_cleared`: a "You pressed" chip outlived the
  first clear (found live). Refused while a turn runs or an approval waits -- the turn holds an index into
  `messages`. Memory and the audit log are untouched; it is audited as `assistant__clear_chat`.
- **An upload** (`POST /api/uploads/delete`, `{id}` as the listing gave it). No tool offers it,
  so a model cannot delete a person's files. The id is hostile, like an upload's name: it must be one the
  store made and has a record for, the file must be directly in that record's folder under the recorded
  name, of the extensions its kind is listed by. A markdown document is only rows, so deleting it removes its
  record and texts and touches nothing on disk. **A link is refused outright**: a link to another upload resolves inside the store, passes every location
  check, and the real file is what would go (a test pins it; the first version's tests passed without
  that check). Audited as `assistant__delete_upload`,
  noted for the model, and announced as `upload_deleted`. The assistant cannot tell that a file is in use
  (a recording being transcribed); the Meetings page hides its upload chips while a transcription runs.
- **A Google Doc or an audiobook** is the owning tool's: `docu_ai__trash` (to Drive's bin, its approval shows
  `info`) and `audiobook__delete_audiobook` (its approval shows `describe_audiobook`). The page fetches
  what will go with the read-only tool and calls the destructive one only on a confirmed press, never to
  find out what it would do.

## Stopping a reply (`POST /api/chat/stop`, 2026-10-31)

Chat had no way to stop a reply once sent. `Hub.request_stop` sets the turn's own `stop` event (a new one each turn,
so a stop never carries over) and answers no to any approval waiting. `run_turn` stops at the next safe point:

- **While the model thinks**, its request is raced against the stop; the answer, if it comes, is thrown away
  (the request's thread runs to its end on its own).
- **A tool already running is never cut off.** It finishes and is audited: stopping halfway through a change would
  leave it done but unrecorded. A tool the model asked for that has not started gets `STOPPED_TOOL` as its result.
- **The conversation is left whole**: every tool call answered, then one short assistant reply (`STOPPED_REPLY`),
  so the next message carries on. Run for real: a reply stopped while the model thought, then a new question was
  answered normally (the API took the conversation as it stood).
- `turn_stopped` is conversation (`CONVERSATION_EVENTS`), so Clear chat removes it.
- The check at the top of each round is a second guard: with it removed the race above still stops the turn before
  the next request goes out, so no test can tell the difference (a deliberate break of it survives). It is kept so
  that does not rest on the order asyncio runs tasks in.

Tools now carry their `title` (MCP's, or their annotations'), passed to the interface in `/api/tools` and in an
approval, so a person reads "Write a new draft" rather than "draft new". The model is still shown name and
description only.

## Every login at a glance (`logins.py`, 2026-10-31)

Settings could only say a tool had "failed its last call", so a lapsed Google login read as "Check" with a raw error, and the
sidebar showed a green dot beside a model that could not answer. `Logins` (`Hub.logins`) checks the model's login and each tool's
together, remembers the last answer, and announces a change once; Settings, the sidebar and the watcher all read it.

- **A tool says its own login state; the assistant never reads a token.** A tool that can offers a read-only `login_status`,
  answering `{state, detail, service}` with `state` one of `ok`, `dead` (refused: sign in again), `missing` (never signed in) or
  `unknown` (could not tell). mail-ai and docu-ai do; only the name is agreed, so a tool with no such door is simply not asked.
- **Only a read-only tool is called for it** (`tool_logins`), as with an approval's preview: a tool that used the name for
  something that changes things must not be run by a page looking at health. Tested.
- **"Could not tell" is never "fine".** A tool that raises, answers late (`LOGIN_WAIT`, 25 s), fails, or says something unreadable
  is `unknown`, which changes nothing about its row and is never announced. Only `dead` and `missing` make a row an error, and
  they do whatever the last call did (before, a Google login that had lapsed was a "warning" with the raw error).
- **One command.** The fix is `./auth` for every login, said once in the banner: `SIGN_IN_AGAIN`. `model_status` now says
  `signed_out` (expired) apart from the model being out of reach for another reason (no network), and gives the hint only for the
  first, because signing in again would not fix the second.
- **The watcher checks every ten minutes, every minute while a login is out**, so the page notices within about two minutes of
  `./auth` finishing. `GET /api/status` (instant) returns what the last check found, so a page does not flash "not checked";
  `?live=true` checks now. A check is under a lock: the watcher and a page's Check now would each announce the same change.
- **Announced once, through the notice stream** (`login_notice`, `tool_login_notice`): going bad, and coming back. No event type
  of its own: the sidebar reads `/api/status` once a minute and when a notice arrives, and Activity never sees a "login" row.
- **Not covered:** a tool busy in a long call may answer late and read `unknown` for that check; a login that Google still
  accepts but whose scopes were narrowed would read `ok`.

**The model through an Anthropic API key (2026-10-31; Bedrock ends at the end of November).** `ANTHROPIC_API_KEY` in `.env` wins over
Bedrock, here and in meet-ai (`resolve_provider`), and reaches both because `.env` is the backend's `env_file` and tools inherit
its environment. `model_status` on that route (`_key_status`) asks the API for the model by id (`models.retrieve`: one read, spends
nothing) and tells three failures apart, because each is fixed differently: **`key_refused`** (401/403: replace the key, hint
`KEY_HINT`), **`model_missing`** (404: name another with `SHELBY_MODEL`, listing what the key can use, hint `MODEL_HINT`), and
anything else (the network: no setting fixes it, no hint). **"Not set up" is not an alarm:** no key and no AWS login to try
(`NoCredentialsError` and friends) is `configured: False`, level `warning`, and Settings leaves it out of the things that need
attention, because Mail, Meetings, Documents and Audiobooks work with no model at all (checked, below). A chat turn that dies
because of the model now says so in plain words with a link to Settings (`status.model_failure`; the raw error stays in the event as
`detail`) rather than "Something went wrong: <botocore text>". `SHELBY_MODEL` (or `ASSISTANT_MODEL`, which wins) names the model for
chat, `MEET_AI_MODEL` or `SHELBY_MODEL` for meet-ai. **The key goes to the one tool that uses it, and to no other (`tools.py`, `tools.yaml`).** Tools inherit the backend's environment, which
would have put a key from `.env` into web-ai (it reads arbitrary web pages), docu-ai, mail-ai, apply-ai and audiobook. `ANTHROPIC_API_KEY`
and `ANTHROPIC_AUTH_TOKEN` are now in `WITHHELD_FROM_TOOLS`, and meet-ai's entry in `tools.yaml` names them (`${ANTHROPIC_API_KEY:-}`: empty
when unset, which is not a provider). Checked on a running copy by reading each process's own environment: the backend and meet-ai
held the key, the other six tools did not. (The AWS variables are still inherited by every tool, as before.) **Not run with a real key** (there is none here): a key Anthropic never issued
was refused by the real API (`./auth --check`: `anthropic dead`), which exercised the refusal path end to end; the accepted path, and
whether `claude-opus-5-5` is a model a real key can use, are unproven until a key is in `.env`. The default id was moved from
`claude-opus-5` to `claude-opus-5-5` (the first-party default in both seams) from the model list this was written against.

Run for real against the real logins (2026-10-31): the model signed out (`signed_out: true`, the `./auth` hint), Gmail and
Google Docs `ok`, with the service names the tools gave. Then a second copy with the Gmail token replaced by one Google never
issued and the Docs token absent: Google's own `invalid_grant` came back as `dead` and the missing file as `missing`, and the page
showed three things signed out with one `./auth`. The real tokens were never touched.

## API key or Bedrock: the switch in Settings (`route.py`, 2026-11-20)

The user asked for a switch between the two ways to the model; before, `.env` decided and a key always won. The user's
choices: **Chat and meeting notes both follow it**, and **Bedrock uses Opus 4.6** (`us.anthropic.claude-opus-4-6-v1`).

- **Each route has its own model line** (`config.named_model`): `ASSISTANT_MODEL`/`SHELBY_MODEL` are the API's,
  `SHELBY_BEDROCK_MODEL` is Bedrock's (default Opus 4.6). One id cannot serve both: `claude-sonnet-5-5` on Bedrock
  would be `anthropic.claude-sonnet-5-5`, which this account does not answer to (meet-ai/CLAUDE.md -> Reaching a model).
  Before this, `SHELBY_MODEL` applied to Bedrock too; with no key it now does not.
- **Kept in `settings.json`** beside memory (`ASSISTANT_SETTINGS`, `/data/assistant/settings.json` in the containers),
  **not the database**: `./auth` runs on the host, cannot reach Postgres (no published port), and must know which
  login is in use, so that it renews AWS (which lapses overnight and opens a browser) only when Bedrock is chosen.
  Written whole and renamed into place; a missing or broken file means ".env decides". `--provider` still wins.
- **`POST /api/model/route {provider}`** saves it, makes it the hub's config (a turn already running finishes the way
  it began), tells the tools, audits `assistant__set_model_route` (origin button), and checks the new way's login at
  once. `/api/status` carries `route` (current, saved, each choice with its model and why it cannot be chosen: no key,
  no AWS profile). A dead login is not a reason to refuse: Settings shows it and `./auth` renews it.
- **A tool follows through one agreed name, `model_route`** `{provider, model}`, like `login_status`: called on start
  (so a restart keeps the choice) and on every switch, only on a tool that declares it changes something, with a
  10 s limit, never raising. A refusal counts whether it comes as an MCP error or as `{"error"}` in the answer, which
  is how meet-ai refuses. meet-ai is the one tool that offers it; its credentials stay as injected at launch. Chosen
  over restarting the tool (what was first described to the user): the registry cannot restart one server (its
  sessions share one exit stack, entered in the lifespan's task), and this needs no restart at all.
- **Run for real (2026-11-20)** on a throwaway backend with real meet-ai (port 8761, own folders): chat on the key
  (Sonnet 5.5), switch (meet-ai ok, AWS login ok), chat on Bedrock (Opus 4.6), meeting notes on Bedrock (Opus 4.6,
  notes correct), switch back, chat on the key; the usage rows said so each time. A restart kept Bedrock. Settings in
  Chrome at 360-1440, both themes, one real click each way. `./auth --check` follows the file.

## Model usage and price (`usage.py`, `007_model_usage.sql`, 2026-11-20)

The Overview's "Model usage" section (tokens in and out, calls, estimated cost, by source) is drawn from one row per
request to a model. **Nothing was recorded before 2026-11-20**, so it counts from the day it was deployed and says so
(`since`, only when `complete`).

- **Two things reach it.** Chat steps are counted where the answer comes back (`run_turn`, from `response.usage`,
  source `chat`). A tool that calls a model itself says so in its result under one agreed key, `model_usage`
  (`{model, provider, input_tokens, output_tokens}`), and `execute` records it (`count_result`, source = the tool's
  qualified name). Only the key and its four fields are agreed, like `login_status`; the assistant learns nothing else
  of the tool, and a tool run alone never reads it. meet-ai's `generate_notes` and `generate_minutes` are the only two.
  Because `execute` is the one path, a button press counts the same as chat.
- **A tool's report is untrusted.** `usage_from_result` takes it only when it is exactly a model, a provider and two
  whole token counts (no bool, float, string or negative) and stores those four fields and nothing else.
  A failed call, or a result without the key, counts nothing.
- **Tokens are stored, dollars are not.** `cost_usd` is worked out when `GET /api/usage` is read, from `PRICES` in
  `usage.py`, so a corrected price fixes the past. `PRICES` holds Anthropic's own list prices from the model list the
  claude-api reference carried on 2026-11-03 (input and output per million tokens), for the Opus, Sonnet and Fable
  models listed there. **A model not in the table is counted in tokens and shown with no price, never a guessed one**
  (Haiku is left out on purpose: its price depends on prompt size). `price_key` maps Bedrock's names
  (`us.anthropic.claude-opus-4-6-v1`) to the first-party id.
- **It is an estimate, and the page says so**: list prices, not a bill; Amazon Bedrock bills a model itself and may
  differ (the Bedrock route ends at the end of November 2026); no cache tokens, because neither this chat loop nor
  meet-ai asks for caching (add a column and a price if that changes). New models or price changes are an edit to
  `PRICES` and `PRICES_AS_OF`, nothing else.
- **The endpoint returns rows, not totals** (`GET /api/usage?limit=5000`, newest first, the same token guard), and the
  page groups them into the viewer's own local days (`web/src/pages/usageData.ts`, tested), as it does the audit log.
  `complete` is false when the limit cut the list short; the page then does not claim when counting began.
- **Stores follow the audit log's rules**: `FileUsageStore` (`usage.jsonl` beside the audit file) or `PgUsageStore`
  (`model_usage`, constraints refuse negative counts); `record` never raises, reads that fail return nothing.
- **Known gaps (an undercount, never an overcount):** a chat request the user stopped before its answer arrived is
  not counted (its figures never reach us); a meet-ai call that fails (`ModelOutOfRoom`, which can spend the whole
  32,000-token output budget) returns no `model_usage`; meet-ai or the terminal chat (`cli.py`) run on their own are
  not counted; the Hub's other model use, if any is added, must pass `usage=`.
- **Run for real (2026-11-20):** migration 007 applied to the real database; one real call through `run_turn` (Sonnet
  5.5 through the API key, "Reply with the single word: ok") came back as 760 tokens in and 4 out, was written to the
  real table, served by `/api/usage` and shown on the live Overview as `<$0.01`. That row is real and stays. The
  populated page was checked on seeded rows (a stand-in answering `/api/usage`; nothing seeded in the real table):
  20 width and theme combinations, no overflow, axe clean, the empty and "could not be loaded" states, and the table view.

## On a timer (`schedule.py`, 2026-10-30)

A tool's entry in `tools.yaml` may say `schedule: [{tool: sync, every_minutes: 30}]`, and the server runs that
tool, with no arguments, at start and then that long after each run ends, whether or not a page is open. Only
mail-ai's `sync` has one: every 15 minutes since 2026-11-07 (the user's choice; it was 30), and the Mail page
re-reads its list every 30 seconds, so new mail shows without pressing Sync. It used to be a timer in the web page: a closed tab left the mailbox five days stale
(2026-10-24), and two tabs synced twice.

- **Declared, never known.** The server reads `registry.schedules`; nothing in it names mail. A wrong entry
  (no tool, an interval under five minutes, not a whole number) stops the server starting, because a schedule
  that silently never ran is the failure this replaced.
- **The path a button takes**, `session.execute` with the gate answered by the declaration (`allow_gate`), and
  the origin `schedule`, which History shows as "Schedule".
- **Audited when its outcome changes**, not every run: the first run, a failure, a recovery. A row every half
  hour pushed a person's own actions out of History and the Overview when the page's timer did it. The newest
  row per tool, which Settings reads for health, is still the current state.
- **Not conversation.** No events, no note for the model. It speaks only through a notice, once when it starts
  failing and once when it recovers. A run never overlaps the one before it; a failure never stops the timer.

Run for real: the first scheduled run after a rebuild, with no page involved, was a full re-sync (the
mailbox's sync point had lapsed) that took 5 min 34 s and added 1,040 messages. A sync pressed in Mail while the
scheduled one runs reaches the same tool process at the same time; since 2026-11-21 mail-ai answers the second with
`already_running` (not an error, so the schedule does not count it a failure) and the page says "Already syncing".
Before, it failed with "database is locked".

## Memory and history in the interface

- **Facts in the prompt carry their ids.** `forget` takes an id; a prompt showing facts without
  them left the model no valid way to act on "forget that" — only a guess. `recall` lists them
  for the interface through the same audited tool path as everything else.
- **Reads triggered from the interface are not audited, and emit no events.** They are the page
  looking, and the panels poll every few seconds — auditing them buried the log under tens of
  thousands of status checks a day. The model's reads are still recorded.
- **The URL hash is followed on change, not just read on load.** A hash change does not reload
  the page, so reading it once left back, bookmarks and edited URLs showing the old section.

## Past conversations (`conversations.py`, `005_conversations.sql`, 2026-11-06)

Chat keeps each conversation in the `conversations` table: its id, a title (the first message, cut at a word,
renamable), the events Chat showed (JSONB) and how many messages it holds. It is saved after every turn and when
Chat is cleared; one with no message in it is not kept. With no database there is no history and nothing fails.
The page lists them, opens one, renames and deletes them, and **a past conversation can be continued** (the user's
request, 2026-11-06): writing in one opened from History makes it the one Chat is in.

- **Continuing gives the model back what it remembered** (`006_conversation_messages.sql`): each save keeps the API's
  own messages (the words, the tools called and what they returned, the thinking with its signature, through the SDK's
  `model_dump`), and `POST /api/conversations/{id}/continue` puts them back. The current conversation is kept first and
  Chat emptied (as Clear chat does, so held notes go too), then every page is sent the chosen one's events again.
  Refused mid-reply, audited (`assistant__continue_conversation`). Continuing the one Chat is in changes nothing.
- **A conversation kept before 2026-11-06 has no messages** and is continued from its words: each question with its
  reply, a question with no reply left out so the model's turns still alternate. What its tools returned is gone; the
  model may need to look again.
- **The page**: a past conversation shows the message box ("Write to continue this chat"); sending continues it, then
  sends. Attaching and dropping files are off there (an upload's note would be dropped by the switch), and Stop is not
  shown (it would stop the other conversation's reply).

- **The conversation Chat is in is special.** Deleted, it leaves Chat too (as Clear chat does) and is refused
  while a message in it is being worked on: left open, its next turn saved it again, deleted messages and old title
  and all (found in Chrome). Renamed, the hub's own title changes too, or the next save put the old one back.
- **A failed save is a warning, never an error** (`log` in server.py, which the first version named but never
  had: a database hiccup at the end of a reply would have raised; found while building continuing, now tested).
- **Deleting is audited** (`assistant__delete_conversation`, its title and size). Clearing saves first; deleting
  the current one clears without saving.
- **The page treats the panel and an opened conversation as one layer** (`web/DESIGN.md` -> Back): Back closes the
  panel, and from a past conversation returns to the current one. The history keeps only the id, so Forward or a
  reload fetches it again.

## Dictation, spoken replies, and tools for the page only (`PUT /api/dictate`, `POST /api/speak`, 2026-11-06)

The chat box's microphone records in the browser and sends the clip here; meet-ai's `dictate` turns it into words,
which go into the message box to be read and sent by hand. Never sent by themselves.

- **A clip is not an upload.** It goes to a temporary folder, is handed to meet-ai by path, and the folder is deleted
  whatever happens. Nothing is stored, listed, or noted for the model. It is a read from the page, so it is neither
  audited nor shown as a step (`session.execute`). 25 MB at most; refusals are `{"error"}`, which the page's upload
  helper reads.
- **`interface_only`**: a tool may say in its `_meta` that it is the page's own plumbing. `anthropic_tools()` leaves
  it out, and a model that names one anyway gets "no such tool" without anything running. Every tool the model is
  shown costs it context on every turn, and the model has no microphone.
- **`POST /api/speak {text, voice?}`** sends a sentence or two to audiobook's `speak` and returns the MP3 bytes
  (`no-store`). The same rules: a page read, not audited or shown; nothing kept; refusals are `{"error"}`. The page
  turns a reply's markdown into sentences (`web/src/components/speechText.ts`: code and tables are said to be on
  screen, never read), asks for one while the one before plays, and pauses an audiobook that is playing. **A reply is
  read only when its speaker button is pressed** (the user's choice: an automatic "Speak replies" switch was built and
  taken out the same day). The press also plays a moment of silence, because a phone's browser plays sound only from an
  element a press has started; dictating or sending stops a reading.
- **The containers' model cache does not yet hold base.en** (`data/cache/huggingface`, checked 2026-11-06). The first
  clip after deploying downloads it (about 140 MB) and is slow once.

## Approval previews

- **A tool may declare, in `_meta`, the read-only tool that renders its effect.** The gate
  calls it and shows the result instead of the arguments. This exists because
  `send_draft(draft_id, confirmation)` cannot be approved from its arguments, and the
  assistant must not learn what an email is in order to fix that.
- **Verify the named tool is read-only before calling it.** Otherwise a tool could name a
  destructive "preview" and have it run before anyone approved anything.
- **Never fall back silently.** A declared preview that could not be produced is announced;
  otherwise it is indistinguishable from a tool that offered none, and someone approves a
  send believing they saw it.
- **Sanitise preview text.** It is untrusted content — an email body — printed directly
  above a yes/no prompt, where escape sequences could repaint the screen or fake the prompt.
  Strip C0/C1 controls except newline and tab, and cap the length so a huge body cannot
  scroll the call being approved off the screen.

## The gate, continued

- **A gate that cannot get an answer declines.** `input()` raises `EOFError` when stdin is
  exhausted — piped input that ran out, a non-interactive shell — and letting it propagate
  kills the turn mid-chain with writes already done. Found live: two approved writes landed,
  then a third call hit end-of-input and crashed the session. `KeyboardInterrupt` is a
  decline for the same reason.

## Testing

No model, no child process, no network. The gate carries the most tests: it is the only
thing between a model's intention and a write, and it must work without depending on a
model behaving well.
