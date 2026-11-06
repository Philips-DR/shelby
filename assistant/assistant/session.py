"""Classify, call, approve, audit. The whole job.

There is no domain logic here and there must never be any. The assistant does not know what
a timeline is, what a span is, or that Google Docs indexes are UTF-16 code units. It knows
which tools exist and how to ask for approval.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from assistant.approval import Asker, approve, needs_approval
from assistant.audit import AuditStore
from assistant.config import ANTHROPIC, ModelConfig
from assistant.tools import RemoteTool, ToolRegistry

MAX_TOKENS = 16000

# A turn that needs more round trips than this is looping, not working. Twelve was too few the day tailoring
# a CV began to check itself: one request legitimately runs ~25 rounds -- read, match the posting, record the
# user's answers (one gated call each), draft, check the claims, fix, save, build, read the page count, trim
# and rebuild, clear the superseded Docs. Measured live (2026-10-15): it stopped at twelve, mid-trim.
MAX_TOOL_ROUNDS = 30

# What a stopped turn leaves in the conversation, so the next turn knows what happened: the model's own reply
# that was never finished, and each tool it asked for that did not run.
STOPPED_REPLY = "(The user stopped this reply.)"
STOPPED_TOOL = "Not run: the user stopped this reply before it ran."

SYSTEM_PROMPT = """\
You coordinate a small set of local tools on the user's own machine. Each tool does one \
thing well; you decide which to call and with what.

Two habits matter.

Preview before you commit. Several tools ship an operation that costs nothing and writes \
nothing -- a preview, a dry run, a listing. Use it to check your assumptions before calling \
the operation that spends money or creates a file, and tell the user what you found.

Chain rather than improvise. Tools are designed to feed each other: one produces markdown, \
another compiles markdown into a document. If a request spans two tools, call them in turn \
and pass the first one's output path to the second. Never try to do a tool's job yourself.

You cannot read or write files directly, and you have no shell. If something cannot be done \
with the tools available, say so plainly and say what is missing.

Say exactly what you did, and what you did not. If a request asked for more than you did -- \
tailoring, rewriting, checking, sending -- and you only did part of it, say which part, before \
anything else. Never describe a result as something it is not: a document formatted as \
uploaded is not a document tailored for a job.

To change what a document says -- tailor a CV to a role, rewrite a report, shorten notes -- \
read it with read_document, write the new version with write_draft (passing the original as \
based_on), then build that draft. Keep every section of the original unless asked to cut; if \
write_draft reports sections missing, either restore them or say plainly what you left out. \
Work only from the user's own material. Never invent experience, employers, dates, \
qualifications, figures or skills; if the role calls for something the material does not show, \
say so and ask rather than add it. To build a CV, use docu_ai__build with theme "resume".

Do not ask for permission in prose. Every call that writes is intercepted before it runs \
and shown to the user with its exact arguments, to approve or decline. That is the gate; \
asking first as well makes two gates and stalls the work. Say what you are about to do, \
then call the tool and let the user answer the prompt.

If a call comes back saying the user declined, accept it and stop. Do not look for another \
route to the same effect, and do not ask again.

