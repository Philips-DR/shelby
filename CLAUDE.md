# Shelby — rules for the whole folder

**Start here: `plan.md`** holds the current state — what is built, what is rough, what is waiting
on the user, and the next steps. This file holds the rules. Read both before changing anything.

Each tool's own `CLAUDE.md` holds its engineering rules and gotcha ledger, and wins for anything
inside that tool. **This file covers only what is true across them.** Read the tool's file before
changing the tool.

## Commands

    ./setup    # idempotent: shared .venv, audiobook's own .venv, npm ci for docu-ai and the web app, speaker models
    ./start    # ./auth, then ./start-docker up: database, backend (API, :8750; launches every tool over MCP stdio) and web app (:8751), in containers
    ./start-docker up [--tailscale] [--ngrok]   # what ./start runs; the flags add a private or a public address
    ./test     # all nine test suites (the eight tools' and publish-check's). Must pass with no credentials, no model, no network
    ./auth     # every login (AWS, Google Docs, Gmail): renews only the dead ones, and copies Google tokens into data/config for the containers; --check to just look
    ./renew-secrets   # a server's logins: sends it fresh AWS credentials + Google tokens over ssh (README → "On a server")
    ./publish-check   # before every push: the commits GitHub lacks, for secrets (exit 1) and personal details (exit 2); --all for every commit

## The web app and the backend are separate programs

`web/` is the frontend: its own folder, packages, build and server (`web/serve`, port 8751).
`assistant/` is the backend: an API on port 8750 that serves no page. They meet only over HTTP,
across origins, with one access token — never an import, a shared build, a proxy, or a page the
backend hands out. `./start-docker up` (which `./start` runs) makes the token (random per launch),
gives it to both, and the web app's server writes it into the page; nobody pastes it. They run as
separate containers. See `assistant/CLAUDE.md` for what the split forced (token hand-over, CORS ordering).

## One folder, not one program

The tools share a folder, an install and a start command. **They do not share a process, a
module or a credential**, and keeping it that way is the point of the whole rebuild:

- **No tool imports another.** Tools meet only through the assistant, over MCP, as child
  processes. personal-ai's modules shared one process and quietly came to import each other's
  auth; separate processes are what make that impossible rather than merely discouraged.
- **A crash or a hang stays inside one tool.** docu-ai is TypeScript and could not share a Python
  process anyway; transcription pins every core for hours and must survive a server restart.
