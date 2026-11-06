"""The assistant as a long-running server: one process, the tools held open, a browser in front.

Chat and buttons are two views of ONE system, not two apps. Every button action that changes
something is noted and handed to the model with your next message, so "stop the recording"
pressed in buttons mode and "write it up" typed in chat mode refer to the same recording.
Every chat action streams to the browser as events, so a transcription the model started
shows up in the buttons view with a live status. One state, one event stream, one gate.

Security, because this process can send email as you:

  * it binds to 127.0.0.1 unless told otherwise (ASSISTANT_HOST: a container's private network);
  * every /api request must carry a random token issued at launch and injected into the
    page -- a site in another tab can make your browser POST to localhost, but it cannot
    read the page to learn the token;
  * requests whose Host is not localhost are refused, which closes DNS rebinding.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
import json
import logging
import os
import secrets
import shutil
import tempfile
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from pydantic import BaseModel

from assistant.approval import WEB_PREVIEW_LIMIT, needs_approval, sanitise
from assistant.audit import AuditStore
from assistant.conversations import (ConversationStore, NullConversationStore, _new_id, messages_for_storage,
                                     messages_from_events, title_from_message)
from assistant.auth import (
    AuthError, MemorySessionStore, PgSessionStore, clear_cookie, exchange_code, fetch_userinfo,
    google_login_url, parse_allowed_emails, pkce_pair, set_cookie,
)
from assistant.config import load_tool_servers, model_config_from_environment
from assistant.db import Database
from assistant.session import ApprovalRequest, allow_gate, execute, run_turn
from assistant import files, texts
from assistant import uploads as up
from assistant.collect import INVENTORY, RELEASE, Collector
from assistant.records import kept_tools, records_for, shown
from assistant.documents import document_tools
from assistant.setup import context_for, current_lexicon, lexicon_path_for, prepare, stores_for
from assistant.logins import Logins
from assistant.status import model_failure, network_status, tools_status
from assistant.tools import RemoteTool, ToolRegistry
from assistant.schedule import run_every
from assistant.watchers import watch, watch_login

ROOT = Path(__file__).resolve().parent.parent
HISTORY_LIMIT = 1000
KEEPALIVE_SECONDS = 15
LOCAL_HOSTS = {"127.0.0.1", "localhost"}
LOOPBACK_BINDS = {"127.0.0.1", "::1", "localhost"}


def parse_hosts(value: str | None) -> frozenset[str]:
    """Names the API may be reached by, beyond localhost: ASSISTANT_HOSTS, comma separated. Exact
    names only, never patterns -- the Host check is what stops a hostile page pointing its own name at
    this machine, and a pattern is a bigger door than a name."""
    return frozenset(part.strip().lower() for part in (value or "").replace(" ", ",").split(",") if part.strip())
# Where the web app is served from: its own server (8751) and Vite's development server.
# Only these origins may read responses; the token is still required on every call.
DEFAULT_ORIGINS = ("http://127.0.0.1:8751", "http://localhost:8751",
                   "http://127.0.0.1:5173", "http://localhost:5173")
NOTE_LIMIT = 400
# Audio a tool may offer for playing and download. A tool's folder is not enough on its own:
# only these kinds of file are ever sent.
MEDIA_TYPES = {".mp3": "audio/mpeg", ".m4b": "audio/mp4", ".m4a": "audio/mp4", ".wav": "audio/wav",
               ".flac": "audio/flac", ".ogg": "audio/ogg", ".opus": "audio/ogg"}
# What a stored upload is sent as, by id (/api/files/{id}). Anything else goes as plain bytes to download.
STORED_TYPES = {**MEDIA_TYPES, ".pdf": "application/pdf", ".webm": "audio/webm", ".mp4": "audio/mp4",
                ".aac": "audio/aac"}


def approval_view(request: ApprovalRequest) -> dict[str, Any]:
    return {
        "id": request.id,
        "tool": request.tool.qualified_name,
        "server": request.tool.server,
        "name": request.tool.name,
        "title": request.tool.title,
        "arguments": request.arguments,
        # Untrusted content (an email body, a transcript) on its way to a screen. The
        # browser renders it as text, never HTML; this also caps its length.
        "preview": sanitise(request.preview, WEB_PREVIEW_LIMIT) if request.preview else None,
        "preview_expected": request.preview_expected,
    }


log = logging.getLogger("assistant.server")

# The chat page's microphone (meet-ai's `dictate`). A clip is not an upload: it is never stored, listed or noted for
# the model, and is deleted as soon as meet-ai has read it. Two minutes of the browser's Opus is about 1 MB; a WAV of
# the same is about 23 MB.
DICTATION_TOOL = "meet_ai__dictate"
MAX_DICTATION_BYTES = 25 * 1024**2
# Speaking a reply (audiobook's `speak`): the page sends a sentence or two at a time and plays each as it comes.
SPEECH_TOOL = "audiobook__speak"


def parsed(output: str) -> Any:
    try:
        return json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return output


# The events that make up Chat's conversation. Clearing the chat removes these and nothing else: a finished-job
# notice, an upload, and a button's own result are not conversation, and other pages read them.
CONVERSATION_EVENTS = {"user_message", "assistant_text", "turn_done", "turn_error", "turn_stopped",
                       "approval_needed", "approval_resolved"}


def is_conversation(event: dict[str, Any]) -> bool:
    if event.get("type") in CONVERSATION_EVENTS:
        return True
    return event.get("type") in ("tool_started", "tool_finished") and event.get("origin") != "button"


class Hub:
    """Everything the browser and the model share."""

    def __init__(self, registry: ToolRegistry, config: Any, context: str, audit: AuditStore,
                 refresh_context: Callable[[], Awaitable[str]] | None = None,
                 conversations: ConversationStore | NullConversationStore | None = None) -> None:
        self.registry = registry
        self.config = config
        self.context = context
        # A server runs for days. Memory written mid-session -- a fact remembered, a spelling
        # corrected -- must reach the model on the next turn, not after a restart.
        self.refresh_context = refresh_context
        self.audit = audit
        self.conversations = conversations or NullConversationStore()
        self.conversation_id: str | None = None
        self.conversation_title: str = ""
        self.messages: list[dict[str, Any]] = []
        self.notes: list[str] = []
        self.turn: asyncio.Task | None = None
        # Set by Stop; a new one for each turn, so a stop never carries over to the next message.
        self.stop: asyncio.Event | None = None
        self.pending: dict[str, tuple[ApprovalRequest, asyncio.Future]] = {}
        self.subscribers: set[asyncio.Queue] = set()
        self.history: deque[dict[str, Any]] = deque(maxlen=HISTORY_LIMIT)
        self.seq = 0
        # What every login looked like at the last check; Settings, the sidebar and the watcher all read it.
        self.logins = Logins(config, registry, self.emit)

    @property
    def busy(self) -> bool:
        return self.turn is not None and not self.turn.done()

    async def emit(self, event: dict[str, Any]) -> None:
        self.seq += 1
        stamped = {**event, "seq": self.seq, "at": time.time()}
        self.history.append(stamped)
        for queue in list(self.subscribers):
            queue.put_nowait(stamped)

    async def web_gate(self, request: ApprovalRequest) -> bool:
        """Suspend the turn until a person answers in the browser."""
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self.pending[request.id] = (request, future)
        await self.emit({"type": "approval_needed", **approval_view(request)})
        try:
            return await future
        finally:
            self.pending.pop(request.id, None)

    def compose(self, message: str) -> str:
        """The user's message, with anything they did through buttons since the last one.

        Notes are held until a turn boundary rather than appended as they happen: a note
        landing mid-turn would sit between a tool call and its result, and the model's API
        rejects a conversation with that shape.
        """
        if not self.notes:
            return message
        done = "\n".join(f"- {note}" for note in self.notes)
        self.notes.clear()
        return f"[Since your last message, you did this in the interface:\n{done}]\n\n{message}"

    async def save_conversation(self) -> None:
        """Persist the current conversation's events to the database."""
        if self.conversation_id is None:
            return
        conv_events = [e for e in self.history if is_conversation(e)]
        message_count = sum(1 for e in conv_events if e.get("type") == "user_message")
        if message_count == 0:
            return
        try:
            await self.conversations.save(
                self.conversation_id, self.conversation_title, conv_events, message_count,
                messages_for_storage(self.messages))
        except Exception:
            log.warning("could not save conversation %s", self.conversation_id, exc_info=True)

    async def run(self, message: str) -> None:
        checkpoint = len(self.messages)
        held = list(self.notes)
        if self.conversation_id is None:
            self.conversation_id = _new_id()
            self.conversation_title = title_from_message(message)
        await self.emit({"type": "user_message", "text": message})
        if self.refresh_context is not None:
            try:
                self.context = await self.refresh_context()
            except Exception:
                # Memory failing degrades what the assistant knows, never whether it runs: the turn
                # goes ahead with the context it already has.
                pass
        self.messages.append({"role": "user", "content": self.compose(message)})
        self.stop = asyncio.Event()
        try:
            await run_turn(self.registry, self.config, self.messages, self.audit,
                           context=self.context, gate=self.web_gate, emit=self.emit, stop=self.stop)
        except Exception as error:
            # A failed turn can leave a tool call without its result, which would poison
            # every later turn. Roll the conversation back to before it, and keep the notes.
            del self.messages[checkpoint:]
            self.notes = held + self.notes
            plain = model_failure(error, self.config)
            if plain:
                # The model is the trouble, not the request: say so, point at Settings, and keep the raw error.
                await self.emit({"type": "turn_error", "error": plain, "detail": str(error)[:500], "settings": True})
            else:
                await self.emit({"type": "turn_error", "error": str(error)[:500]})
        await self.save_conversation()

    async def clear_chat(self, save: bool = True) -> int:
        """Forget the conversation: what the model remembers of it and what Chat shows. Returns how many
        messages it held.

        The notes go too -- they are what buttons did since the last message, handed to the model with
        the next one, and a model with no conversation has no use for them. Memory (what the assistant
        knows about the user), finished-job notices, uploads and the audit log are not conversation and
        stay. The caller makes sure no turn is running: a turn holds an index into these messages."""
        if save:  # not when the conversation is being deleted: saving would put it straight back
            await self.save_conversation()
        cleared = len(self.messages)
        self.messages.clear()
        self.notes.clear()
        self.conversation_id = None
        self.conversation_title = ""
        kept = [event for event in self.history if not is_conversation(event)]
        self.history.clear()
        self.history.extend(kept)
        # Tells every open page to fetch the pruned history; the rule for what counts as conversation
        # lives here and nowhere else.
        await self.emit({"type": "chat_cleared"})
        return cleared

    async def continue_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        """Make a kept conversation the one Chat is in, so the next message carries on from it: the current one is
        kept first and Chat emptied (as Clear chat does), then the model is given back what it remembered of the
        chosen one and every open page is sent its events again. None when there is no such conversation. The
        caller makes sure no turn is running."""
        if conversation_id == self.conversation_id:
            return {"id": conversation_id, "title": self.conversation_title, "restored": 0}  # already in it
        kept = await self.conversations.get(conversation_id)
        if kept is None:
            return None
        await self.clear_chat()
        self.messages.extend(kept.get("messages") or messages_from_events(kept["events"]))
        self.conversation_id = conversation_id
        self.conversation_title = kept["title"]
        for event in kept["events"]:
            await self.emit({k: v for k, v in event.items() if k not in ("seq", "at")})
        return {"id": conversation_id, "title": kept["title"], "restored": len(kept["events"])}

    def request_stop(self) -> bool:
        """Ask the running turn to stop at its next safe point (see `run_turn`). An approval waiting on
        the person is answered no, which is what stopping means for it. False if nothing is running."""
        if not self.busy or self.stop is None:
            return False
        self.stop.set()
        for _request, future in list(self.pending.values()):
            if not future.done():
                future.set_result(False)
        return True

    def note_text(self, text: str) -> None:
        """Something that happened outside any tool call -- an upload -- told to the model the
        same way a button press is, with the next message."""
        self.notes.append(text[:NOTE_LIMIT])

    def note(self, tool: RemoteTool, arguments: dict[str, Any], outcome: str, output: str) -> None:
        compact = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))
        self.notes.append(
            f"{tool.server}.{tool.name}({compact}) -> {outcome}: {output[:NOTE_LIMIT]}"
        )


