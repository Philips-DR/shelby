"""The MCP client half: launch each tool, hold the sessions, expose what they offer.

Every tool is a child process speaking MCP over stdio. None of them is a network service,
none has to be running beforehand, and the assistant is the only thing that knows more than
one of them exists.
"""

from __future__ import annotations

import json
import os
import sys
from contextlib import AbstractAsyncContextManager, AsyncExitStack, nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from assistant.config import ToolServer

# The separator between a server's name and a tool's own. Two underscores, because tool
# names themselves contain single ones and a collision here would route a call to the
# wrong server.
QUALIFIER = "__"

# What the backend knows that a tool must not. A tool inherits the backend's environment (that is how
# credentials and paths reach it), so anything the backend alone may use has to be taken out of it:
# a tool holding the database address could read memory, which no tool may.
# The model's key is the backend's too, and goes by name to the one tool that calls a model (meet-ai, in tools.yaml):
# inherited by all, it would sit in the environment of web-ai, which reads arbitrary web pages.
WITHHELD_FROM_TOOLS = ("DATABASE_URL", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


def tool_environment(extra: dict[str, str]) -> dict[str, str]:
    """The environment a tool is started with: this process's, less what is the backend's alone, plus what
    tools.yaml injects for that tool."""
    inherited = {k: v for k, v in os.environ.items() if k not in WITHHELD_FROM_TOOLS}
    return {**inherited, **extra}


# Built-in tools are namespaced like any server, so a model cannot tell them apart from a
# real one and the gate treats them identically.
LOCAL_SERVER = "assistant"


@dataclass(frozen=True)
class ApprovalPreview:
    """How a tool says its effect should be shown before someone approves it.

    A destructive tool whose arguments are opaque identifiers cannot be approved from its
    arguments: `send_draft(draft_id, confirmation)` says nothing about who the mail is for
    or what it says. A tool may therefore point at the read-only tool that renders its
    effect, and the gate shows that instead.

    Declared by the tool in MCP's `_meta`, so the assistant never learns what any
    particular tool does -- only how to ask it.
    """

    tool: str
    argument_map: dict[str, str]
    field: str | None = None

    @staticmethod
    def parse(meta: Any) -> "ApprovalPreview | None":
        spec = (meta or {}).get("approval") if isinstance(meta, dict) else None
        if not isinstance(spec, dict) or not spec.get("preview_tool"):
            return None
        mapping = spec.get("argument_map")
        return ApprovalPreview(
            tool=str(spec["preview_tool"]),
            argument_map={str(k): str(v) for k, v in mapping.items()} if isinstance(mapping, dict) else {},
            field=str(spec["field"]) if spec.get("field") else None,
        )


# Marks a local tool that renders its own preview; the registry calls its `render` directly.
LOCAL_RENDER = ApprovalPreview(tool="", argument_map={})


@dataclass(frozen=True)
class LocalTool:
    """A tool the assistant implements itself, for the things no tool should own.

    Memory is the only such thing: it is the assistant's own state, and putting it behind
    an MCP server would make it a tool that every other tool would eventually want to read.
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool
    handler: Callable[[dict[str, Any]], Awaitable[str]]
    # What the approval gate shows instead of raw arguments -- a whole document as a JSON
    # string cannot be reviewed. A remote tool declares its preview in _meta; a local one
    # simply renders it.
    render: Callable[[dict[str, Any]], Awaitable[str]] | None = None


@dataclass(frozen=True)
class ToolOutcome:
    """What a tool returned, and whether the tool itself considered it a failure."""

    text: str
    is_error: bool


@dataclass(frozen=True)
class RemoteTool:
    """One tool on one server, as the model will see it."""

    server: str
    name: str
    qualified_name: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool
    preview: ApprovalPreview | None = None
    # What the tool calls itself for a person ("Write a new draft"), for the interface; the model is
    # shown the name and description only.
    title: str = ""

    def as_anthropic_tool(self) -> dict[str, Any]:
        return {
            "name": self.qualified_name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


class ToolRegistry:
    """Owns the sessions. Async context manager: entering launches every server."""

    def __init__(self, servers: list[ToolServer], local: list[LocalTool] | None = None) -> None:
        self._servers = servers
        self._local = {tool.name: tool for tool in (local or [])}
        self._sessions: dict[str, ClientSession] = {}
        self._stack = AsyncExitStack()
        self.tools: list[RemoteTool] = []
        # Held around every call to a tool: what its arguments name that must be on disk for it, there for the
        # length of the call. Stored markdown is lent this way (texts.py); nothing, until the server sets it.
        self.lend: Callable[[dict[str, Any]], AbstractAsyncContextManager[Any]] = lambda _arguments: nullcontext()
        # Told of every call to a tool that may have changed something (not read-only, and not reported as failed),
        # once it has returned: what it made may now be worth keeping (collect.py). Nothing, until the server sets it.
        self.changed: Callable[[RemoteTool], None] = lambda _tool: None

    def folders_of(self, server: str) -> list[Path]:
        """The folders one tool declared in tools.yaml (`files:`): what it makes, which may be served and kept."""
        return [Path(f) for s in self._servers if s.safe_name == server for f in s.files]

    @property
    def media_roots(self) -> list[Path]:
        """Folders the web app may fetch audio from: exactly what tools.yaml declared."""
        return [Path(f) for server in self._servers for f in server.files]

    @property
    def schedules(self) -> list[tuple[str, str, int]]:
        """(server, qualified tool name, seconds) for every tool tools.yaml says to run on a timer."""
        return [(server.name, f"{server.safe_name}{QUALIFIER}{s.tool}", s.every_seconds)
                for server in self._servers for s in server.schedule]

    async def __aenter__(self) -> "ToolRegistry":
        await self._stack.__aenter__()
        try:
            self.tools.extend(
                RemoteTool(
                    server=LOCAL_SERVER,
                    name=tool.name,
                    qualified_name=f"{LOCAL_SERVER}{QUALIFIER}{tool.name}",
                    description=tool.description,
                    input_schema=tool.input_schema,
                    read_only=tool.read_only,
                    preview=LOCAL_RENDER if tool.render else None,
                )
                for tool in self._local.values()
            )
            for server in self._servers:
                session = await self._launch(server)
                self._sessions[server.safe_name] = session
                self.tools.extend(await self._describe(server, session))
        except BaseException:
            # Without this, a failure part-way through startup leaves child processes
            # attached to a half-built exit stack and the whole program HANGS instead of
            # reporting the problem. Found the hard way: an AttributeError from a renamed
            # SDK field surfaced as a silent deadlock, not a traceback.
            await self._stack.__aexit__(*sys.exc_info())
            raise
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._stack.__aexit__(*exc)  # type: ignore[arg-type]

    async def _launch(self, server: ToolServer) -> ClientSession:
        params = StdioServerParameters(
            command=server.command,
            args=server.args,
            cwd=server.cwd,
            # The child inherits this process's environment plus whatever tools.yaml adds,
            # which is how credentials and paths reach a tool without it discovering them.
            env=tool_environment(server.env),
        )
        read, write = await self._stack.enter_async_context(stdio_client(params))
        session = await self._stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        return session

    @staticmethod
    async def _describe(server: ToolServer, session: ClientSession) -> list[RemoteTool]:
        listed = await session.list_tools()
        out: list[RemoteTool] = []
        for tool in listed.tools:
            annotations = tool.annotations
            out.append(
                RemoteTool(
                    server=server.safe_name,
                    name=tool.name,
                    qualified_name=f"{server.safe_name}{QUALIFIER}{tool.name}",
                    description=tool.description or "",
                    input_schema=tool.input_schema,
                    # Absent means "not declared safe". Defaulting the other way would let
                    # a tool that forgot to annotate itself past the approval gate.
                    read_only=bool(annotations and annotations.read_only_hint),
                    preview=ApprovalPreview.parse(tool.meta),
                    title=tool.title or (annotations.title if annotations and annotations.title else "") or "",
                )
            )
        return out

    def find(self, qualified_name: str) -> RemoteTool | None:
        return next((t for t in self.tools if t.qualified_name == qualified_name), None)

    def anthropic_tools(self) -> list[dict[str, Any]]:
        return [tool.as_anthropic_tool() for tool in self.tools]

    async def preview_of(self, tool: RemoteTool, arguments: dict[str, Any]) -> str | None:
        """Render what this call would do, by asking the tool the tool named.

        None means "declared a preview and it could not be produced", which the caller must
        surface rather than quietly showing raw arguments as though nothing were missing.
        """
        if tool.server == LOCAL_SERVER:
            local = self._local.get(tool.name)
            if local is None or local.render is None:
                return None
            try:
                return await local.render(arguments)
            except Exception:
                return None  # declared and not produced: the gate says so

        spec = tool.preview
        if spec is None:
            return None

        target = self.find(f"{tool.server}{QUALIFIER}{spec.tool}")
        # A preview that could act would be a hole rather than a help: a tool could name a
        # destructive "preview" and have it run before anyone approved anything.
        if target is None or not target.read_only:
            return None

        arguments_for_preview = {
            parameter: arguments[source]
            for parameter, source in spec.argument_map.items()
            if source in arguments
        }
        outcome = await self.call(target, arguments_for_preview)
        if outcome.is_error:
            return None

        if spec.field is None:
            return outcome.text
        try:
            value = json.loads(outcome.text).get(spec.field)
        except (json.JSONDecodeError, AttributeError):
            return None
        return str(value) if value else None

    async def call(self, tool: RemoteTool, arguments: dict[str, Any]) -> "ToolOutcome":
        """Call a tool and report honestly whether it worked.

        MCP reports a tool's own failure as `isError` on a successful response, not as a
        raised exception. Discarding that flag makes every failure look like a success --
        which is how an audit log ends up recording a build that died on an expired token
        as `ok`, the one thing an audit log must never do.
        """
        if tool.server == LOCAL_SERVER:
            try:
                return ToolOutcome(text=await self._local[tool.name].handler(arguments), is_error=False)
            except Exception as exc:
                return ToolOutcome(text=str(exc), is_error=True)

        async with self.lend(arguments):
            result = await self._sessions[tool.server].call_tool(tool.name, arguments)
        blocks = getattr(result, "content", []) or []
        text = "\n".join(b.text for b in blocks if getattr(b, "type", None) == "text")
        # `is_error`, not `isError`: mcp 2.x exposes snake_case attributes and keeps the
        # camelCase spelling only as a wire alias. Reading the alias off the object returns
        # nothing and silently reports every failure as a success -- the same rename that
        # turned inputSchema into input_schema, and worth checking rather than recalling.
        outcome = ToolOutcome(text=text, is_error=bool(getattr(result, "is_error", False)))
        if not tool.read_only and not outcome.is_error:
            self.changed(tool)
        return outcome