- **Credentials stay with their tool** (`~/.config/docu-ai`, `~/.config/mail-ai`, and audiobook's
  Hugging Face token in `audiobook/.env`, which is not Shelby's `.env`). The assistant
  holds only its own model login, and reads a tool's health from how its calls went, never from
  its token files.
- **Every tool still runs alone.** Its wrappers use the tool's own `.venv` if it has one, and
  Shelby's `../.venv` otherwise (audiobook has no such fallback: it needs its own) — so a tool
  checked out by itself works unchanged.

## The shared Python environment

assistant, meet-ai, mail-ai, apply-ai and web-ai share `.venv`. `./setup` installs all five tools'
`requirements.txt` into it and runs `pip check`. **audiobook does not** (2026-10-10): it has its own
`audiobook/.venv`, built from its own pinned `requirements.txt`, because torch, Docling and Pocket
TTS are 1.9 GB that nothing else uses (the shared one is 696 MB) and torch must come from PyTorch's
CPU index, not PyPI's CUDA build. It was the weight and the index, not a version conflict — they
shared only fastapi, uvicorn, starlette, numpy, pydantic and huggingface_hub, at patch-level
differences. `audiobook/mcp` prefers its own `.venv` and does not fall back to Shelby's.

**A pin that conflicts across tools is a
decision, not a merge accident**: if two tools need different versions of one package, the
answer is that tool getting its own `.venv` again (its wrappers already prefer one), never a
loosened pin.

Measured when Shelby was formed (2026-09-27): the three tools pinned only `anthropic` in
common, at the same version; installed transitive deps differed only by patch (`idna`,
`protobuf`). 696 MB shared versus ~900 MB across three environments.

## Tailoring a CV: the checks that run before the draft is saved (2026-10-15)

Asked to tailor a CV or write a cover letter, the assistant now runs `apply-ai` first, then drafts, then builds
with a page target. Three tools carry it, each in its own folder and none importing another; the procedure is
in their tool descriptions, not in the assistant's prompt:

- **apply-ai** (`requirements`, `claims`; reads only): every requirement of the posting against what the user's
  own material shows, the gaps asked about in one message before drafting; then every figure, overstating word,
  tool, language, degree and name in the draft traced to a source line, and any limit the source put on a claim
  noticed when a draft drops it; since 2026-10-30 also the email body, and a claim that code is private set against
  the addresses web-ai found public (the user's own CV said "private" when most were public). Rules and the
  failures behind them: `apply-ai/CLAUDE.md`.
- **docu-ai** (`build` returns `layout`; `layout`, `info`, `trash`): the page count and a warning for a heading
  stranded at a page foot, a page target missed or a stray last page, read from the PDF Docs exports; a gated
  `trash` for the Doc a rebuild replaces. `docu-ai/CLAUDE.md` → "Layout".
- **assistant**: confirmed answers go to memory with `remember` and come back as `facts`; every draft it writes is
  marked `.draft` and is never counted as the user's material; one request may take up to 30 model rounds
  (`MAX_TOOL_ROUNDS`), because checking, fixing, trimming and rebuilding is that many.

The check is advisory: nothing stops a model skipping it, and it cannot tell that a sentence is true. The
person approving the draft is still the last check. Verified through the real chat on two real postings.

## The interface (`web/`)

Designed phone-first: sidebar, rail or bottom tab bar by width; light, dark or follow the system; charts
drawn from the audit log and the tools' own status. **`web/DESIGN.md` is the rulebook** — tokens only (never
a literal colour, size or duration), a fixed colour per tool, status colour only for status and always with
an icon and a word, every chart with a table view, motion tokenised and off under reduced motion. Three
habits that came out of building it:

- **Look at it, at three sizes, in both themes, and run axe.** Screenshots at 390×844, 820×1180 and
  1440×900; `document.documentElement.scrollWidth <= innerWidth` at 390; an axe-core pass over every page.
  Axe found real contrast failures a screenshot never would (the muted text token missed 4.5:1 on grey chips).
- **Test the logic that is easy to get quietly wrong.** `npm test` covers the audit-log arithmetic (local
  days, month boundaries, medians) and the scales; it caught a chart axis that would have read 0 / 0.5 / 1
  for a day with one action. Charts show only what the tools returned; a quiet week is a quiet chart.
- **A dev server against the container backend needs its origin allowed**: compose lists only 8751 and the
  Tailscale name, so add `http://127.0.0.1:5173` to `ASSISTANT_ORIGINS` in a throwaway override (see
  `web/README.md`), and put it back (`./start-docker up`) when done. In a headless browser, a clipped
  screenshot resizes the viewport and cancels a hover: capture with `captureBeyondViewport: false`.

## In containers (`start-docker`, `compose.yaml`, `docker/`)

Shelby also runs in Docker, which is how it is reached from a phone or another computer (Tailscale;
`README.md` has the steps). The rules:

- **One backend image holds the backend and every tool; the web app is a second image.** The tools are
  the backend's own child processes over MCP on stdio, and a container boundary is not a reason to
  change that. The web app stays a separate program with its own image. `init: true` is not optional:
  detached renders and transcriptions are reparented to PID 1, which must reap them.
- **An NVIDIA card is used when there is one, and only then (2026-10-31).** `./start-docker` adds
  `compose.nvidia.yaml` (the image built with `GPU=nvidia`, the card handed to the backend) when `nvidia-smi`
  answers and Docker has NVIDIA's runtime; a card Docker cannot reach is said once and Shelby runs on the
  CPU. `./setup` decides the same way for the host's environments. `SHELBY_GPU=cpu|nvidia` overrides both. The
  image carries no CUDA of its own: the driver is the host's, the rest pip packages (`meet-ai` and `audiobook`
  `requirements-nvidia.txt`), and the code picks the device at run time, so a CPU machine's image and
  behaviour are what they were. Never run on a GPU here (the laptop has none PyTorch can use): the package
  sets were resolved, the detection was run against stand-ins, and the CPU path was run for real.
