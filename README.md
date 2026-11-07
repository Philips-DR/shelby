# Shelby

My personal AI assistant and the tools it runs, in one folder, started with one command.

**My design, built with Claude Code as a pair programmer.** I defined the system architecture, the rules every
part must follow and the features myself, and reviewed and tested every change. The architecture is below; the
rules are in [`CLAUDE.md`](CLAUDE.md) and each tool's own `CLAUDE.md`, and the decisions, with the reasons for
each, are in [`plan.md`](plan.md).

Where it stands and what comes next: [`plan.md`](plan.md). Rules for working on it:
[`CLAUDE.md`](CLAUDE.md).

| Folder | What it does |
|---|---|
| `web/` | The web app you open: chat and buttons, uploads of audio, markdown, PDFs. A separate program that calls the backend's API. |
| `assistant/` | The backend. Starts the tools below, calls them for you, asks before anything that writes. |
| `meet-ai/` | Records meetings, transcribes them on this machine, writes notes and minutes that cite the recording. |
| `docu-ai/` | Turns markdown into a properly formatted Google Doc. |
| `mail-ai/` | Reads, searches, drafts and sends Gmail. |
| `apply-ai/` | Checks for a job application: a posting's requirements against what your own material shows, and a draft's claims against what you have actually written. Reads only. |
| `web-ai/` | Reads a web page (its text and links), checks that a link answers, and asks GitHub what a stranger can see. Reads only; refuses anything that is not on the public internet. |
| `audiobook/` | Turns a PDF into an audiobook, read in a voice cloned from a short recording. Runs entirely on this computer. |

## Architecture

Eight programs, not one. They share a folder, an install and a start command — nothing else.

- **The web app and the backend are separate programs.** `web/` is a frontend: its own build, its
  own server, port 8751. `assistant/` is an API with no page of its own, port 8750. They only ever
  meet over HTTP, across origins — never an import, a shared build, or a page one hands the other.
  `./start` makes a fresh access token each launch and gives it to both; the web app's server writes
  it into the page as it serves it, so nothing is pasted by hand.
- **The backend starts the six tools as its own child processes**, talking to each over MCP on
  stdio — the same protocol a model uses to call them. `meet-ai`, `docu-ai`, `mail-ai`, `apply-ai`, `web-ai` and
  `audiobook` each also work standalone, from their own folder, with nothing else running.
- **No tool imports another, and no tool imports the backend.** They meet only through the
  backend's tool calls. A crash or a multi-hour transcription in one tool cannot take down another,
  or the backend, or the web app.
- **Every write is gated.** The backend classifies a tool's own call as read-only or not (from the
  tool's own annotation, never a list it keeps itself) and asks a person before anything else runs —
  sending mail, building a Doc, changing a recording. A poll or a read needs no approval; a write
  does, every time, and every call is written to an audit log.
- **Credentials stay with their tool.** docu-ai's Google login and mail-ai's Gmail login live in
  their own `~/.config` folders; the backend holds only its own model login and reads a tool's
  health from how its calls went, never from its token files.

The rules behind each of these, and why they're rules, are in [`CLAUDE.md`](CLAUDE.md); each
tool's own architecture — its layers, its verified API facts, its gotchas — is in that tool's own
`CLAUDE.md`.

## First time

```bash
./setup          # the Python environments, Node packages, the web app, speaker models
```

Then `./auth`: it checks every login — AWS for the model, Google for docu-ai, Gmail for
mail-ai (plus the wider drafting token, once made with `./auth mail-compose`) — and opens a
browser only for the ones that are dead. `./auth --check` reports without signing in. Settings
go in `.env`, which `./setup` creates from `.env.example`.

## Every day

```bash
./start          # then open http://127.0.0.1:8751/
```

One command, three containers: the backend (API on port 8750, which launches the tools as its own
children), the web app (port 8751) and the database (PostgreSQL, which only the backend can reach). It
checks your logins first (`./auth`), then runs `./start-docker up`, so anything you add goes to that.
The containers keep running until `./start-docker down`. A transcription or recording in progress is
built to outlive a restart and is picked up again next time.

