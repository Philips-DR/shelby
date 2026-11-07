"""Making a render's pieces two at a time (2026-11-06, the user's choice after hearing no difference in 8-bit).

Pocket TTS pins itself to one processor thread, so one render left most of this laptop idle. Measured with abigail in
8-bit: one copy 2.0x real time; two copies at once 1.42x each, 2.84x in all; three 0.96x each, 2.89x in all (the
memory bus, not the cores, is the limit by then); about 0.85 GB a copy. So on the processor a render makes a chapter's
missing pieces in two worker processes, each with its own model (Pocket TTS is not thread-safe), and render.py puts the
chapter together in order from the chunk cache afterwards. One worker on an NVIDIA card, or when memory is short;
AUDIOBOOK_RENDER_WORKERS names another number.

While the chat page is reading a reply aloud (speaking.py touches SPEAKING_MARK), a render makes one piece at a time:
three copies at once slowed each to 0.96x real time, the edge of a reply stuttering.
"""

from __future__ import annotations

import os
import sys
import time
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from multiprocessing import get_context
from pathlib import Path
from typing import Iterator

import numpy as np

SPEAKING_MARK = Path(".cache/speaking")
SPEAKING_RECENT_S = 30
DEFAULT_WORKERS = 2
GB_PER_WORKER = 1.2  # 0.85 GB measured, with room for the voice and the process around it


def chat_is_speaking(mark: Path = SPEAKING_MARK, now: float | None = None) -> bool:
    try:
        return (now if now is not None else time.time()) - mark.stat().st_mtime < SPEAKING_RECENT_S
    except OSError:
        return False


def plan_workers(gpu: bool, available_gb: float, setting: str | None) -> tuple[int, str]:
    """How many pieces a render makes at once, and why, in words for the job's log."""
    if setting:
        try:
            n = max(1, int(setting))
            return n, f"{n} piece{'s' if n > 1 else ''} at a time (AUDIOBOOK_RENDER_WORKERS)"
        except ValueError:
            pass
    if gpu:
        return 1, "one piece at a time, on the GPU"
    n = max(1, min(DEFAULT_WORKERS, int(available_gb // GB_PER_WORKER)))
    if n < DEFAULT_WORKERS:
        return n, f"one piece at a time: only {available_gb:.1f} GB of memory free"
    return n, f"{n} pieces at a time"


def workers_here() -> tuple[int, str]:
    import psutil

    from .tts import eight_bit_here

    return plan_workers(not eight_bit_here(), psutil.virtual_memory().available / 1024**3,
                        os.environ.get("AUDIOBOOK_RENDER_WORKERS"))


# In each worker process: its own voice, loaded once.
_narrator = None


def _start(voice: str) -> None:
    global _narrator
    from .tts import Narrator

    _narrator = Narrator(voice)
    _narrator.state  # load the model and the voice now, not on the first piece
    sys.stdout.flush()  # a worker's "Loading Pocket TTS..." otherwise reached the job's log only when the render ended


def _speak(text: str) -> tuple[str, np.ndarray]:
    assert _narrator is not None
    return text, _narrator.synthesize(text).astype(np.float32)


class WorkerPool:
    """Worker processes that each speak in `voice` (a saved voice's file or a preset's name)."""

    def __init__(self, voice: str, workers: int, mark: Path = SPEAKING_MARK):
        self.workers = workers
        self.mark = mark
        # spawn, not fork: a forked copy of a process that has loaded torch can hang.
        self._pool = ProcessPoolExecutor(max_workers=workers, mp_context=get_context("spawn"),
                                         initializer=_start, initargs=(voice,))

    def generate(self, texts: list[str]) -> Iterator[tuple[str, np.ndarray, float]]:
        """Each text's audio as it is made, with the wall time since the one before (what the time left is worked
        out from). As many at once as there are workers; one while the chat page is reading a reply."""
        queue = list(texts)
        running: set[Future] = set()
        last = time.monotonic()
        while queue or running:
            limit = 1 if chat_is_speaking(self.mark) else self.workers
            while queue and len(running) < limit:
                running.add(self._pool.submit(_speak, queue.pop(0)))
            done, running = wait(running, return_when=FIRST_COMPLETED)
            for future in done:
                text, audio = future.result()
                now = time.monotonic()
                yield text, audio, now - last
                last = now

    def close(self) -> None:
        self._pool.shutdown(wait=True, cancel_futures=True)
