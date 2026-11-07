"""A file to attach, named by its path, read from the one folder this tool was given (2026-10-30).

A file cannot travel through a model: a Word CV is about 650 KB, which is at least 217,000 tokens as base64, and
one model reply holds 16,000. So a caller names a file instead -- one docu-ai saved -- and this reads it. Only from
the folder Shelby injected (`MAIL_AI_ATTACH_ROOT`): a model chooses the path, and a path is otherwise a way to
mail any file on the machine to anyone. Kept out of `compose.py`, which stays pure.
"""

from __future__ import annotations

from pathlib import Path

from mailai.compose import MAX_ATTACHMENTS_BYTES, Attachment, BadAttachment


def read_attachment(path: str, root: Path | None, filename: str = "", mime_type: str = "") -> Attachment:
    """The file at `path`, which must be a plain file inside `root`. A link is refused outright, wherever it
    points: nothing that saves a file there makes one, and following it is how a file elsewhere gets out."""
    if root is None:
        raise BadAttachment("no folder to attach files from was given to this tool (MAIL_AI_ATTACH_ROOT)")
    if not isinstance(path, str) or not path.strip():
        raise BadAttachment("an attachment by path needs a path")
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    if candidate.is_symlink():
        raise BadAttachment(f"{path!r} is a link, not a file to attach")
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        raise BadAttachment(f"there is no file to attach at {path!r}") from None
    if not resolved.is_relative_to(Path(root).resolve()):
        raise BadAttachment(f"{path!r} is not in the folder files may be attached from")
    if not resolved.is_file():
        raise BadAttachment(f"{path!r} is not a file")
    size = resolved.stat().st_size
    if size > MAX_ATTACHMENTS_BYTES:  # before reading it in
        raise BadAttachment(f"{resolved.name} is {size / 1024**2:.1f} MB; files may come to "
                            f"{MAX_ATTACHMENTS_BYTES // 1024**2} MB in all")
    return Attachment(filename or resolved.name, resolved.read_bytes(), mime_type)