When you learn something durable about the user or their work -- how a name is actually \
spelled, who someone is, a standing preference -- record it. Do not record the contents of \
a meeting or a document; those live in the files the tools produce.\
"""


def system_prompt(context: str = "") -> str:
    """The standing instructions, plus what the assistant knows about this user.

    Memory is appended rather than interleaved so the instructions stay a fixed prefix. It
    is also framed as background rather than instruction, because a remembered line is data
    the user wrote once and not an order that outranks what they are saying now.
    """
    return f"{SYSTEM_PROMPT}\n\n{context}" if context.strip() else SYSTEM_PROMPT


def build_client(config: ModelConfig):
    """Imported lazily so the pure modules stay importable with no SDK and no credentials."""
    if config.provider == ANTHROPIC:
        from anthropic import Anthropic

        return Anthropic(api_key=config.api_key) if config.api_key else Anthropic()

    from anthropic import AnthropicBedrock

    return AnthropicBedrock(aws_region=config.region, aws_profile=config.profile)


def _text_of(content: list[Any]) -> str:
    return "\n".join(b.text for b in content if getattr(b, "type", None) == "text").strip()


@dataclass(frozen=True)
class ApprovalRequest:
    """One call waiting on a person. The same object whether that person is at a terminal
    or looking at a card in a browser -- the gate is what differs, not the question."""

    tool: RemoteTool
    arguments: dict[str, Any]
    preview: str | None
    preview_expected: bool
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


# Async so a web server can suspend a turn on a click. A terminal answers the same question
# synchronously with input(); both satisfy this signature.
Gate = Callable[[ApprovalRequest], Awaitable[bool]]
EventSink = Callable[[dict[str, Any]], Awaitable[None]]


async def _discard(_event: dict[str, Any]) -> None:
    return None


def terminal_gate(ask: Asker = input) -> Gate:
    async def gate(request: ApprovalRequest) -> bool:
        return approve(request.tool, request.arguments, ask, preview=request.preview,
                       preview_expected=request.preview_expected)
    return gate


async def allow_gate(_request: ApprovalRequest) -> bool:
    """For a button press: the click was the approval."""
    return True


async def execute(
    registry: ToolRegistry,
    tool: RemoteTool,
    arguments: dict[str, Any],
    audit: AuditStore,
    gate: Gate,
    emit: EventSink = _discard,
    origin: str = "chat",
) -> tuple[str, str]:
    """Preview, gate, call, audit -- for one tool call. Returns (output, outcome).

    The single path every call takes, whether a model asked for it or a person pressed a
    button. Two paths would drift: the button one would quietly lose the audit row, or the
    preview, the first time someone changed only the other.
    """
    preview = None
    if needs_approval(tool) and tool.preview is not None:
        try:
            # Fetched before asking, not after: the preview is the thing being approved.
            preview = await registry.preview_of(tool, arguments)
        except Exception:
            preview = None  # reported at the gate, never swallowed

    if needs_approval(tool):
        request = ApprovalRequest(tool=tool, arguments=arguments, preview=preview,
                                  preview_expected=tool.preview is not None)
        if not await gate(request):
            await audit.record(tool=tool.qualified_name, arguments=arguments,
                               outcome="declined", origin=origin)
            await emit({"type": "tool_finished", "tool": tool.qualified_name,
                        "outcome": "declined", "origin": origin})
            return "The user declined to run this. Do not attempt it another way.", "declined"

    # A read triggered from the interface is the page looking, not the system acting -- and
    # the panels poll every few seconds. Recording those buried the audit log: a day with a
    # tab open was ~43,000 rows of "recording status: ok" around the few that mattered. The
    # model's reads are still recorded; what it chose to look at is worth knowing.
    quiet = origin == "button" and tool.read_only
    if quiet:
        emit = _discard

    await emit({"type": "tool_started", "tool": tool.qualified_name,
                "arguments": arguments, "origin": origin})
    started = time.monotonic()
    try:
        result = await registry.call(tool, arguments)
        output = result.text
        # A tool that reports its own failure is a failure, even though the call itself
        # returned normally.
        outcome = "failed" if result.is_error else "ok"
        error = result.text if result.is_error else None
    except Exception as exc:  # the transport dying must not end the conversation
        output, outcome, error = f"tool failed: {exc}", "failed", str(exc)

    if not quiet:
        await audit.record(
            tool=tool.qualified_name,
            arguments=arguments,
            outcome=outcome,
            error=error,
            duration_ms=int((time.monotonic() - started) * 1000),
            result=output,
            origin=origin,
        )
    await emit({"type": "tool_finished", "tool": tool.qualified_name, "outcome": outcome,
                "result": output[:2000], "origin": origin, "read_only": tool.read_only})
    return output, outcome


async def run_turn(
    registry: ToolRegistry,
    config: ModelConfig,
    messages: list[dict[str, Any]],
    audit: AuditStore,
    ask: Asker = input,
    context: str = "",
    gate: Gate | None = None,
    emit: EventSink = _discard,
    stop: asyncio.Event | None = None,
) -> str:
    """One user request, through as many tool calls as it takes. Mutates `messages`.

    `gate` decides approvals; without one, a terminal prompt built from `ask` does. `emit`
    receives each step as it happens, which is how a browser watches a turn unfold.

    `stop`, once set, ends the turn at the next safe point: the model's answer still on its way is
    thrown away, and a tool not yet started is not started. A tool already running is never cut off:
    it finishes and is audited, because stopping halfway through a change would leave it done but
    unrecorded. Either way the conversation is left whole -- every tool call answered, the model's
    turn closed with STOPPED_REPLY -- so the next message carries on from it.
    """
    gate = gate or terminal_gate(ask)
    client = build_client(config)
    tools = registry.anthropic_tools()

    for _ in range(MAX_TOOL_ROUNDS):
        if stop is not None and stop.is_set():
            return await _stopped(messages, emit)
        asked = asyncio.ensure_future(asyncio.to_thread(
            client.messages.create,
            model=config.resolved_model,
            max_tokens=MAX_TOKENS,
            system=system_prompt(context),
            # Explicit: on Opus 4.6 omitting this means no thinking at all.
            thinking={"type": "adaptive"},
            tools=tools,
            messages=messages,
        ))
        if stop is not None:
            stopped = asyncio.ensure_future(stop.wait())
            await asyncio.wait({asked, stopped}, return_when=asyncio.FIRST_COMPLETED)
            stopped.cancel()
            if not asked.done():
                # The request's thread runs to its end on its own; what it brings back is not used.
                asked.cancel()
                return await _stopped(messages, emit)
        response = await asked

        # The whole content list, not just the text: thinking and tool_use blocks have to
        # travel back unchanged or the next turn loses the model's own reasoning.
        messages.append({"role": "assistant", "content": response.content})

        text = _text_of(response.content)
        if text:
            await emit({"type": "assistant_text", "text": text})

        if response.stop_reason != "tool_use":
            await emit({"type": "turn_done", "text": text})
            return text

        results: list[dict[str, Any]] = []
        for block in response.content:
            if getattr(block, "type", None) != "tool_use":
                continue

            if stop is not None and stop.is_set():
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": STOPPED_TOOL, "is_error": True})
                continue

            tool = registry.find(block.name)
            if tool is None or tool.interface_only:  # never shown to the model, so a guess at one is refused
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": f"no such tool: {block.name}",
                    "is_error": True,
                })
                continue

            output, outcome = await execute(
                registry, tool, dict(block.input or {}), audit, gate, emit
            )
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": output,
                **({"is_error": True} if outcome == "failed" else {}),
            })

        # Every result in one user message: splitting them teaches the model to stop
        # making parallel calls.
        messages.append({"role": "user", "content": results})

    final = "I stopped after too many tool calls without reaching an answer."
    await emit({"type": "turn_done", "text": final})
    return final


async def _stopped(messages: list[dict[str, Any]], emit: EventSink) -> str:
    """Close the model's turn as stopped. The conversation always ends on the user's side here (their
    message, or the results of the tools just run), so one short reply keeps it alternating as the API
    requires, and tells the model next time that it was cut short rather than leaving it to guess."""
    messages.append({"role": "assistant", "content": [{"type": "text", "text": STOPPED_REPLY}]})
    await emit({"type": "turn_stopped"})
    return STOPPED_REPLY
