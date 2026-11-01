"""audiobook's second front door: the same operations the CLI runs, reachable by a model.

Both doors sit directly on operations.py; neither wraps the other. Long work -- Docling reading
a book, a render, cloning a voice -- starts as a background job and returns at once with an id;
`job_status` is how anyone, a model or the suite's web app, watches it.

Where jobs are kept is injected (AUDIOBOOK_JOBS), like the paths in the other tools' doors. The
tool's own data (output/, voices/, .cache/) is relative to the folder it runs from, and ./mcp
runs it from there.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from . import keeping, operations
from .background import ROOT, JobError

VERSION = "0.1.0"
FAILURES = (ValueError, FileNotFoundError, FileExistsError, OSError, JobError)


@dataclass(frozen=True)
class ServerPaths:
    """Where this server keeps its jobs. Supplied by the caller, never assumed."""

    jobs_dir: Path


def _failed(error: Exception) -> dict:
    return {"error": str(error)}


READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)
DESTROY = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False)


def approval_preview(preview_tool: str, argument_map: dict[str, str], field: str | None = None) -> dict:
    """Declare, in MCP's `_meta`, which read-only tool on this server shows what a destructive one will do, so
    an approval prompt can show that instead of a bare name. (A copy of mail-ai's, not an import: tools do not
    import each other.) A caller that honours it must check the named tool is read-only."""
    return {"approval": {"preview_tool": preview_tool, "argument_map": argument_map, **({"field": field} if field else {})}}


def create_audiobook_server(paths: ServerPaths) -> MCPServer:
    server = MCPServer(name="audiobook", version=VERSION)

    @server.tool(
        name="list_voices",
        title="List the voices",
        description=(
            "Every voice a book can be read in: the cloned ones saved on this machine (with the "
            "recording they came from, how closely they match it, and who agreed to the cloning) "
            "and the built-in presets. Reads only."
        ),
        annotations=READ,
    )
    def _list_voices() -> dict:
        try:
            return {"voices": operations.voice_choices()}
        except FAILURES as error:
            return _failed(error)

    @server.tool(
        name="list_audiobooks",
        title="List finished audio",
        description=(
            "Every book that has audio on disk -- chapter MP3s and M4B audiobooks -- with its title and "
            "author and each file's path and size, newest first. Call a book by its title; `book` is its "
            "folder's name (the PDF's file name), which describe_audiobook and delete_audiobook take. Reads only."
        ),
        annotations=READ,
    )
    def _list_audiobooks() -> dict:
        try:
            return {"audiobooks": operations.list_audiobooks()}
        except FAILURES as error:
            return _failed(error)

    @server.tool(
        name="describe_audiobook",
        title="What is stored for a book",
        description=(
            "The files stored for one book in the output folder -- names and sizes -- and whether a render or "
            "reading of it is running. Takes the book's name exactly as list_audiobooks gives it, never a path. "
            "This is what the approval for delete_audiobook shows. Reads only."
        ),
        annotations=READ,
    )
    def _describe_audiobook(book: str) -> dict:
        try:
            return operations.describe_audiobook(book, paths.jobs_dir)
        except FAILURES as error:
            return _failed(error)

    @server.tool(
        name="delete_audiobook",
        title="Delete a book's audio",
        description=(
            "Delete the finished audio and working files of one book (its folder in the output folder), by the "
            "name list_audiobooks gives, never a path. Cannot be undone. Does NOT delete the uploaded PDF, any "
            "voice, or the shared reading and speech caches, and refuses while that book is being read or "
            "rendered. Only when the user asked to delete that book's audio."
        ),
        annotations=DESTROY,
        meta=approval_preview("describe_audiobook", {"book": "book"}, field="summary"),
    )
    def _delete_audiobook(book: str) -> dict:
        try:
            return operations.delete_audiobook(book, paths.jobs_dir)
        except FAILURES as error:
            return _failed(error)

    @server.tool(
        name="preview_book",
        title="Preview what would be read aloud",
        description=(
            "A PDF's chapters as they would be narrated: number, title, words, length of speech, "
            "and how long the render would take, with what was left out (tables, formulas, "
            "citations, page furniture, the book's own contents page) counted by reason, and each chapter's "
            "finished audio, if it has been rendered (`other_audio`: the whole-book .m4b, and files from an "
            "earlier reading whose chapters were found differently). The chapter numbers are what "
            "start_render's `chapters` takes. Instant once the PDF has been analysed; if it has "
            "not, it says analysed=false and start_analysis is the next step. Reads only."
        ),
        annotations=READ,
    )
    def _preview_book(pdf: str) -> dict:
        try:
            return operations.book_overview(operations.pdf_file(pdf))
        except FAILURES as error:
            return _failed(error)

    @server.tool(
        name="read_chapter",
        title="Read a chapter's narrated text",
        description=(
            "The exact text the voice will speak for one chapter, as segments (title, heading, "
            "paragraph, list item) after every cleaning rule and correction. Use it to answer "
            "'what will it say here?' or to find something the voice would misread. A long "
            "chapter comes back truncated=true with next_start set: call again with start="
            "next_start for the rest. Needs an analysed PDF. Reads only."
        ),
        annotations=READ,
    )
    def _read_chapter(pdf: str, chapter: int, start: int = 0) -> dict:
        try:
            return operations.chapter_text(operations.pdf_file(pdf), chapter, start)
        except FAILURES as error:
            return _failed(error)

    @server.tool(
        name="get_corrections",
        title="Read a book's corrections",
        description=(
            "The book's corrections file: `find => replace` lines applied to its text before it "
            "is read aloud, for typos in the source or names the voice cannot say. Empty if the "
            "book has none. Reads only."
        ),
        annotations=READ,
    )
    def _get_corrections(pdf: str) -> dict:
        try:
            return operations.get_corrections(operations.pdf_file(pdf))
        except FAILURES as error:
            return _failed(error)

    @server.tool(
        name="set_corrections",
        title="Replace a book's corrections",
        description=(
            "Replace the book's whole corrections file with `text`: one `find => replace` per "
            "line, blank lines and # comments ignored. Read the current text with "
            "get_corrections first and send it back with the change, or the old lines are lost. "
            "Lines without => are not applied and come back in `ignored`. Takes effect on the next "
            "preview or render; chunks already spoken stay cached and only changed text is "
            "re-read. Writes a file next to the PDF."
        ),
        annotations=WRITE,
    )
    def _set_corrections(pdf: str, text: str) -> dict:
        try:
            return operations.set_corrections(operations.pdf_file(pdf), text)
        except FAILURES as error:
            return _failed(error)

    @server.tool(
        name="start_analysis",
        title="Read a PDF in the background",
        description=(
            "Run layout analysis over a PDF (Docling) in the background and return at once with a "
            "job id: about 2-4 seconds a page, so minutes for a book, and slower for a scan, which "
            "is read with OCR. It is the first step for any new PDF; preview_book, read_chapter "
            "and start_render all work from its cached result. Check on it with job_status. One "
            "job runs at a time."
        ),
        annotations=WRITE,
    )
    def _start_analysis(pdf: str) -> dict:
        try:
            return operations.start_analysis(operations.pdf_file(pdf), paths.jobs_dir)
        except FAILURES as error:
            return _failed(error)

    @server.tool(
        name="start_render",
        title="Render an audiobook in the background",
        description=(
            "Narrate an analysed PDF in a chosen voice, in the background, and return at once with "
            "a job id. This is hours of CPU for a whole book -- about the length of the speech "
            "divided by 1.4 (preview_book reports it) -- and every sentence spoken is cached, so a "
            "stopped or interrupted render started again loses nothing, and a different `speed` "
            "re-encodes in seconds. `chapters` selects by the numbers preview_book shows, e.g. "
            "'1-3,5' (default all); `speed` is 0.5-2.0 (default 0.95, pitch unchanged); `m4b` also "
            "builds one audiobook file with chapter markers. Writes MP3s under this tool's output "
            "folder. One job runs at a time."
        ),
        annotations=WRITE,
    )
    def _start_render(pdf: str, voice: str, chapters: str | None = None,
                      speed: float = operations.DEFAULT_SPEED, m4b: bool = False) -> dict:
        try:
            return operations.start_render(operations.pdf_file(pdf), voice, paths.jobs_dir,
                                           chapters=chapters, speed=speed, m4b=m4b)
        except FAILURES as error:
            return _failed(error)

    @server.tool(
        name="start_voice_clone",
        title="Clone a voice from a recording",
        description=(
            "Clone a voice from an audio recording, in the background, and return at once with a "
            "job id; it tries several 30-second windows of a long recording and keeps the best "
            "match, which takes a minute or more. ONLY for a voice the user owns or whose "
            "speaker has agreed: `consent` must be the user's own statement of whose voice it is "
            "and that they agreed -- ask for it, never write it yourself. It is kept with the "
            "voice. Name: lowercase letters, digits, - and _. Afterwards hear it with "
            "start_voice_sample before rendering anything in it."
        ),
        annotations=WRITE,
    )
    def _start_voice_clone(name: str, recording: str, consent: str, overwrite: bool = False) -> dict:
        try:
            return operations.start_voice_clone(name, Path(recording).expanduser().resolve(),
                                                consent, paths.jobs_dir, overwrite)
        except FAILURES as error:
            return _failed(error)

    @server.tool(
        name="start_voice_sample",
        title="Hear a voice read a sample",
        description=(
            "Have a voice read a short sample paragraph, in the background, and return at once with "
            "a job id; about half a minute. The MP3's path is in the finished job's outputs. A "
            "cheap way to judge a voice before committing hours to a render."
        ),
        annotations=WRITE,
    )
    def _start_voice_sample(voice: str, speed: float = operations.DEFAULT_SPEED) -> dict:
        try:
            return operations.start_voice_sample(voice, paths.jobs_dir, speed)
        except FAILURES as error:
            return _failed(error)

    @server.tool(
        name="cancel_job",
        title="Stop the running job",
        description=(
            "Stop the audiobook job that is running (or the one named by job_id) and return it with "
            "state cancelled. For a render nothing is lost: every sentence already spoken is kept, so "
            "start_render with the same arguments carries on from there. Reading a book or cloning a "
            "voice starts over if run again, and a cloned voice that was not finished is not saved. "
            "Use it when the user says the wrong book, voice or chapters were started, or wants the "
            "computer back. Errors if nothing is running."
        ),
        annotations=WRITE,
    )
    def _cancel_job(job_id: str | None = None) -> dict:
        try:
            return {"job": operations.cancel_job(paths.jobs_dir, job_id)}
        except FAILURES as error:
            return _failed(error)

    @server.tool(
        name="job_status",
        title="How is the job getting on?",
        description=(
            "State of an audiobook job -- running, done, failed, interrupted or cancelled -- with its kind "
            "(analyse, render, voice, sample), its phase, percent, the chapter being spoken and "
            "the time left while it runs, and the files it made once it is done. Pass a job id, or "
            "omit it for the most recent. An interrupted render can be started again and resumes "
            "where it stopped. Reads only."
        ),
        annotations=READ,
    )
    def _job_status(job_id: str | None = None) -> dict:
        try:
            return {"job": operations.job_status(paths.jobs_dir, job_id)}
        except FAILURES as error:
            return _failed(error)

    # The suite's two agreed names (its layer 1b): what is worth keeping, and letting go of it once kept. Neither is
    # for a conversation; keeping.py says what each hands over.
    @server.tool(
        name="inventory",
        title="What there is to keep",
        description=(
            "For the suite, not for answering a person: every finished file and record this tool holds that is "
            "worth keeping -- chapter audio with the exact text it speaks, whole-book M4Bs, voice samples, voices, "
            "corrections, finished jobs -- each labelled (book, chapter number and title, speed, voice). The suite "
            "files them in its own store. To say what has been rendered, ask the suite what it keeps. Reads only."
        ),
        annotations=READ,
    )
    def _inventory() -> dict:
        try:
            return keeping.inventory(paths.jobs_dir)
        except FAILURES as error:
            return _failed(error)

    @server.tool(
        name="release",
        title="Let go of audio the suite has kept",
        description=(
            "For the suite only, never because a person asked: delete this tool's working copies of finished audio "
            "the suite has already filed, each named by its path and the SHA-256 of the copy filed. Anything whose "
            "hash differs, or that is not finished audio in this tool's output folder, is kept and said so. To "
            "delete a book's audio, a person uses the Audiobooks page."
        ),
        annotations=DESTROY,
    )
    def _release(files: list[dict]) -> dict:
        try:
            return keeping.release(files)
        except FAILURES as error:
            return _failed(error)

    return server


def main() -> None:
    """The one place this entry point reaches for the environment, named so it is visible."""
    paths = ServerPaths(jobs_dir=Path(os.environ.get("AUDIOBOOK_JOBS", ROOT / ".jobs")))
    create_audiobook_server(paths).run(transport="stdio")


if __name__ == "__main__":
    main()
