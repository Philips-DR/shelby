"""Tell someone when a long job finishes.

The only module in the server that knows a tool by name, the way tools.yaml is the only file
that knows every tool exists. Everything else stays tool-agnostic; if a new tool needs
watching, it gets a watcher here and nowhere else.

It polls through the registry directly rather than through `session.execute`: this is the
server looking, not anyone acting, so it is neither audited nor gated.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Awaitable, Callable

from assistant.tools import ToolRegistry

POLL_SECONDS = 15
FINISHED = {"done", "failed", "interrupted"}

Emit = Callable[[dict[str, Any]], Awaitable[None]]


async def _read(registry: ToolRegistry, name: str) -> dict[str, Any] | None:
    tool = registry.find(name)
    if tool is None:
        return None
    outcome = await registry.call(tool, {})
    if outcome.is_error:
        return None
    try:
        return json.loads(outcome.text)
    except json.JSONDecodeError:
        return None


def transcription_notice(before: str | None, job: dict[str, Any] | None) -> dict[str, Any] | None:
    """What to say when a job changes state, or None. Pure, so it can be tested alone."""
    if not job or before != "running" or job.get("state") not in FINISHED:
        return None
    name = Path(str(job.get("audio", ""))).name
    state = job["state"]
    if state == "done":
        return {"level": "success", "title": "Transcript ready",
                "body": f"{name} is transcribed. Notes can be written from it now."}
    if state == "failed":
        return {"level": "error", "title": "Transcription failed",
                "body": f"{name}: {str(job.get('detail', ''))[:200]}"}
    return {"level": "warning", "title": "Transcription interrupted",
            "body": f"{name} stopped before finishing. Starting it again resumes where it left off."}


def audiobook_notice(before: str | None, job: dict[str, Any] | None) -> dict[str, Any] | None:
    """The same for an audiobook job -- reading a book, rendering it, cloning a voice, a sample."""
    if not job or before != "running" or job.get("state") not in FINISHED:
        return None
    name = Path(str(job.get("target", ""))).name
    kind = job.get("kind")
    state = job["state"]
    if state == "done":
        title, body = {
            "analyse": ("Book read", f"{name} is analysed. Preview it, then choose a voice."),
            "render": ("Audiobook ready", f"{name} is rendered. It is under Audiobooks."),
            "voice": ("Voice cloned", f"The voice from {name} is ready. Listen to a sample before using it."),
            "sample": ("Sample ready", f"A sample of {name} is ready to hear."),
        }.get(kind, ("Audiobook job finished", name))
        return {"level": "success", "title": title, "body": body}
    if state == "failed":
        return {"level": "error", "title": "Audiobook job failed",
                "body": f"{name}: {str(job.get('detail', ''))[:200]}"}
    return {"level": "warning", "title": "Audiobook job interrupted",
            "body": f"{name} stopped before finishing. Starting it again resumes where it left off."}


def recording_notice(before: str | None, session: dict[str, Any] | None) -> dict[str, Any] | None:
    if before == "recording" and session and session.get("state") == "orphaned":
        return {"level": "warning", "title": "Recording interrupted",
                "body": f"{session.get('id')} stopped unexpectedly. Its audio is safe -- stop it to recover."}
    return None


async def watch(registry: ToolRegistry, emit: Emit, on_change: Callable[[str], None] | None = None) -> None:
    """Run until cancelled. A failed poll is skipped, never fatal. `on_change(server)` is told when an audiobook
    job has made something new -- a chapter finished, or the job ended -- so what it made can be kept (collect.py)."""
    job_state: dict[str, str] = {}
    book_state: dict[str, str] = {}
    book_made: dict[str, int] = {}
    recording: str | None = None
    while True:
        try:
            status = await _read(registry, "meet_ai__transcription_status")
            job = (status or {}).get("job")
            if job:
                notice = transcription_notice(job_state.get(job["id"]), job)
                job_state[job["id"]] = job["state"]
                if notice:
                    await emit({"type": "notice", **notice})

            status = await _read(registry, "audiobook__job_status")
            job = (status or {}).get("job")
            if job:
                notice = audiobook_notice(book_state.get(job["id"]), job)
                changed = (job["id"] in book_state and book_state[job["id"]] != job["state"]) \
                    or book_made.get(job["id"], 0) < len(job.get("outputs") or [])
                book_state[job["id"]] = job["state"]
                book_made[job["id"]] = len(job.get("outputs") or [])
                if notice:
                    await emit({"type": "notice", **notice})
                if changed and on_change is not None:
                    on_change("audiobook")

            rec = await _read(registry, "meet_ai__recording_status")
            session = (rec or {}).get("session")
            notice = recording_notice(recording, session)
            recording = session.get("state") if session else None
            if notice:
                await emit({"type": "notice", **notice})
        except asyncio.CancelledError:
            raise
        except Exception:
            pass  # the next poll will try again
        await asyncio.sleep(POLL_SECONDS)


# ---------------------------------------------------------------------------
# The model login
# ---------------------------------------------------------------------------

LOGIN_POLL_SECONDS = 600
# While a login is out the person is on their way to fix it: look again soon enough that the page notices.
LOGIN_RECHECK_SECONDS = 60


def login_notice(before: str | None, status: dict[str, Any]) -> dict[str, Any] | None:
    """Announce the model login going bad, once. The SSO access token renews itself from a
    refresh token, so a countdown to its expiry time would be wrong; the honest signal is
    the moment a live check first fails."""
    if status.get("level") == "error" and before != "error":
        title = ("The Anthropic API key was refused" if status.get("key_refused")
                 else "The model is not available to this key" if status.get("model_missing")
                 else "AWS login needs renewing")
        return {"level": "error", "title": title,
                "body": status.get("hint") or str(status.get("detail", ""))[:200]}
    if status.get("level") == "ok" and before == "error":
        return {"level": "success", "title": "AWS login working again",
                "body": "Notes and minutes can be written."}
    return None


async def watch_login(logins: Any) -> None:
    """Check every login now, then every ten minutes -- every minute while one is out. `logins` is
    `assistant.logins.Logins`, which also does the announcing."""
    while True:
        try:
            await logins.check()
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(LOGIN_RECHECK_SECONDS if logins.needs_attention() else LOGIN_POLL_SECONDS)
