"""Reading and drafting documents: the assistant's own tools for what the user uploaded.

Found testing: asked to "create a CV for an ML engineer role" from an uploaded résumé, the
assistant could only format the file as uploaded -- it had no way to read a document's words or
write a new version -- and its reply read as though it had tailored one. These two tools close
that: read what was uploaded, and write a new draft beside it.

They live here, not behind an MCP door, because stored documents are the assistant's own state, like
memory: the text is written by the model, and the tool only reads and files it. The text is in the
database (files.py); these tools read and write it there, and a path is how a document is named.

- A draft is always a NEW document, recorded as made by the assistant. Nothing an upload, or an
  earlier draft, holds is ever overwritten -- so the original is always there to compare against.
- Writing passes the approval gate, and the gate shows the draft itself, rendered, not a JSON
  string: a person approves what they have read.
- Reads are confined to stored documents. The model is handed paths by uploads and by these
  tools; it has no business reading anything else on the machine.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from assistant import files, texts
from assistant import uploads as up
from assistant.files import FileIndex, StoredFile
from assistant.tools import LocalTool

MAX_READ_CHARS = 200_000
MAX_DRAFT_CHARS = 200_000


async def _find(root: Path, index: FileIndex, path: str) -> tuple[Path, str]:
    if not texts.is_under(root, path):
        raise up.UploadError("only uploaded documents can be read")
    found = await texts.find_text(root, index, path)
    if found is None:
        raise up.UploadError(f"no markdown file at {path}")
    return found


async def _read(root: Path, index: FileIndex, arguments: dict[str, Any]) -> str:
    try:
        target, text = await _find(root, index, str(arguments.get("path", "")))
    except up.UploadError as error:
        return json.dumps({"error": str(error)})
    return json.dumps({"path": str(target), "text": text[:MAX_READ_CHARS],
                       "truncated": len(text) > MAX_READ_CHARS}, ensure_ascii=False)


async def _write(root: Path, index: FileIndex, arguments: dict[str, Any]) -> str:
    title = str(arguments.get("title", "")).strip()
    markdown = str(arguments.get("markdown", ""))
    if not markdown.strip():
        return json.dumps({"error": "the draft is empty"})
    if len(markdown) > MAX_DRAFT_CHARS:
        return json.dumps({"error": f"the draft is longer than {MAX_DRAFT_CHARS} characters"})
    if "\x00" in markdown:
        return json.dumps({"error": "the draft holds a NUL character, which no document does"})
    try:
        name = up.document_name(title or "Draft")
    except up.UploadError as error:
        return json.dumps({"error": str(error)})
    draft = {f"{name}.md": markdown if markdown.endswith("\n") else markdown + "\n"}
    sha256, size = files.texts_digest(draft)
    record = StoredFile(id=files.new_id(), kind="docs", name=name, bytes=size, sha256=sha256,
                        made_by="assistant", created=time.time())
    await index.add(record, draft)
    target = texts.path_for(root, record, list(draft))
    result: dict[str, Any] = {"path": str(target), "title": name, "characters": len(markdown)}
    source = await _source(root, index, arguments)
    if source is not None:
        # Told to the model too, so its reply can say what was cut instead of claiming nothing was.
        result["compared_with_original"] = compare(source, markdown)
    return json.dumps(result, ensure_ascii=False)


def _structure(markdown: str) -> tuple[list[str], int]:
    headings = [line.lstrip("#").strip() for line in markdown.splitlines() if line.startswith("#")]
    bullets = sum(1 for line in markdown.splitlines() if line.lstrip().startswith(("- ", "* ")))
    return headings, bullets


def compare(source: str, draft: str) -> dict[str, Any]:
    """What a rewrite left out, measured rather than asserted.

    Found live: asked to tailor a CV, the model wrote a draft that silently stopped after the
    first project -- Skills, Education and Certifications gone, 7 of 18 points kept -- while
    saying it had only reordered. A prompt asking for honesty did not prevent it; a count does,
    because the person approving sees it above the draft.
    """
    source_headings, source_bullets = _structure(source)
    draft_headings, draft_bullets = _structure(draft)
    present = {h.lower() for h in draft_headings}
    return {
        "missing_sections": [h for h in source_headings if h.lower() not in present],
        "points_kept": f"{draft_bullets} of {source_bullets}",
        "length_kept": f"{len(draft)} of {len(source)} characters",
    }


async def _source(root: Path, index: FileIndex, arguments: dict[str, Any]) -> str | None:
    based_on = str(arguments.get("based_on") or "")
    if not based_on:
        return None
    try:
        return (await _find(root, index, based_on))[1]
    except up.UploadError:
        return None


async def _render(root: Path, index: FileIndex, arguments: dict[str, Any]) -> str:
    title = str(arguments.get("title", "")).strip() or "Draft"
    markdown = str(arguments.get("markdown", ""))
    head = f"New file: {title}.md"
    source = await _source(root, index, arguments)
    if source is not None:
        c = compare(source, markdown)
        missing = ", ".join(c["missing_sections"]) or "none"
        head += (f"\nCompared with {Path(str(arguments['based_on'])).name}: "
                 f"sections missing or renamed: {missing}. "
                 f"Points kept: {c['points_kept']}. Length: {c['length_kept']}.")
    return f"{head}\n\n{markdown}"


async def _list(files_root: Path, root: Path, index: FileIndex) -> str:
    listing = await up.listing(index, files_root, root)
    return json.dumps({
        # `draft` marks what the assistant wrote itself: never the user's own material, so never a source.
        "documents": [{"name": d["name"], "path": d["path"], "files": d["files"], "draft": d["draft"]}
                      for d in listing["docs"]],
        "audio": [{"name": a["name"], "path": a["path"]} for a in listing["audio"]],
    }, ensure_ascii=False)


def document_tools(files_root: Path, root: Path, index: FileIndex) -> list[LocalTool]:
    """`root` is where documents are named (texts.py); `files_root` the store, for the audio list_uploads gives."""
    return [
        LocalTool(
            name="list_uploads",
            description=(
                "List what the user has uploaded -- markdown documents (a CV, notes, a report) "
                "and audio recordings -- newest first, with the path each needs. Use it whenever "
                "the user refers to something they uploaded or 'my CV' and no path is in the "
                "conversation. A document marked draft: true was written by the assistant, not the "
                "user, and is never the user's own material. Reads only."
            ),
            input_schema={"type": "object", "properties": {}},
            read_only=True,
            handler=lambda _arguments: _list(files_root, root, index),
        ),
        LocalTool(
            name="read_document",
            description=(
                "Read the text of an uploaded markdown document -- a CV, notes, a report -- by "
                "the path the upload reported. Use it before rewriting or tailoring anything. "
                "Only uploaded documents can be read. Reads only."
            ),
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string", "description": "The .md file's path."}},
                "required": ["path"],
            },
            read_only=True,
            handler=lambda arguments: _read(root, index, arguments),
        ),
        LocalTool(
            name="write_draft",
            description=(
                "Save a new markdown document you have written -- a tailored CV, a rewritten "
                "report, a letter -- as a new file, and return its path, ready for "
                "docu_ai__build. Never overwrites anything: the original stays as it was. Use "
                "only facts from the user's own material; never invent experience, dates, "
                "employers, qualifications or figures. Keep every section and fact of the "
                "original unless the user asked for something to be cut. When the draft rewrites "
                "an existing document, pass its path as based_on: the user then sees exactly "
                "which sections and points the draft leaves out. The user sees the draft in "
                "full and approves it before it is saved."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string",
                              "description": "A short file name for the draft, e.g. 'CV - ML engineer'."},
                    "markdown": {"type": "string", "description": "The whole document, as markdown."},
                    "based_on": {"type": "string",
                                 "description": "The path of the document this rewrites, if any."},
                },
                "required": ["title", "markdown"],
            },
            read_only=False,
            handler=lambda arguments: _write(root, index, arguments),
            render=lambda arguments: _render(root, index, arguments),
        ),
    ]
