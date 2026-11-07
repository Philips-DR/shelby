# assistant

Talk to your tools. The assistant classifies a request, calls a tool, gates anything that
writes, and logs what happened.

It owns no domain logic. It does not know what a timeline is, what a span is, or that
Google Docs indexes are UTF-16 code units. Every hard thing lives inside a tool, behind an
MCP door, where it is tested and cannot drift.

```bash
./assistant-cli --list                      # what tools exist, and which of them write
./assistant-cli "write up the meeting"      # one-shot
./assistant-cli                             # chat loop
```

## In a browser

```bash
./assistant-web                             # the API, on http://127.0.0.1:8750/
../web/serve                                # the web app, on http://127.0.0.1:8751/
```

The web app is a separate program in `../web` (Shelby's `./start` runs both). This server
is the API only and serves no page.

**Chat** and **Buttons** are a toggle at the top. Buttons mode is a Meetings panel today —
record, transcribe with live progress, write notes — calling the same tools the model calls,
with no model involved. An approval the model is waiting on follows you between modes: inline
in chat, a banner in buttons mode, and a badge on the Chat tab. The URL carries the mode
(`#chat`, `#buttons`), so either view can be bookmarked.

One long-running process: the tools are launched once and held open, and a browser talks to
it. Chat and buttons are two views of **one** system — anything you change with a button is
handed to the model with your next message, and anything the model does streams to every open
view as it happens.

The chat gate works the same here as in the terminal, except that a turn *suspends* on an
approval card instead of blocking on a prompt, and resumes when you answer it.

**It binds to 127.0.0.1 only, and every API request needs a token issued at launch.** The
server prints it on start; the web app asks for it once and the browser keeps it until the
next restart. Localhost alone is not enough: any site open in another tab can make your
browser send a request to localhost, and this process can send email as you. The token is
what that site cannot know. Requests whose `Host` is not localhost are refused too, which
closes DNS rebinding, and only the web app's own origins may read responses.

## How it reaches the tools

Every tool is a child process speaking MCP over stdio. None is a network service, none has
to be running beforehand, and each is equally usable from its own terminal with the
assistant absent. `tools.yaml` is the only file in the system that knows more than one of
them exists:

```yaml
servers:
  - name: meet-ai
    command: ${MEET_AI_HOME:-../meet-ai}/mcp
    cwd: ${MEET_AI_HOME:-../meet-ai}
```

Paths take `~`, `$VAR` and `${VAR:-fallback}`, and a **relative path resolves against
`tools.yaml` itself**, not the working directory — so the defaults assume the tools are
siblings of this repository and work on a fresh machine unedited. An unset variable with no
fallback is an error rather than a literal, because a child process launched with a
nonsense path fails nowhere near its cause. A bare command like `npm` is left for `PATH`
to find.

`env` on a server entry is where that tool's paths and credentials are injected. A tool
never discovers either for itself.

## The gate

Anything that writes is shown to you with its exact arguments before it runs:

```
  run this?
  meet_ai.generate_notes
  {
    "timeline": ".../slice.timeline.json"
  }
  [y/N]
```

The decision of what needs approval comes from each tool's own `readOnlyHint` annotation,
not from a list kept here — a list would need updating every time a tool gained an
operation, and would be wrong in between. **A tool that declares nothing is treated as
writing.** Failing closed is the only safe default.

Anything that is not an explicit `y`/`yes` is a decline, including `ok` and `sure`. A gate
that guesses at intent is not a gate.

### When arguments are not enough to approve

Some calls cannot be judged from their arguments. `send_draft(draft_id, confirmation)` is
two opaque strings — no recipient, no subject, not a word of the body. Approving that is
not approval.

So a tool may point at the read-only tool that renders its effect, in MCP's `_meta`:

```json
{"approval": {"preview_tool": "review_draft",
              "argument_map": {"draft_id": "draft_id"},
              "field": "rendered"}}
```

The gate calls it before asking, and shows that instead:

```
  run this?
  mail_ai.send_draft

  To: kwame@example.com
  Subject: Re: Claims review

  Tuesday works for me.

  { "draft_id": "r-8891", "confirmation": "a5c8bae607a53430" }
  [y/N]
```

The assistant never learns what an email is — only how to ask. Three rules make it safe:

- **The named tool must be read-only.** A "preview" that could act would be a hole rather
  than a help — a tool could name a destructive preview and have it run before anyone
  approved anything.
- **A declared preview that fails is said out loud.** Falling back silently to raw arguments
  looks identical to a tool that never offered one, and the person approves believing they
  have seen it.
- **Preview text is sanitised.** It is content the assistant did not write — an email body —
  printed directly above a yes/no prompt. Control characters are stripped and the length is
  capped, so it cannot repaint the screen, hide the real recipient, or paint a convincing
  fake prompt.

The model is told not to ask permission in prose, because the gate already does that. Both
at once makes two gates and a conversation that stalls waiting for an answer it was never
going to act on.

## The audit log

One JSON line per tool call, appended to `audit.jsonl`: what ran, with what arguments, how
long it took, and whether it worked. With tools behind MCP each call is a discrete typed
event rather than a function call buried in a process, which is what makes "what did it get
wrong this week" answerable from the log alone.

```
meet_ai__generate_notes   ok       7194ms
docu_ai__build            failed   invalid_grant
```

A tool that reports its own failure is recorded as a failure — see CLAUDE.md for why that
sentence had to be earned.

## Memory

A small JSON file of facts, all of which go into the system prompt. It is plain text and
safe to edit by hand.

```bash
./assistant-cli "remember that Kwame leads the claims project"
./assistant-cli --no-memory "..."     # load nothing, record nothing
```

Not pgvector, and not yet. Retrieval only earns its infrastructure once there is more than
fits in a prompt; at personal scale, sending every fact is simpler than top-k similarity
*and* strictly more accurate, because nothing relevant can be missed. `MemoryStore.relevant()`
is the seam a vector store would sit behind when that stops being true.

Recording the same kind and subject twice corrects the earlier note rather than adding a
second one — two contradictory facts in one prompt is worse than either alone.

Memory is framed to the model as background rather than instruction. A remembered line is
something you wrote once; it should not outrank what you are saying now.

### The lexicon

Facts of kind `spelling` become a lexicon that meet-ai uses to fix names and jargon it
mis-hears:

```
remember  kind=spelling  subject="round robin"  content="round robinson, round robins"
```

At the start of each session that lexicon is written to `lexicon.json` and its path is put
in the prompt, so the assistant can hand it to any tool that takes one. meet-ai still knows
nothing about a memory store — it takes a lexicon as an argument, which is what keeps it
usable on its own.

Both memory tools pass through the approval gate like any other write. That is deliberate:
you should see what the assistant writes down about you, at the moment it decides to.

## Where the model comes from

Bedrock by default, or the Anthropic API when `ANTHROPIC_API_KEY` is set; `--provider`
forces either. Credentials are read from the environment in exactly one place and passed
down.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install pytest        # tests only
```

Then point `tools.yaml` at your tools.

## Testing

```bash
.venv/bin/python -m pytest tests/ -q
```

No model, no child process, no network. The approval gate has the most tests, because it is
the only thing standing between a model's intention and a write, and it must not depend on
a model behaving well in order to work.