Nothing to sign in to: every start makes a fresh access token, gives it to both programs, and the web
app's server puts it in the page. A tab left open across a restart picks up the new one by itself.
**Buttons → Settings** shows whether the model login, the network and each tool are working.

What the assistant remembers about you, its history of every call, and sign-in sessions are in the
database (`./data/postgres`). The first start after upgrading from the files moves `memory.json` and
`audit.jsonl` into it once and renames them to `*.imported`; nothing is deleted.

Each half can still run alone for development: `assistant/assistant-web` for the backend (with no
`DATABASE_URL` it keeps memory and history in files again), `web/serve` for the app (or
`cd web && npm run dev` for live reload). Run that way without a shared `ASSISTANT_TOKEN`, the app
asks once for the token the backend prints.

```bash
./test           # every tool's tests; none needs a login, a model or the network
./publish-check  # before a push: what GitHub does not have yet, checked for secrets and personal details
```

## When you power on the laptop

**There is nothing to start.** Docker itself starts at boot and brings Shelby back with it: every
container (database, backend, web, and Tailscale if you use it) is set to
`restart: unless-stopped`, so they return unless you stopped them yourself with `./start-docker down`.
They come back with the same access token, so a tab or phone that already had the page open keeps
working. Give it a minute after logging in, then open `http://127.0.0.1:8751/` (or the `shelby…ts.net`
address from your phone).

1. Check once that Docker starts at boot: `systemctl is-enabled docker` should print `enabled`
   (if not, `sudo systemctl enable docker`).
2. **The model**: put an `ANTHROPIC_API_KEY` in `.env` and run `./start-docker up`: no daily login, and it wins over
   Bedrock when both are set. Settings asks Anthropic whether the key, and the model it will use, are accepted, and says
   what to change if not (`SHELBY_MODEL` in `.env` names another model). Only Chat and meeting notes need a model; every
   other page works without one. **With Bedrock instead, renew the AWS login each morning**: it lapses overnight, and
   until then the assistant cannot think (Settings shows "Signed out"). Run `./auth`, or just
   `aws sso login --profile ayadata-bedrock`. The Google logins last about a week.
3. If it is not there: `./start-docker status` shows what is running; `./start-docker up` starts it.

**It is only reachable while the laptop is awake.** A laptop that sleeps (lid closed, idle) is off the
network, so your phone cannot reach Shelby until it wakes. For all-day access from your phone, keep it
awake and plugged in (set the laptop not to suspend while on AC power).

## In containers, and from your phone

Shelby runs in Docker, which is also how it reaches your phone and other computers.

```bash
./start-docker up              # build, start, say where it is: http://127.0.0.1:8751/
./start-docker up --tailscale  # the same, plus a private HTTPS address for your other devices
./start-docker import          # once: copy this folder's existing data into ./data
./start-docker down | logs | status | test
```

Two images, as on the host: **backend** (the API *and* every tool, which are its child processes) and
**web** (the web app, still a separate program). All state lives in `./data`; the model's AWS login
is read from `~/.aws`. Nothing is published beyond `127.0.0.1`. `up --audio` lets meet-ai record from
this computer's microphone.

**On a computer with an NVIDIA card**, transcribing (Whisper), speaking (Pocket TTS) and reading books
(Docling) run on the card, found by itself: `./setup` and `./start-docker up` see the card's driver and
install NVIDIA's builds of their libraries (about 4 GB more to download). The containers also need the
[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html);
`./start-docker up` says so when it is missing, and runs on the CPU until then. `SHELBY_GPU=cpu` in `.env`
keeps everything on the CPU. Any other computer runs on the CPU, as before.

**From your phone or another computer, over Tailscale.** Tailscale is a private network between
your own devices: only devices signed in to your account can reach Shelby, and to everyone else
it does not exist.

1. Make a free Tailscale account (tailscale.com) and install the app on each device you want to
   reach Shelby *from* — your phone, other computers — signed in to that account. This computer
   does not need it: Shelby's own Tailscale container joins your network as a machine called
   `shelby`. In the admin console (login.tailscale.com/admin → DNS), make sure **MagicDNS** is on and
   enable **HTTPS Certificates**.