class ChatRequest(BaseModel):
    message: str


class ApprovalAnswer(BaseModel):
    approve: bool


class UploadDeletion(BaseModel):
    id: str


class RecordDeletion(BaseModel):
    ids: list[str]


class ConversationRename(BaseModel):
    title: str


class SpeechRequest(BaseModel):
    text: str
    voice: str | None = None


class ActionRequest(BaseModel):
    tool: str
    arguments: dict[str, Any] = {}
    confirmed: bool = False


def create_app(
    tools_path: Path,
    memory_path: Path,
    audit_path: Path,
    provider: str | None = None,
    model: str | None = None,
    token: str | None = None,
    registry_factory: Callable[[list[Any]], ToolRegistry] | None = None,
    watch_jobs: bool = True,
    files_path: Path | None = None,
    texts_path: Path | None = None,
    legacy_uploads: Path | None = None,
    origins: tuple[str, ...] = DEFAULT_ORIGINS,
    hosts: frozenset[str] = frozenset(),
    on_ready: Callable[[], None] | None = None,
    google_client_id: str | None = None,
    google_client_secret: str | None = None,
    google_redirect_uri: str | None = None,
    allowed_emails: frozenset[str] = frozenset(),
    database_url: str | None = None,
) -> FastAPI:
    # Every file the suite keeps (files.py): <root>/<id>/<name>, each recorded in the `files` table, or in
    # index.json there with no database. `legacy_uploads` is the old uploads folder, copied in once on start.
    files_root = (files_path or ROOT / "files").resolve()
    # Where stored markdown is lent to a tool for one call (texts.py). Everything a lend makes there is removed,
    # so it must not be, or hold, the file store.
    texts_root = (texts_path or ROOT / "texts").resolve()
    if texts_root.is_relative_to(files_root) or files_root.is_relative_to(texts_root):
        raise ValueError(f"the texts folder ({texts_root}) and the file store ({files_root}) must be apart")
    token = token or secrets.token_urlsafe(24)
    holder: dict[str, Hub] = {}
    # With a database URL, memory, the audit log and sign-in sessions live in PostgreSQL and the two
    # files are imported into it once; without one they are the files. Connected in the lifespan.
    database = (Database(database_url, legacy_memory=memory_path, legacy_audit=audit_path)
                if database_url else None)
    memory, audit = stores_for(database, memory_path, audit_path)
    conversations = ConversationStore(database) if database else NullConversationStore()
    file_index = files.index_for(database, files_root)
    # What tools made that the suite keeps, under the tools' own labels (records.py, collect.py).
    records = records_for(database, files_root)
    lender = texts.Lender(texts_root, file_index)
    doc_batches = up.DocBatches()
    lexicon_path = lexicon_path_for(memory_path)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        config = model_config_from_environment(provider, model)
        if database is not None:
            await database.connect()
        if legacy_uploads is not None:
            app.state.files_imported = await up.import_old_uploads(file_index, files_root, legacy_uploads)
        lender.clear()
        local_tools, context = await prepare(memory, lexicon_path)
        local_tools = [*local_tools, *document_tools(files_root, texts_root, file_index),
                       *kept_tools(records, file_index)]
        registry = (registry_factory(local_tools) if registry_factory
                    else ToolRegistry(load_tool_servers(tools_path), local=local_tools))
        registry.lend = lender.lend
        # Held open for the life of the server: the tools stay running instead of being
        # relaunched for every request.
        await registry.__aenter__()
        holder["hub"] = Hub(registry, config, context, audit,
                            refresh_context=lambda: context_for(memory, lexicon_path),
                            conversations=conversations)
        app.state.hub = holder["hub"]
        # What a tool made is taken into the store and the database: after a call that changed something, when
        # the watcher sees a job finish, and now, which the first time is the taking-in of what is already there.
        # Never after the tool's own inventory or release, which would only ask again.
        collector = Collector(registry, file_index, records, files_root, emit=holder["hub"].emit)
        registry.changed = lambda tool: None if tool.name in (INVENTORY, RELEASE) else collector.soon(tool.server)
        app.state.collector = collector
        for server in collector.offering():
            collector.soon(server)
        # Tells the browser when a long job finishes, so nobody has to keep asking.
        watchers = [
            asyncio.create_task(watch(registry, holder["hub"].emit, on_change=collector.soon)),
            asyncio.create_task(watch_login(holder["hub"].logins)),
        ] if watch_jobs else []
        # What tools.yaml says to run on a timer (mail's sync), whether or not a page is open.
        watchers += [asyncio.create_task(run_every(registry, audit, holder["hub"].emit, server, name, seconds))
                     for server, name, seconds in registry.schedules]
        # Only now -- tools started, hub up -- is the server really accepting calls. Announcing
        # earlier sent people (and a browser tab) to a port that refused the connection.
        if on_ready is not None:
            on_ready()
        try:
            yield
        finally:
            for task in watchers:
                task.cancel()
            await collector.stop()
            await registry.__aexit__(None, None, None)
            if database is not None:
                await database.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.token = token
    app.state.database = database
    app.state.files_root = files_root
    app.state.texts_root = texts_root
    app.state.files_imported = {}

    def hub() -> Hub:
        return holder["hub"]

    allowed_hosts = LOCAL_HOSTS | hosts
    sessions = ((PgSessionStore(database) if database is not None else MemorySessionStore())
                if google_client_id and google_client_secret else None)

    async def authenticate(request: Request) -> bool:
        """Is this request from someone who may use the API? The one place that decides.

        Two ways in: the launch token (header or, for EventSource, query param) and a Google
        sign-in session cookie. Either one is enough."""
        supplied = request.headers.get("x-assistant-token") or ""
        if not supplied and request.url.path == "/api/events":
            supplied = request.query_params.get("token", "")
        if supplied and secrets.compare_digest(supplied, token):
            return True
        if sessions is not None:
            sid = request.cookies.get("session", "")
            if sid and await sessions.get(sid) is not None:
                return True
        return False

    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]").lower()
        if host not in allowed_hosts:
            return JSONResponse({"error": "forbidden host"}, status_code=403)
        path = request.url.path
        if path.startswith("/auth/") or path == "/api/me":
            return await call_next(request)
        if path.startswith("/api/") and not await authenticate(request):
            return JSONResponse({"error": "missing or wrong token"}, status_code=401)
        return await call_next(request)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(origins),
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["content-type", "x-assistant-token", "ngrok-skip-browser-warning"],
        allow_credentials=True,
    )

    # -----------------------------------------------------------------------
    # Google sign-in (when configured)
    # -----------------------------------------------------------------------

    if sessions is not None and google_client_id and google_client_secret and google_redirect_uri:
        @app.get("/auth/login")
        async def auth_login(request: Request):
            redirect = request.query_params.get("redirect", "")
            if redirect and not any(redirect.rstrip("/") == o.rstrip("/") for o in origins):
                return JSONResponse({"error": "invalid redirect"}, status_code=400)
            verifier, challenge = pkce_pair()
            state = secrets.token_urlsafe(24)
            sessions.save_pending(state, verifier, redirect)
            return RedirectResponse(
                google_login_url(google_client_id, google_redirect_uri, state, challenge),
                status_code=302,
            )

        @app.get("/auth/callback")
        @app.get("/auth/callback/")
        async def auth_callback(request: Request):
            error = request.query_params.get("error")
            state = request.query_params.get("state", "")
            pending = sessions.pop_pending(state) if state else None

            if error:
                target = pending[1] if pending else "/"
                return RedirectResponse(target)

            code = request.query_params.get("code")
            if not code or not pending:
                return JSONResponse({"error": "missing code or expired state"}, status_code=400)
            verifier, redirect = pending

            try:
                tokens = await exchange_code(
                    google_client_id, google_client_secret, google_redirect_uri, code, verifier)
                access_token = tokens.get("access_token")
                if not access_token:
                    raise AuthError("no access token in response")
                userinfo = await fetch_userinfo(access_token)
            except AuthError:
                return JSONResponse({"error": "sign-in failed"}, status_code=502)

            email = (userinfo.get("email") or "").lower()
            if not userinfo.get("email_verified"):
                return JSONResponse({"error": "email not verified by Google"}, status_code=403)
            if email not in allowed_emails:
                return JSONResponse({"error": "this account is not allowed"}, status_code=403)

            sid = await sessions.create(email)
            secure = request.url.scheme == "https"
            target = redirect or "/"
            if "127.0.0.1" in target:
                target = target.replace("127.0.0.1", "localhost")
            response = RedirectResponse(target, status_code=302)
            response.headers["set-cookie"] = set_cookie(sid, secure)
            return response

        @app.post("/auth/logout")
        async def auth_logout(request: Request):
            sid = request.cookies.get("session", "")
            if sid:
                await sessions.delete(sid)
            secure = request.url.scheme == "https"
            response = JSONResponse({"ok": True})
            response.headers["set-cookie"] = clear_cookie(secure)
            return response

    @app.get("/api/me")
    async def me(request: Request):
        email = None
        if sessions is not None:
            sid = request.cookies.get("session", "")
            session = await sessions.get(sid) if sid else None
            if session:
                email = session.email
        return {"email": email, "google_auth": sessions is not None}

    @app.get("/api/tools")
    async def tools() -> list[dict[str, Any]]:
        return [
            {
                "qualified_name": t.qualified_name, "server": t.server, "name": t.name, "title": t.title,
                "description": t.description, "read_only": t.read_only,
                "has_preview": t.preview is not None, "input_schema": t.input_schema,
            }
            for t in hub().registry.tools
        ]

    @app.get("/api/state")
    async def state() -> dict[str, Any]:
        h = hub()
        return {
            "busy": h.busy,
            "pending": [approval_view(r) for r, _f in h.pending.values()],
            "history": list(h.history),
            "notes": list(h.notes),
            "model": h.config.resolved_model,
        }

    @app.post("/api/chat")
    async def chat(body: ChatRequest) -> dict[str, Any]:
        h = hub()
        if not body.message.strip():
            raise HTTPException(400, "empty message")
        if h.busy:
            raise HTTPException(409, "still working on the last message")
        h.turn = asyncio.create_task(h.run(body.message.strip()))
        return {"accepted": True}

    @app.post("/api/chat/stop")
    async def stop_chat() -> dict[str, Any]:
        """Stop the reply being worked on. It ends at the next safe point: a tool already running
        finishes and is recorded, nothing after it starts, and an approval waiting is declined."""
        if not hub().request_stop():
            raise HTTPException(409, "nothing is being worked on")
        return {"stopping": True}

    @app.post("/api/chat/clear")
    async def clear_chat() -> dict[str, Any]:
        """Delete the conversation. Refused while a message is being worked on: the turn is in the
        middle of that conversation, and an approval waiting on you is part of it."""
        h = hub()
        if h.busy or h.pending:
            raise HTTPException(409, "still working on a message; clear the chat when it has finished")
        cleared = await h.clear_chat()
        await audit.record(tool="assistant__clear_chat", arguments={}, outcome="ok",
                           result=f"{cleared} messages", origin="button")
        return {"cleared": cleared}

    @app.get("/api/conversations")
    async def list_conversations(limit: int = 50) -> list[dict[str, Any]]:
        return await hub().conversations.list(max(1, min(limit, 200)))

    @app.get("/api/conversations/current")
    async def current_conversation() -> dict[str, Any]:
        h = hub()
        return {"id": h.conversation_id, "title": h.conversation_title}

    @app.get("/api/conversations/{conversation_id}")
    async def get_conversation(conversation_id: str) -> dict[str, Any]:
        conv = await hub().conversations.get(conversation_id)
        if conv is None:
            raise HTTPException(404, "no such conversation")
        return conv

    @app.delete("/api/conversations/{conversation_id}")
    async def delete_conversation(conversation_id: str) -> dict[str, Any]:
        """Delete a kept conversation. The one Chat is in now leaves Chat too, as Clear chat does, and is refused
        while a message in it is being worked on: left open, its next message saved it again, deleted messages and
        old title and all (found in Chrome)."""
        h = hub()
        current = conversation_id == h.conversation_id
        if current and (h.busy or h.pending):
            raise HTTPException(409, "still working on a message in this conversation; delete it when it has finished")
        kept = await h.conversations.get(conversation_id)
        if kept is None or not await h.conversations.delete(conversation_id):
            raise HTTPException(404, "no such conversation")
        if current:
            await h.clear_chat(save=False)
        await audit.record(tool="assistant__delete_conversation", arguments={"id": conversation_id}, outcome="ok",
                           result=f"{kept['title']!r}, {kept['message_count']} messages"
                                  + ("; Chat cleared" if current else ""), origin="button")
        return {"deleted": True, "cleared": current}

    @app.patch("/api/conversations/{conversation_id}")
    async def rename_conversation(conversation_id: str, body: ConversationRename) -> dict[str, Any]:
        if not body.title.strip():
            raise HTTPException(400, "empty title")
        h = hub()
        if not await h.conversations.rename(conversation_id, body.title.strip()):
            raise HTTPException(404, "no such conversation")
        if conversation_id == h.conversation_id:
            h.conversation_title = body.title.strip()  # or the next save would put the old title back
        return {"renamed": True}

    @app.post("/api/conversations/{conversation_id}/continue")
    async def continue_conversation(conversation_id: str) -> dict[str, Any]:
        """Carry on a kept conversation. Refused while a message is being worked on, as Clear chat is: the turn is in
        the middle of the conversation that would be put away. Audited, as Clear chat is."""
        h = hub()
        if h.busy or h.pending:
            raise HTTPException(409, "still working on a message; continue another conversation when it has finished")
        continued = await h.continue_conversation(conversation_id)
        if continued is None:
            raise HTTPException(404, "no such conversation")
        await audit.record(tool="assistant__continue_conversation", arguments={"id": conversation_id}, outcome="ok",
                           result=repr(continued["title"]), origin="button")
        return continued

    @app.post("/api/approvals/{approval_id}")
    async def answer(approval_id: str, body: ApprovalAnswer) -> dict[str, Any]:
        h = hub()
        entry = h.pending.get(approval_id)
        if entry is None:
            raise HTTPException(404, "no such pending approval")
        request, future = entry
        if not future.done():
            future.set_result(body.approve)
        await h.emit({"type": "approval_resolved", "id": approval_id,
                      "tool": request.tool.qualified_name, "approved": body.approve})
        return {"approved": body.approve}

    @app.post("/api/actions")
    async def action(body: ActionRequest) -> dict[str, Any]:
        """A button press: you chose the tool, so no model is involved.

        The click is the approval -- except where the tool declares a preview of its
        effect, as sending an email does. There the first press returns the preview and
        only a confirmed second press acts, the same rule the chat gate applies.
        """
        h = hub()
        tool = h.registry.find(body.tool)
        if tool is None:
            raise HTTPException(404, f"no tool {body.tool}")

        if needs_approval(tool) and tool.preview is not None and not body.confirmed:
            preview = await h.registry.preview_of(tool, body.arguments)
            return {"needs_confirmation": True,
                    "preview": sanitise(preview, WEB_PREVIEW_LIMIT) if preview else None,
                    "preview_expected": True}

        arguments = dict(body.arguments)
        if "lexicon" in (tool.input_schema.get("properties") or {}) and "lexicon" not in arguments:
            lexicon = await current_lexicon(memory, lexicon_path)
            if lexicon is not None:
                arguments["lexicon"] = str(lexicon)

        output, outcome = await execute(h.registry, tool, arguments, h.audit,
                                        allow_gate, h.emit, origin="button")
        # Only actions that changed something become notes. A status poll every few seconds
        # would bury the model's context in noise.
        if not tool.read_only:
            h.note(tool, arguments, outcome, output)
        return {"outcome": outcome, "output": parsed(output)}

    @app.get("/api/events")
    async def events(request: Request) -> StreamingResponse:
        h = hub()
        queue: asyncio.Queue = asyncio.Queue()
        h.subscribers.add(queue)

        async def stream():
            # Sent at once, before any event exists. A browser only fires EventSource.onopen
            # when the first bytes arrive, so without this every page load reported
            # "reconnecting" -- and kept the message box disabled -- for up to 15 seconds.
            yield ": connected\n\n"
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_SECONDS)
                        yield f"data: {json.dumps(event, default=str)}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
            finally:
                h.subscribers.discard(queue)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    @app.get("/api/status")
    async def status(live: bool = False) -> dict[str, Any]:
        """What Settings shows. Tools are read from what is already known; the network and
        every login are only checked when asked (live=true), since each costs a round trip."""
        h = hub()
        if live:
            network, _checked = await asyncio.gather(asyncio.to_thread(network_status), h.logins.check())
        # What the last check found -- this one, when live, otherwise the watcher's, which is at most ten minutes
        # old (a minute while a login is out). Before any check it is only what is configured.
        out: dict[str, Any] = {
            "tools": await tools_status(h.registry, h.audit, h.logins.tools),
            "model": h.logins.model or {"provider": h.config.provider, "model": h.config.resolved_model,
                                        "profile": h.config.profile, "region": h.config.region},
            "mail_compose": h.registry.find("mail_ai__send_draft") is not None,
        }
        if live:
            out["network"] = network
        return out

    # -----------------------------------------------------------------------
    # Uploads. The body is the file itself, streamed to disk -- a four-hour recording is
    # never held in memory. Each goes into the file store under its own name and ends in a
    # path, which is all any tool needs.
    # -----------------------------------------------------------------------

    def refuse(error: up.UploadError) -> JSONResponse:
        return JSONResponse({"error": str(error)}, status_code=400)

    @app.get("/api/uploads")
    async def list_uploads() -> dict[str, Any]:
        return await up.listing(file_index, files_root, texts_root)

    async def take(request: Request, name: str, kind: str, target_for: Callable[[Path, str], tuple[str, Path]],
                   limit: int) -> tuple[files.StoredFile, Path]:
        """One file into a new slot of its own, recorded once whole. A refused or broken-off upload leaves
        no slot behind."""
        file_id, target = target_for(files_root, name)
        try:
            size, sha256 = await up.receive(target, request.stream(), limit)
        except BaseException:
            files.discard_slot(files_root, file_id)
            raise
        return await up.keep(file_index, file_id, kind, target, size, sha256), target

    @app.put("/api/uploads/audio")
    async def upload_audio(request: Request, name: str):
        h = hub()
        try:
            record, target = await take(request, name, "audio", up.audio_target, up.MAX_AUDIO_BYTES)
        except up.UploadError as error:
            return refuse(error)
        h.note_text(f"The user uploaded audio {target.name} ({record.bytes} bytes), saved at {target}.")
        await h.emit({"type": "upload", "kind": "audio", "id": record.id, "name": target.name, "path": str(target)})
        return {"id": record.id, "name": target.name, "path": str(target), "bytes": record.bytes}

    @app.put("/api/dictate")
    async def dictate(request: Request, name: str = "clip.webm") -> Any:
        """A spoken clip in, its words out, for the message box. A read from the page, so not audited and not shown
        as a step (session.execute); refusals are {"error"}, which is what the page's upload helper reads."""
        h = hub()
        tool = h.registry.find(DICTATION_TOOL)
        if tool is None:
            return JSONResponse({"error": "Dictation needs meet-ai, which is not running."}, status_code=503)
        suffix = Path(name).suffix.lower()
        if suffix not in up.AUDIO_EXTS:
            return JSONResponse({"error": f"{name} is not an audio file"}, status_code=400)
        folder = Path(tempfile.mkdtemp(prefix="dictation-"))
        try:
            clip = folder / f"clip{suffix}"
            try:
                await up.receive(clip, request.stream(), MAX_DICTATION_BYTES)
            except up.UploadError as error:
                return refuse(error)
            output, outcome = await execute(h.registry, tool, {"audio": str(clip)}, h.audit,
                                            allow_gate, h.emit, origin="button")
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        result = parsed(output)
        if outcome != "ok" or not isinstance(result, dict) or result.get("error"):
            message = result.get("error") if isinstance(result, dict) else output
            return JSONResponse({"error": message or "Dictation failed."}, status_code=422)
        return result

    @app.post("/api/speak")
    async def speak(body: SpeechRequest) -> Any:
        """A sentence or two of a reply, spoken: MP3 bytes back. A read from the page, so not audited and not shown as
        a step (session.execute), and nothing is kept. Refusals are {"error"}."""
        h = hub()
        tool = h.registry.find(SPEECH_TOOL)
        if tool is None:
            return JSONResponse({"error": "Speaking replies needs the audiobook tool, which is not running."},
                                status_code=503)
        arguments: dict[str, Any] = {"text": body.text, **({"voice": body.voice} if body.voice else {})}
        output, outcome = await execute(h.registry, tool, arguments, h.audit, allow_gate, h.emit, origin="button")
        result = parsed(output)
        if outcome != "ok" or not isinstance(result, dict) or result.get("error") or not result.get("audio"):
            message = result.get("error") if isinstance(result, dict) else output
            return JSONResponse({"error": message or "Speaking failed."}, status_code=422)
        try:
            audio = base64.b64decode(result["audio"], validate=True)
        except (binascii.Error, ValueError, TypeError):
            return JSONResponse({"error": "The audiobook tool sent back something that is not audio."}, status_code=502)
        return Response(audio, media_type=str(result.get("mime") or "audio/mpeg"), headers={"cache-control": "no-store"})

    @app.put("/api/uploads/book")
    async def upload_book(request: Request, name: str):
        h = hub()
        try:
            record, target = await take(request, name, "book", up.book_target, up.MAX_BOOK_BYTES)
        except up.UploadError as error:
            return refuse(error)
        h.note_text(f"The user uploaded a book (PDF) {target.name} ({record.bytes} bytes), saved at {target}.")
        await h.emit({"type": "upload", "kind": "book", "id": record.id, "name": target.name, "path": str(target)})
        return {"id": record.id, "name": target.name, "path": str(target), "bytes": record.bytes}

    @app.put("/api/uploads/voice")
    async def upload_voice(request: Request, name: str):
        h = hub()
        try:
            record, target = await take(request, name, "voice", up.voice_target, up.MAX_VOICE_BYTES)
        except up.UploadError as error:
            return refuse(error)
        h.note_text(f"The user uploaded a recording {target.name} to clone a voice from "
                    f"({record.bytes} bytes), saved at {target}.")
        await h.emit({"type": "upload", "kind": "voice", "id": record.id, "name": target.name, "path": str(target)})
        return {"id": record.id, "name": target.name, "path": str(target), "bytes": record.bytes}

    @app.post("/api/uploads/delete")
    async def delete_upload(body: UploadDeletion):
        """Delete one upload by the id the listing gave it. Only buttons reach this: no tool offers it, so
        a model cannot delete a person's files. Every delete is audited and noted."""
        h = hub()
        try:
            gone = await up.delete_upload(file_index, files_root, body.id)
        except up.UploadError as error:
            return refuse(error)
        except OSError as error:
            return refuse(up.UploadError(f"could not delete it: {error.strerror or error}"))
        h.note_text(f"The user deleted the {gone['kind']} upload {gone['name']}; it no longer exists.")
        await h.emit({"type": "upload_deleted", "kind": gone["kind"], "id": gone["id"], "name": gone["name"]})
        await audit.record(tool="assistant__delete_upload",
                           arguments={"id": gone["id"], "kind": gone["kind"], "name": gone["name"]},
                           outcome="ok", result=f"{gone['files']} file(s), {gone['bytes']} bytes", origin="button")
        return gone

    @app.get("/api/files/{file_id}")
    async def stored_file(file_id: str):
        """An upload, by the id the listing gave it, for the web app to play or download. A folder of
        markdown is not a file to send. Every refusal is the same plain 404, as for /api/files."""
        record = await file_index.get(file_id) if files.is_id(file_id) else None
        if record is None or record.kind == "docs":
            raise HTTPException(404, "no such file")
        candidate = files.path_of(files_root, record)
        try:
            resolved = candidate.resolve()
        except (ValueError, OSError):
            raise HTTPException(404, "no such file") from None
        if candidate.is_symlink() or not resolved.is_file() or resolved.parent != (files_root / record.id).resolve():
            raise HTTPException(404, "no such file")
        return FileResponse(resolved, media_type=STORED_TYPES.get(resolved.suffix.lower(), "application/octet-stream"),
                            filename=record.name)

    # -----------------------------------------------------------------------
    # What tools made that the suite keeps (records.py): listed under the tool's own labels, its text read one at
    # a time, deleted only by a button. The page knows what they are; this server does not.
    # -----------------------------------------------------------------------

    @app.get("/api/records")
    async def list_records(tool: str, kind: str | None = None) -> dict[str, Any]:
        return {"records": [await shown(r, file_index) for r in await records.find(tool, kind)]}

    @app.get("/api/records/{record_id}")
    async def one_record(record_id: str) -> dict[str, Any]:
        record = await records.by_id(record_id) if files.is_id(record_id) else None
        if record is None:
            raise HTTPException(404, "no such record")
        return {**await shown(record, file_index), "text": record.text}

    @app.post("/api/records/delete")
    async def delete_records(body: RecordDeletion):
        """Delete records and their files, by the ids the listing gave. Only buttons reach this: no tool offers
        it, so a model cannot delete what a person kept. Audited and noted, as deleting an upload is."""
        h = hub()
        gone: list[Any] = []
        for record_id in dict.fromkeys(body.ids):
            record = await records.by_id(record_id) if files.is_id(record_id) else None
            if record is None:
                return refuse(up.UploadError(f"no such record: {record_id}"))
            gone.append(record)
        size = 0
        for record in gone:
            await records.remove(record.id)
            for file_id in record.files.values():
                size += await files.drop_made(file_index, files_root, file_id)
        if gone:
            names = sorted({str(r.labels.get("title") or r.key) for r in gone})
            h.note_text(f"The user deleted {len(gone)} kept item(s) of {gone[0].tool}: {', '.join(names[:10])}; "
                        f"they no longer exist.")
            await h.emit({"type": "records_changed", "tool": gone[0].tool})
            await audit.record(tool="assistant__delete_records",
                               arguments={"tool": gone[0].tool, "kinds": sorted({r.kind for r in gone}),
                                          "keys": [r.key for r in gone][:50]},
                               outcome="ok", result=f"{len(gone)} record(s), {size} bytes", origin="button")
        return {"deleted": len(gone), "bytes": size}

    @app.get("/api/files")
    async def media(path: str):
        """Audio a tool made, for the web app to play or download. The token rides in a header
        like everywhere else, so the app fetches this itself rather than pointing an <audio>
        tag at it. Nothing is served unless it is an audio file inside a folder tools.yaml
        declared for some tool; anything else is a plain 404, so the answer says nothing about
        what exists elsewhere."""
        try:
            resolved = Path(path).resolve()  # follows symlinks: the check is on where it really is
        except (ValueError, OSError):  # a NUL byte, an unreadable link loop: still just "not there"
            raise HTTPException(404, "no such file") from None
        roots = [root.resolve() for root in hub().registry.media_roots]
        kind = MEDIA_TYPES.get(resolved.suffix.lower())
        if kind is None or not resolved.is_file() or not any(resolved.is_relative_to(r) for r in roots):
            raise HTTPException(404, "no such file")
        return FileResponse(resolved, media_type=kind, filename=resolved.name)

    # Markdown goes into the database, not the file store: held until the batch is done, then stored whole.
    @app.post("/api/uploads/docs")
    async def start_docs(body: dict[str, Any]):
        try:
            return {"batch": doc_batches.start(str(body.get("name", "")))}
        except up.UploadError as error:
            return refuse(error)

    @app.put("/api/uploads/docs/{batch}")
    async def upload_doc(batch: str, request: Request, name: str):
        try:
            kept, size = await doc_batches.receive(batch, name, request.stream())
        except up.UploadError as error:
            return refuse(error)
        return {"name": kept, "bytes": size}

    @app.post("/api/uploads/docs/{batch}/done")
    async def finish_docs(batch: str):
        h = hub()
        try:
            record, names = await doc_batches.finish(file_index, batch)
        except up.UploadError as error:
            return refuse(error)
        path = texts.path_for(texts_root, record, names)
        h.note_text(f"The user uploaded markdown for a document: {', '.join(names)}, "
                    f"ready to build from {path}.")
        await h.emit({"type": "upload", "kind": "docs", "id": record.id, "name": record.name, "path": str(path)})
        return {"id": record.id, "name": record.name, "path": str(path), "files": names}

    @app.get("/api/history")
    async def audit_history(limit: int = 200) -> list[dict[str, Any]]:
        """The durable record of every tool call, newest first -- the live event stream only
        covers this run; this survives restarts."""
        return await audit.recent(max(1, min(limit, 2000)))

    @app.get("/")
    async def root() -> dict[str, Any]:
        # The API only. The web app is its own program (suite/web) on its own port, and this
        # server knows nothing about it beyond which origins may call it.
        return {"service": "assistant", "api": "/api"}

    return app


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="The assistant, in a browser.")
    parser.add_argument("--port", type=int, default=int(os.environ.get("ASSISTANT_PORT", 8750)))
    parser.add_argument("--host", default=os.environ.get("ASSISTANT_HOST", "127.0.0.1"),
                        help="address to bind; 127.0.0.1 unless this runs in a container's own network")
    parser.add_argument("-t", "--tools", default=str(ROOT / "tools.yaml"))
    parser.add_argument("-m", "--memory", default=os.environ.get("ASSISTANT_MEMORY", str(ROOT / "memory.json")))
    parser.add_argument("-a", "--audit", default=os.environ.get("ASSISTANT_AUDIT", str(ROOT / "audit.jsonl")))
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    from assistant.cli import quieten_libraries

    quieten_libraries()
    # The token is random per launch unless ASSISTANT_TOKEN fixes it.
    stored = Path(os.environ["ASSISTANT_FILES"]) if os.environ.get("ASSISTANT_FILES") else None
    lent = Path(os.environ["ASSISTANT_TEXTS"]) if os.environ.get("ASSISTANT_TEXTS") else None
    # The old uploads folder: what is still in it is copied into the file store on start, once.
    uploads = Path(os.environ.get("ASSISTANT_UPLOADS") or ROOT / "uploads")
    origins = tuple(o.strip() for o in os.environ.get("ASSISTANT_ORIGINS", "").split(",") if o.strip())
    hosts = parse_hosts(os.environ.get("ASSISTANT_HOSTS"))
    fixed = bool(os.environ.get("ASSISTANT_TOKEN"))
    holder: dict[str, FastAPI] = {}

    def announce() -> None:
        # Printed for the case where the web app runs without being handed the token (the two
        # started separately); ../start gives both the same one and nobody needs this line.
        # flush: when stdout is a file or a pipe rather than a terminal, Python holds these
        # back, and the one line a person needs to connect never appears in the log.
        if args.host in LOOPBACK_BINDS:
            print(f"assistant API on http://{args.host}:{args.port}/  (localhost only)", flush=True)
        else:
            # Said out loud, because it is the one setting that changes who can knock. Whatever
            # reaches this port still needs the token and a Host from the allowed list.
            print(f"assistant API listening on {args.host}:{args.port} -- NOT localhost-only. Reachable by "
                  f"whatever can reach this port; publish it to 127.0.0.1 or a private network only.", flush=True)
            print(f"  allowed Host names beyond localhost: {', '.join(sorted(hosts)) or '(none)'}", flush=True)
        database = holder["app"].state.database
        if database is None:
            print("memory and history: files (no DATABASE_URL)", flush=True)
        else:
            print("memory and history: PostgreSQL", flush=True)
            labels = {"facts": "facts", "audit": "audit rows", "audit_skipped": "unreadable audit lines skipped"}
            moved = ", ".join(f"{n} {labels[name]}" for name, n in database.imported.items() if n)
            if moved:
                print(f"  imported from the old files, which are now renamed .imported: {moved}", flush=True)
        print(f"files: {holder['app'].state.files_root}; markdown in the database, lent to tools in "
              f"{holder['app'].state.texts_root}", flush=True)
        imported = dict(holder["app"].state.files_imported)
        unreadable = imported.pop("docs_unreadable", 0)
        copied = ", ".join(f"{n} from {folder}" for folder, n in imported.items() if n)
        if copied:
            print(f"  copied in from the old uploads folder, whose folders are now renamed .imported: {copied}",
                  flush=True)
        if unreadable:
            print(f"  NOT copied in: {unreadable} markdown folder(s) that are not UTF-8 text; they are in "
                  f"docs.imported", flush=True)
        print(f"access token: {holder['app'].state.token}", flush=True)
        if not fixed:
            print("  (new on every launch; set ASSISTANT_TOKEN in .env to keep one across restarts)",
                  flush=True)

    app = create_app(Path(args.tools), Path(args.memory), Path(args.audit), files_path=stored,
                     texts_path=lent, legacy_uploads=uploads,
                     provider=args.provider, model=args.model,
                     token=os.environ.get("ASSISTANT_TOKEN") or None,
                     origins=origins or DEFAULT_ORIGINS, hosts=hosts, on_ready=announce,
                     google_client_id=os.environ.get("GOOGLE_CLIENT_ID") or None,
                     google_client_secret=os.environ.get("GOOGLE_CLIENT_SECRET") or None,
                     google_redirect_uri=os.environ.get("GOOGLE_REDIRECT_URI") or None,
                     allowed_emails=parse_allowed_emails(os.environ.get("ASSISTANT_ALLOWED_EMAILS")),
                     database_url=os.environ.get("DATABASE_URL") or None)
    holder["app"] = app
    # Loopback unless ASSISTANT_HOST says otherwise, and it says otherwise only in the container
    # setup, whose compose file publishes the port to 127.0.0.1 and to a private Tailscale
    # network, never to the world. Never bind 0.0.0.0 on a machine on a network you do not
    # control: this process can send email as you.
    #
    # timeout_graceful_shutdown is not optional. uvicorn waits for open connections to drain
    # before stopping, and the event stream never drains on its own -- so any browser tab left
    # open blocked shutdown forever, and the three tool processes with it. Found by trying to
    # restart the server with a stream still connected.
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning",
                timeout_graceful_shutdown=3)


if __name__ == "__main__":
    main()
