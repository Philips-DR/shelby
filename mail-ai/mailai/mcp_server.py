"""mail-ai's second front door: the same operations the CLI exposes, reachable by a model.

Both doors sit directly on operations.py; neither wraps the other.

Drafting and sending are registered **only when the caller supplies a compose credential**.
A server built without one does not merely refuse those tools, it does not have them: a
model cannot call a tool that was never advertised, which is a stronger guarantee than a
tool that checks a flag.

When they are registered, `send_draft` takes a draft id and a confirmation and nothing
else. There is no tool on this door that accepts message content and sends it, so
"compose and send in one step" is not a mistake a caller can make.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import NotRequired, TypedDict

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from mailai.auth import AuthConfig, check_login
from mailai.attach import read_attachment
from mailai.compose import Attachment, BadAttachment
from mailai.operations import (
    as_dict,
    discard_draft,
    draft_new,
    draft_reply,
    list_drafts,
    list_threads,
    read_thread,
    review_draft,
    search_mail,
    send_draft,
    status,
    sync_mailbox,
)

VERSION = "0.2.0"

# Worst first, so the state of several logins is the one that most needs a person.
LOGIN_ORDER = ["dead", "missing", "unknown", "ok"]


def approval_preview(preview_tool: str, argument_map: dict[str, str], field: str | None = None) -> dict:
    """Declare how a caller should show this tool's effect before approving it.

    A destructive tool whose arguments are opaque identifiers cannot be approved
    meaningfully from its arguments alone: "send_draft(draft_id, confirmation)" says
    nothing about who the mail is going to or what it says. This points a caller at the
    read-only tool that renders the effect, so the approval prompt can show the email
    rather than two hashes.

    The contract, carried in MCP's `_meta`:

        preview_tool   a READ-ONLY tool on this same server
        argument_map   {preview tool's parameter: this tool's parameter}
        field          which key of the preview's JSON result to display, if not all of it

    A caller is free to ignore this. A caller that honours it must still verify the named
    tool is read-only, because a "preview" that acted would be a hole rather than a help.
    """
    return {
        "approval": {
            "preview_tool": preview_tool,
            "argument_map": argument_map,
            **({"field": field} if field else {}),
        }
    }


class AttachmentArgument(TypedDict):
    """One file for `draft_new`: either `path`, a file in the folder this server may attach from (what
    docu_ai__save_export returns), or `filename` with `data`, its bytes as standard base64. `filename`
    renames a file given by path; `mime_type` is worked out from the name when left out."""

    path: NotRequired[str]
    filename: NotRequired[str]
    data: NotRequired[str]
    mime_type: NotRequired[str]


@dataclass(frozen=True)
class ServerPaths:
    """Where this server may read and write. Supplied by the caller, never assumed."""

    store: Path
    # The one folder a file may be attached from by path (docu-ai saves exports there). None: no file by path.
    attach_root: Path | None = None


def _failed(error: Exception) -> dict:
    return {"error": str(error)}


def _attachment(argument: AttachmentArgument, root: Path | None) -> Attachment:
    """One file, by its bytes or by its path, never both: a file given twice is a question of which is meant."""
    if ("data" in argument) == ("path" in argument):
        raise BadAttachment("give each attachment either `data` (its bytes as base64) or `path`, not both")
    if "path" in argument:
        return read_attachment(argument["path"], root, argument.get("filename", ""), argument.get("mime_type", ""))
    return Attachment.from_base64(argument.get("filename", ""), argument["data"], argument.get("mime_type", ""))


def create_mail_ai_server(paths: ServerPaths, auth: AuthConfig,
                          compose_auth: AuthConfig | None = None) -> MCPServer:
    """`compose_auth` is what turns drafting on. Omit it and this door cannot draft or send."""
    server = MCPServer(name="mail-ai", version=VERSION)

    @server.tool(
        name="status",
        title="What the local mailbox holds",
        description=(
            "How many messages and threads are stored, how recent they are, whether a "
            "sync watermark exists, and when the last sync finished (`synced_at`). Reads the "
            "local file only — no network, no credentials. The safe thing to check first."
        ),
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
    )
    def _status() -> dict:
        try:
            return as_dict(status(paths.store))
        except (OSError, ValueError) as error:
            return _failed(error)

    @server.tool(
        name="login_status",
        title="Check the Gmail login",
        description=(
            "Is the Gmail login still accepted? Asks Google once whether each saved login (reading, and drafting "
            "when it is on) still works. `state` is the worst of them: ok; dead (Google refuses it, so it must be "
            "signed in again); missing (never signed in); unknown (Google could not be reached, so nothing is known). "
            "Changes nothing: no file is written and no mail is touched."
        ),
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
    )
    def _login_status() -> dict:
        named = [("Reading", auth)] + ([("Drafting", compose_auth)] if compose_auth is not None else [])
        checks = [(name, check_login(config)) for name, config in named]
        worst = min((check.state for _, check in checks), key=LOGIN_ORDER.index)
        return {
            "service": "Gmail",
            "state": worst,
            "detail": "; ".join(f"{name}: {check.detail or check.state}" for name, check in checks if check.state != "ok"),
            "logins": [{"name": name, "state": check.state, "detail": check.detail} for name, check in checks],
        }

    @server.tool(
        name="sync",
        title="Bring the local mailbox level with Gmail",
        description=(
            "Fetch new and changed mail into the local store. Incremental after the first "
            "run; falls back to a full resync by itself if the watermark has expired, "
            "which happens after about a week. Writes only to the local mailbox file and "
            "changes nothing in Gmail."
        ),
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=True,
            open_world_hint=True,
        ),
    )
    def _sync(label: str = "INBOX,SENT", limit: int | None = None) -> dict:
        try:
            targets = ([None] if label.lower() == "all"
                       else [p.strip() for p in label.split(",") if p.strip()])
            return as_dict(sync_mailbox(auth, paths.store, labels=targets, limit=limit))
        except Exception as error:
            return _failed(error)

    @server.tool(
        name="list_threads",
        title="Recent threads",
        description=(
            "The most recent conversations, newest first, with who started each and how "
            "many messages it holds. Offline: reads only what a previous sync stored."
        ),
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
    )
    def _list_threads(limit: int = 20) -> dict:
        try:
            return {"threads": [as_dict(t) for t in list_threads(paths.store, limit=limit)]}
        except (OSError, ValueError) as error:
            return _failed(error)

    @server.tool(
        name="read_thread",
        title="Read one thread",
        description=(
            "Every message in a thread, oldest first, with each one's quoted history "
            "already removed — so a ten-message thread reads as ten messages rather "
            "than ten copies of the first. Offline."
        ),
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
    )
    def _read_thread(thread_id: str) -> dict:
        try:
            return as_dict(read_thread(paths.store, thread_id))
        except (OSError, ValueError) as error:
            return _failed(error)

    @server.tool(
        name="search",
        title="Search the local mailbox",
        description=(
            "Find messages whose subject, body or sender contains the given text. Offline, "
            "over what a previous sync stored — not a Gmail search."
        ),
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
    )
    def _search(text: str, limit: int = 20) -> dict:
        try:
            return {"messages": search_mail(paths.store, text, limit=limit)}
        except (OSError, ValueError) as error:
            return _failed(error)

    if compose_auth is None:
        return server

    @server.tool(
        name="draft_reply",
        title="Draft a reply in a thread",
        description=(
            "Write a reply to an existing thread and leave it as a draft. Sends nothing. "
            "The recipient, subject and threading headers come from what was synced, so "
            "the reply threads correctly in clients other than Gmail too. Returns a draft "
            "id and a confirmation; read it back with review_draft before sending."
        ),
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, open_world_hint=True
        ),
    )
    def _draft_reply(thread_id: str, body: str) -> dict:
        try:
            return as_dict(draft_reply(compose_auth, paths.store, thread_id, body))
        except Exception as error:
            return _failed(error)

    @server.tool(
        name="draft_new",
        title="Write a new draft",
        description=(
            "Compose a new message and leave it as a draft. Sends nothing. Returns a draft "
            "id and a confirmation; read it back with review_draft before sending. "
            "`attachments` is a list of files. To attach a CV or cover letter, save each one "
            "with docu_ai__save_export first and give its returned path here as {path}; only "
            "files in the folder that tool saves to are accepted. Do not copy a file's bytes "
            "yourself: a Word document is far more text than you can carry. A small file you "
            "already hold can instead be {filename, data, mime_type?}, data being standard "
            "base64. Files may come to 10 MB in all. Every file is listed by review_draft and "
            "covered by the confirmation: changing one afterwards invalidates it. A file with "
            "no content, a path outside that folder or a link, a name with a slash or a hidden "
            "character, or data that is not valid base64 is refused and no draft is made."
        ),
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, open_world_hint=True
        ),
    )
    def _draft_new(to: str, subject: str, body: str, cc: str = "",
                   attachments: list[AttachmentArgument] | None = None) -> dict:
        try:
            # Built here, before anything reaches Gmail, so a refused file makes no draft.
            files = [_attachment(a, paths.attach_root) for a in attachments or []]
            return as_dict(draft_new(compose_auth, to, subject, body, cc=cc, attachments=files))
        except Exception as error:
            return _failed(error)

    @server.tool(
        name="list_drafts",
        title="List drafts",
        description=(
            "The drafts in Gmail: each one's id, who it is to, its subject, its first words and when it "
            "was last changed, and the thread it belongs to. Sends nothing."
        ),
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
    )
    def _list_drafts(limit: int = 25) -> dict:
        try:
            return {"drafts": list_drafts(compose_auth, limit=limit)}
        except Exception as error:
            return _failed(error)

    @server.tool(
        name="review_draft",
        title="Read a draft, and get the token that would send it",
        description=(
            "Show a draft exactly as it currently stands, with the confirmation that "
            "authorises sending that exact content. Editing the draft afterwards "
            "invalidates the confirmation, so a draft can only be sent in the state it was "
            "last read in. Sends nothing."
        ),
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
    )
    def _review_draft(draft_id: str) -> dict:
        try:
            return as_dict(review_draft(compose_auth, draft_id))
        except Exception as error:
            return _failed(error)

    @server.tool(
        name="send_draft",
        title="Send a reviewed draft",
        description=(
            "Send an existing draft. THIS LEAVES THE MACHINE AND CANNOT BE UNDONE. "
            "Requires the confirmation from review_draft, and refuses if the draft has "
            "changed since. There is deliberately no way to pass message content here: to "
            "send something, draft it, review it, then send that draft."
        ),
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=False,
            open_world_hint=True,
        ),
        # Without this, approving a send means approving {draft_id, confirmation} -- two
        # opaque strings. The gate in sending.py guarantees the draft is the one SOMEBODY
        # read; this is what lets the person actually approving it be that somebody.
        meta=approval_preview("review_draft", {"draft_id": "draft_id"}, field="rendered"),
    )
    def _send_draft(draft_id: str, confirmation: str) -> dict:
        try:
            return as_dict(send_draft(compose_auth, draft_id, confirmation))
        except Exception as error:
            return _failed(error)

    @server.tool(
        name="discard_draft",
        title="Delete a draft",
        description="Permanently delete a draft. Sends nothing, but cannot be undone.",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, open_world_hint=True
        ),
        meta=approval_preview("review_draft", {"draft_id": "draft_id"}, field="rendered"),
    )
    def _discard_draft(draft_id: str) -> dict:
        try:
            return discard_draft(compose_auth, draft_id)
        except Exception as error:
            return _failed(error)

    return server


def main() -> None:
    """The one place this entry point reaches for the environment, named so it is visible."""
    root = Path(__file__).resolve().parent.parent
    attach_root = os.environ.get("MAIL_AI_ATTACH_ROOT")
    paths = ServerPaths(store=Path(os.environ.get("MAIL_AI_STORE", root / "mailbox.sqlite3")),
                        attach_root=Path(attach_root) if attach_root else None)

    # Drafting is off unless asked for, and asking is a deliberate act: MAIL_AI_COMPOSE=1
    # in the server's own environment. Without it this door has no sending tool at all.
    compose = AuthConfig.from_environment(compose=True) if os.environ.get(
        "MAIL_AI_COMPOSE"
    ) else None
    create_mail_ai_server(paths, AuthConfig.from_environment(), compose).run(transport="stdio")


if __name__ == "__main__":
    main()