- **All state is in `./data`** (git-ignored, owned by you, not by Docker's root): each tool's path comes
  from an environment variable in `compose.yaml`, which is Shelby's own rule that paths are injected.
  audiobook is the exception, because it reads no setting for where its folders are, so the image
  symlinks `voices`, `output`, `.cache` and `.env` into `/data/audiobook`. `start-docker import` copies
  what the host folders already hold, once, never overwriting.
  The database is state too: `./data/postgres`, a `postgres:16-alpine` container run as your uid, with no
  published port, which only the backend reaches. It holds the assistant's memory, audit log and sign-in
  sessions (`assistant/CLAUDE.md` → "The database"); the tools keep their own files and never see it.
- **Nothing is published beyond `127.0.0.1`**, and the backend and web app listen on `0.0.0.0` *inside*
  the container network only (`ASSISTANT_HOST`, `WEB_HOST`). That is the one deliberate relaxation of
  "bind to localhost"; the token and the Host check still apply to everything. Reaching it from
  elsewhere is the Tailscale sidecar's job (`--tailscale`), not a published port's.
- **Hosts are exact names** (`ASSISTANT_HOSTS`, shared by both programs; `SHELBY_HOST` in `.env`), never a
  pattern or `*`: the Host check is what stops a hostile page pointing its own name at this machine.
- **No source is mounted over the image.** A change to the code is live after `./start-docker up`
  (layer-cached, so only what changed is rebuilt). The images hold no credentials; they come in as the
  `./data` and `~/.aws` volumes.
- **A container restart interrupts a running render; a process restart does not.** On the host a job
  outlives the backend because it is a detached process nobody owns. In a container every process dies
  with the container, so `./start-docker up` (which recreates it) or a `docker compose restart` leaves
  a running render `interrupted` — honestly, and with every spoken sentence kept: start it again and it
  resumes. Verified. Don't deploy while a long render is going.
- **`./test` must pass with no network and an empty model cache**, and it once did not: a meet-ai test
  built the real 1.5 GB Whisper model and passed only because the developer's cache held it. Check it
  clean-room, in the image: `docker run --rm --network none -e HF_HOME=/tmp/empty-hf -e HOME=/tmp/h
  --entrypoint bash shelby-backend -c 'cd meet-ai && ../.venv/bin/python -m pytest tests -q'` (and the
  other tools). `./start-docker test` runs every suite in the image, with docu-ai's corpus mounted
  because one of its tests reads a fixed path in the author's home folder.
- **What was run for real, and what was not:** see `plan.md` ("Built and verified"). The Tailscale
  sidecar needs a tailnet to run against, which cannot be faked.

## The model is optional (2026-10-31)

Only the assistant's chat and meet-ai's notes and minutes call a model. Mail, Meetings (recording, transcribing, reading),
Documents and Audiobooks are buttons on tools that never touch one, so they work with no model login and no key: with the AWS
login dead and no key, every tool answered and Settings said so (`assistant/CLAUDE.md` -> Every login at a glance). A model comes
from an `ANTHROPIC_API_KEY` in `.env` (wins) or the Bedrock profile; Bedrock ends at the end of November. Settings treats "no model
set up" as information, not as something needing attention.

## Settings

`.env` (from `.env.example`, never committed) is read by `./start-docker` and passed to the containers, so
every tool inherits it. It holds only what is genuinely Shelby-wide: the AWS profile and region, the port.
A tool's own paths stay in `assistant/tools.yaml`, the one file that knows every tool exists.

## Working in this repo — rules learned the hard way

- **Run `./publish-check` before every push.** `shelby` is public. It reads the commits GitHub does not have:
  exit 1 is a secret (a key's shape, or a value from this machine's own login files) or a credentials file, and
  the push must not happen; exit 2 is a personal detail not already public (an email, a phone number, a server
  id), to show the user. It never prints a secret whole. Its tests build fakes from pieces, so none is written
  out whole in this repo: keep it that way, or it flags itself. Private words with no shape go in the
  git-ignored `.publish-watch`.
- **Stage by explicit path, never `git add -A`.** `docu-ai/plan.md` carries the user's own
  uncommitted edit; it has been kept out of every commit and must stay out unless they ask.
- **Commit as the user**: this machine has no git identity configured, so use
  `git -c user.name=Philip -c user.email=philip@ayadata.ai commit …`, with the co-author line.
- **Tools are launched once, when the backend starts.** A change to meet-ai, docu-ai or mail-ai
  (or to the backend) is not live until the backend restarts. The web app is different: its
  server serves `web/dist` live, so `cd web && npm run build` updates a running app.
- **Restart with `./start-docker up`**, which recreates only what changed (see "In containers"). To kill a
  process by name, as when a test run leaves a server behind, the brackets matter: an unbracketed pattern such as
  `pkill -f "vite preview"` matches the shell running it and kills that instead. **The pattern must
  not appear anywhere else in the command you run**: the whole command text is the shell's own
  command line, so `pkill -f "vite[ ]preview"` still kills it whenever the same command also
  contains `vite preview` (a heredoc that writes the script counts). Put it in a script file and
  run `bash script` as its own command. Tripped over three times in one session.
- **Drive the chat the way the page does** to test it: the token is in the served page
  (`curl -s http://127.0.0.1:8751/` → `<meta name="assistant-token">`); POST `/api/chat`, poll
  `/api/state` for events and pending approvals, answer with POST `/api/approvals/{id}`. Read a
  pending draft's full `arguments` before approving it — never approve blind.
- **Check the interface in a real browser**: Puppeteer (`puppeteer-core`) against
  `/usr/bin/google-chrome-stable`. Chrome's own headless screenshot flags break on the event
  stream (`assistant/CLAUDE.md`).
- **A live test that builds a Google Doc leaves a real Doc** in the user's Drive: trash it after,
  and delete test uploads from `assistant/uploads/`.
- **A live audiobook test leaves a book's worth of audio** in `audiobook/output/<pdf name>/`, named
  for the PDF — so upload a *copy* under a throwaway name (`zz-test-paper.pdf`), never the real
  book's name, or a test render overwrites the user's finished chapters. Delete the output folder,
  the upload, and the `.corrections.txt` a test leaves beside it. A render is a detached process:
  restarting the backend does not stop it (and the restarted backend sees it), so `pkill` it
  explicitly if a test render must end.
- **Logins lapse: AWS SSO overnight, the Google tokens weekly** (the OAuth app is in "Testing").
  `./auth --check` tells which, without a browser. Settings now can too (2026-10-31): mail-ai and docu-ai
  each offer a read-only `login_status` that asks Google whether *their own* token (the container's copy, the one
  that matters) still works, and the page says "Signed out of Gmail" with the one command, `./auth`; before, it
  judged a tool by its last call, which may be days old. The sidebar's model dot goes red and says "Signed out" the
  same way (`assistant/CLAUDE.md` -> Every login at a glance). Only the user can renew them (`./auth`, needs a browser).
  **The containers hold their own copy of each Google token** (`data/config`), which renewing on the host did
  not touch: on 2026-10-15 every build in the container failed with `invalid_grant` on a token Google had let
  lapse two weeks earlier. `./auth` now copies a login that is good on the host into `data/config` when the
  refresh token differs (`--check` only says so), never the other way and never from a dead login.
- **Done means run for real and looked at.** Unit tests passed on every change Shelby has had;
  the real runs are what found the dropped quotes, the 8-page minutes, the truncated CV draft and
  the cut-off approval preview. Build it, run it, open the output.

## History

Each tool was its own repo until 2026-09-27; their histories were rewritten into these folders
and merged, so `git log -- docu-ai/src/...` and `git blame` show the real commits. audiobook joined
the same way on 2026-10-10 (four commits, `98c60e3`), with its own web app removed afterwards.

It was called `suite` until 2026-11-07, when the user renamed it Shelby, everything: the folder (`~/Documents/shelby`),
the GitHub repo (`Philips-DR/shelby`; the old address forwards), Docker's project, images, containers and the backend's
user, the database and its user, the `SHELBY_*` settings, and the Tailscale machine (`shelby.<tailnet>.ts.net`).
"Test suite" and "a suite of tools" are plain English and were left alone. Older commits and notes say `suite`.