2. `./start-docker up --tailscale`. The first time, `./start-docker logs tailscale` prints a
   sign-in link for the new `shelby` machine (or put a `TS_AUTHKEY` in `.env` and nothing is asked).
3. The admin console now lists `shelby` with a name like `shelby.tail1234.ts.net`. Put it in `.env` as
   `SHELBY_HOST=shelby.tail1234.ts.net` and run `./start-docker up --tailscale` again.
4. On your phone, with Tailscale on: open `https://shelby.tail1234.ts.net/`.

If it does not open, run `./start-docker tailscale`: it shows the machine's name, whether HTTPS
certificates are on, and what is being served, and says what to change. (The usual cause is step 1's
**HTTPS Certificates** not being enabled; Tailscale then drops the HTTPS address without any error.)

The tailnet is the first lock and the page's access token the second, and the token is handed to
whatever can open the page: keep the tailnet to your own devices (or restrict it with Tailscale ACLs)
until signing in with Google replaces it. **Logins** still happen on a computer with a browser
(`./auth`); `./start-docker import` copies this folder's Google tokens into `./data/config` once, `./auth` keeps them in
step afterwards (a container's copy lapses on its own otherwise), and on a
server you would copy `~/.config/docu-ai` and `~/.config/mail-ai` there yourself. The AWS login lapses
overnight and is renewed on the host (`aws sso login`).

## On a server (renewing its logins)

A server has no browser and no AWS SSO, so it cannot renew a login. `./renew-secrets` does it from
this computer, over ssh: it runs `./auth` for whatever has lapsed, sends the server temporary AWS
credentials for the model and the Google tokens, then asks the server's backend who it now is. Secrets
go on ssh's standard input, never in a command line.

For a server reached through SSM, give it an alias in `~/.ssh/config`:

```
Host shelby-server
  HostName i-0123456789abcdef0            # the instance id
  User ubuntu                             # or ec2-user
  IdentityFile ~/.ssh/<key>
  ProxyCommand sh -c "AWS_PROFILE=<a profile allowed to start sessions> AWS_REGION=us-east-1 aws ssm start-session --target %h --document-name AWS-StartSSHSession --parameters 'portNumber=%p'"
```

Then `SHELBY_REMOTE=shelby-server` in `.env` (and `SHELBY_REMOTE_DIR`, `SHELBY_REMOTE_AWS_DIR`; see
`.env.example`), and on the server set `AWS_CONFIG_DIR` in its `.env` to the full path of the AWS
credentials folder, so `~/.aws` there is never touched.

```bash
./renew-secrets --first    # once: also send the Google client files and audiobook's token
./renew-secrets            # each time the logins lapse
./renew-secrets --check    # what the server holds, and when the AWS credentials run out
```

SSO credentials last as long as the permission set's session (about 8 hours on this account), so
the model's login lapses every few hours instead of overnight; an instance role would end that, and
needs someone who administers the account to attach it. The backend reads the credentials file on every
model call, so nothing is restarted afterwards. The Google tokens lapse weekly while the OAuth app is
in "Testing" (`./auth` renews them, and so does this).

## Each tool still stands alone

Every tool keeps its own command line, tests and rules (`CLAUDE.md`, `plan.md`), and works
from its own folder with the assistant not running: `meet-ai/notes`, `mail-ai/mail`, `apply-ai/apply`, `web-ai/web`,
`cd docu-ai && npm start`, `cd audiobook && .venv/bin/python -m audiobook preview BOOK.pdf`. See each
folder's README or `CLAUDE.md`.

**Audiobooks** are a long job: reading a book takes minutes and rendering one takes hours. Both run in
the background, survive restarting the backend, and show their progress under **Buttons → Audiobooks**.
audiobook is the one tool with its own Python environment (`audiobook/.venv`, ~1.9 GB), and its Hugging
Face token lives in `audiobook/.env`.
