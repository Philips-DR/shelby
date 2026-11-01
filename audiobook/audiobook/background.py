"""Analysing, rendering and cloning as background jobs.

A render of a whole book is hours of CPU, Docling's first look at a long one is minutes, and
cloning a voice searches a recording for its best 30 seconds; no request/response protocol
stays open that long. A job returns at once with an id; the work
runs as a detached `python -m audiobook ...` process; `refresh` reads its progress back from
its log. Nothing blocks, so nothing needs a cap.

Detached on purpose: the process belongs to nobody, so restarting whatever started it (the
assistant, or the MCP door) does not kill it. And if it does die -- the machine sleeps, a
reboot -- starting the same render again loses nothing, because every spoken chunk is cached
(CLAUDE.md, render.py): the job picks up where the cache ends.

Same shape as meet-ai's transcription jobs, deliberately, but not shared with them: no tool
imports another. State is a JSON file and a log per job; a pid is checked against /proc before
anyone believes it, since a pid left over from before a reboot can belong to anything.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
START_CONFIRM_SECONDS = 2.0

# Checking that nothing is running and then launching must not be interleaved with another call
# doing the same, or two jobs start. The MCP door is one process, so a lock here is enough.
_START = threading.Lock()

# The job runs as `bash -c WRAPPER JOB_MARKER python -u -m audiobook ...`. The wrapper's only
# job is to write the exit status into the log: it tells a crash from a finish from a kill
# without guessing from what the log happens to contain.
JOB_MARKER = "audiobook-job"
WRAPPER = '"$@"; status=$?; echo; echo "[exit $status]"'

# The CLI's own output (__main__): render's progress line, its per-chapter and per-book lines,
# voice add's per-window lines, and the sample voice test writes.
# Parsed rather than re-implemented: the log is the process's own account of where it is.
PROGRESS = re.compile(
    # The counts are the ones followed by the time left or the end of the line -- not a "2/3" that
    # happens to be inside the chapter's title.
    r"\[\s*(\d+)%\]\s+chapter\s+(\d+):\s+(.*?)\s+(\d+)/(\d+)(?=\s+·|\s*(?:\r|\n|$))"
    r"(?:\s+·\s+~(\S+)\s+left)?"
)
CHAPTER_FILE = re.compile(r"->\s+(\S.*?\.mp3)\s+\(")
BOOK_FILE = re.compile(r"^Audiobook:\s+(\S.*)$", re.MULTILINE)
SAMPLE_FILE = re.compile(r"^Sample:\s+(\S.*)$", re.MULTILINE)
WINDOW = re.compile(r"window\s+(\d+)/(\d+)")
EXIT = re.compile(r"\[exit (\d+)\]")


class JobError(Exception):
    """Something the caller can act on, phrased for whoever is reading."""


@dataclass
class Job:
    id: str
    kind: str  # "analyse" | "render" | "voice" | "sample"
    target: str  # what it works on: a PDF, a recording, or a voice's name
    log: str
    started_at: str
    pid: int | None = None
    arguments: list[str] = field(default_factory=list)
    state: str = "running"  # running | done | failed | interrupted | cancelled
    phase: str = ""
    percent: float | None = None
    chapter: int | None = None
    chapter_title: str | None = None
    chunks_done: int | None = None
    chunks_total: int | None = None
    eta: str | None = None  # time left, as the render prints it: h:mm:ss
    outputs: list[str] = field(default_factory=list)
    detail: str = ""
    title: str | None = None  # the book as a person names it, for a page to show; `target` is the file


def _job_file(jobs_dir: Path, job_id: str) -> Path:
    return Path(jobs_dir) / f"{job_id}.json"


def _cancel_marker(jobs_dir: Path, job_id: str) -> Path:
    return Path(jobs_dir) / f"{job_id}.cancel"


# What a person is told, per kind, once a job has been stopped on request: what survived.
CANCELLED = {
    "render": "stopped on request. Every sentence already spoken is kept, so starting the same render "
              "again carries on from there.",
    "analyse": "stopped on request. Nothing was kept from this reading; starting it again begins "
               "again.",
    "voice": "stopped on request. The voice was not saved; nothing else changed.",
    "sample": "stopped on request.",
}
STOP_WAIT_SECONDS = 5.0


def _save(jobs_dir: Path, job: Job) -> None:
    _job_file(jobs_dir, job.id).write_text(json.dumps(asdict(job), indent=2), encoding="utf-8")


def _load(path: Path) -> Job | None:
    try:
        return Job(**json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def _group_members(pgid: int):
    """(state, argv) of every process in a process group. The job runs in a session of its own, so
    its group is the wrapper, the Python it started, and whatever that started in turn (ffmpeg)."""
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text().rsplit(")", 1)[-1].split()  # state, ppid, pgrp, ...
            if int(stat[2]) != pgid:
                continue
            argv = [a.decode(errors="replace") for a in (entry / "cmdline").read_bytes().split(b"\0")]
        except (OSError, ValueError, IndexError):  # it exited while we looked
            continue
        yield stat[0], argv


def is_our_job(pid: int | None, target: str) -> bool:
    """Is our job still running? That is: is anything alive in its process group that names this
    target? Not "is the wrapper alive": if only the wrapper is killed, the render underneath it
    carries on, and calling that "interrupted" would let a second render start beside it.

    A pid left over from before a reboot can belong to anything, so a member only counts if it
    names the target and is part of ours (the wrapper's marker, or `python -m audiobook`)."""
    if not pid:
        return False
    return any(
        state != "Z" and target in argv and (JOB_MARKER in argv or "audiobook" in argv)  # Z: finished
        for state, argv in _group_members(pid)
    )


def _group_alive(pgid: int) -> bool:
    """Is any process left in the group, of any name? What a cancel must wait for."""
    return any(state != "Z" for state, _ in _group_members(pgid))


def _reap(pid: int | None) -> None:
    if not pid:
        return
    try:
        os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        pass


def read_progress(kind: str, log_text: str) -> dict:
    """Where the job is, from its own log. Progress lines are rewritten in place with carriage
    returns, so the log is one long line of overwritten updates; the LAST match is current."""
    matches = PROGRESS.findall(log_text)
    if matches:
        percent, chapter, title, done, total, eta = matches[-1]
        return {"phase": "rendering", "percent": float(percent), "chapter": int(chapter),
                "chapter_title": title.strip(), "chunks_done": int(done), "chunks_total": int(total),
                "eta": eta or None}
    if kind == "analyse":
        return {"phase": "analysing", "percent": None}
    if kind == "voice":
        windows = WINDOW.findall(log_text)
        if windows:
            done, total = windows[-1]
            return {"phase": "cloning: trying windows of the recording", "percent": round(100 * int(done) / int(total))}
        return {"phase": "cloning the voice", "percent": None}
    if kind == "sample":
        return {"phase": "speaking a sample", "percent": None}
    if "Loading Pocket TTS" in log_text:
        return {"phase": "loading the voice model", "percent": None}
    return {"phase": "starting", "percent": None}


def _outputs(log_text: str) -> list[str]:
    """Files the job reported making, as absolute paths. They are printed relative to the tool's
    folder, which is where the job ran."""
    files = CHAPTER_FILE.findall(log_text) + BOOK_FILE.findall(log_text) + SAMPLE_FILE.findall(log_text)
    return [str((ROOT / f).resolve()) for f in files]


def _log_tail(path: Path, limit: int = 400) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = [line for line in text.replace("\r", "\n").splitlines() if line.strip()]
    return "\n".join(lines[-6:])[-limit:]


def refresh(jobs_dir: Path, job: Job) -> Job:
    """Bring a job's state up to date from its process and its log."""
    # All four are final: a job with no process cannot come back. Re-reading an interrupted one on
    # every poll used to re-save it, which is what the file's timestamp -- and so its age -- recorded.
    if job.state in ("done", "failed", "interrupted", "cancelled"):
        return job

    # Alive FIRST, log second. The other way round, a process that wrote "[exit 0]" and exited
    # between the two reads looks gone with no exit line in the text already read -- and a job that
    # finished is recorded as interrupted for good. Once the process is gone its log is final.
    alive = is_our_job(job.pid, job.target)
    log = Path(job.log)
    text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    for name, value in read_progress(job.kind, text).items():
        setattr(job, name, value)
    job.outputs = _outputs(text)

    if alive:
        job.state = "running"
        return job

    _reap(job.pid)
    finished = EXIT.findall(text)
    if finished and finished[-1] == "0":
        job.state, job.phase, job.percent, job.eta, job.detail = "done", "done", 100.0, None, ""
    elif finished:
        job.state = "failed"
        job.detail = _log_tail(log)
    elif _cancel_marker(jobs_dir, job.id).exists():
        # Someone asked for this to stop, and the marker was written BEFORE the process was killed,
        # so whichever poll first notices it gone gets this right instead of calling it interrupted.
        job.state = "cancelled"
        job.detail = CANCELLED[job.kind]
    else:
        # Gone without reporting an exit status: killed, or the machine slept or rebooted.
        job.state = "interrupted"
        job.detail = ("the job stopped before finishing. Starting the same render again resumes "
                      "from the last chunk that was spoken, so nothing done is lost.")
    _save(jobs_dir, job)
    return job


def _all(jobs_dir: Path) -> list[Job]:
    folder = Path(jobs_dir)
    if not folder.is_dir():
        return []
    # By name, not by timestamp: ids start with the second the job began, so this is the order they
    # started in, and nothing that touches a file can reorder them.
    return [j for j in (_load(p) for p in sorted(folder.glob("*.json"))) if j]


def history(jobs_dir: Path) -> list[Job]:
    """Every job, oldest first, as last saved (not refreshed: a finished one does not change)."""
    return _all(jobs_dir)


def current(jobs_dir: Path) -> Job | None:
    """The job that is still running, refreshed, if any."""
    for job in reversed(_all(jobs_dir)):
        refreshed = refresh(jobs_dir, job)
        if refreshed.state == "running":
            return refreshed
    return None


def get(jobs_dir: Path, job_id: str) -> Job:
    job = _load(_job_file(jobs_dir, job_id))
    if job is None:
        raise JobError(f"no audiobook job {job_id}")
    return refresh(jobs_dir, job)


def latest(jobs_dir: Path) -> Job | None:
    jobs = _all(jobs_dir)
    return refresh(jobs_dir, jobs[-1]) if jobs else None


def cancel(jobs_dir: Path, job_id: str | None = None) -> Job:
    """Stop the running job (or the named one) and return it, finished.

    The whole process group goes: the job runs in its own session, so this reaches the voice model,
    Docling and any ffmpeg underneath it, and nothing is left burning CPU. SIGTERM first, SIGKILL if
    it is still there after a few seconds. Nothing already done is lost -- see CANCELLED.
    """
    jobs_dir = Path(jobs_dir)
    with _START:  # a start must not slip in between "nothing is running" and the kill
        job = get(jobs_dir, job_id) if job_id else current(jobs_dir)
        if job is None:
            raise JobError("nothing is running")
        if job.state != "running":
            raise JobError(f"job {job.id} is already {job.state}")

        # The marker first: once the process is gone, any poll must be able to tell cancelled from
        # interrupted, and it cannot if the answer is only written after the kill.
        _cancel_marker(jobs_dir, job.id).write_text(datetime.now().isoformat(timespec="seconds"))
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(job.pid, sig)  # the job is its own session, so its pid is its group
            except ProcessLookupError:
                break
            deadline = time.monotonic() + STOP_WAIT_SECONDS
            # Wait for the GROUP to empty, not just the wrapper: a member that ignores SIGTERM
            # outlives the wrapper, and the job must not be called stopped while it burns CPU.
            while time.monotonic() < deadline and _group_alive(job.pid):
                time.sleep(0.1)
            if not _group_alive(job.pid):
                break
        return refresh(jobs_dir, job)


def start(kind: str, target: str, jobs_dir: Path, arguments: list[str],
          command: list[str] | None = None, title: str | None = None) -> Job:
    """Launch `python -m audiobook <arguments>` in the background and return at once. `target`
    must appear among the arguments verbatim: it is how a live process is recognised as ours.

    One at a time. Docling and the voice model each use every core this machine has; a second
    job would halve the speed of both and finish neither sooner.

    `command` exists so tests can substitute a stand-in for the real thing.
    """
    with _START:
        return _start(kind, target, Path(jobs_dir), arguments, command, title)


def _unique_id(jobs_dir: Path, kind: str) -> str:
    base = datetime.now().strftime("%Y%m%d-%H%M%S-%f") + "-" + kind
    job_id, n = base, 1
    while _job_file(jobs_dir, job_id).exists():  # two jobs in one second must not share a log
        n += 1
        job_id = f"{base}-{n}"
    return job_id


def _start(kind: str, target: str, jobs_dir: Path, arguments: list[str], command: list[str] | None,
           title: str | None = None) -> Job:
    jobs_dir.mkdir(parents=True, exist_ok=True)

    running = current(jobs_dir)
    if running is not None:
        verb = {"render": "rendering", "analyse": "analysing", "voice": "cloning a voice from",
                "sample": "speaking a sample of"}[running.kind]
        raise JobError(
            f"job {running.id} is still {verb} {Path(running.target).name}"
            + (f" ({running.percent:.0f}%)" if running.percent is not None else "")
            + ". One at a time: a second would slow both down."
        )

    job_id = _unique_id(jobs_dir, kind)
    log = jobs_dir / f"{job_id}.log"
    invocation = command or ["bash", "-c", WRAPPER, JOB_MARKER,
                             sys.executable, "-u", "-m", "audiobook", *arguments]
    with open(log, "w", encoding="utf-8") as handle:
        process = subprocess.Popen(
            invocation, cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=handle,
            stderr=subprocess.STDOUT, start_new_session=True,
        )

    job = Job(id=job_id, kind=kind, target=target, log=str(log), pid=process.pid, title=title,
              arguments=arguments, started_at=datetime.now().isoformat(timespec="seconds"))
    _save(jobs_dir, job)

    # A bad argument or a missing dependency makes the process exit at once. Say so now, rather
    # than letting the caller poll a job that was dead before its id was returned.
    deadline = time.monotonic() + START_CONFIRM_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return refresh(jobs_dir, job)
        time.sleep(0.1)
    return refresh(jobs_dir, job)
