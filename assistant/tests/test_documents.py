"""Tests for reading and drafting documents. Confinement first: the model chooses the path. The text is in
the database; a path names a document, and nothing of it is on disk between calls."""

import asyncio
import json
from pathlib import Path

from assistant import texts
from assistant import uploads as up
from assistant.documents import document_tools
from assistant.files import JsonFileIndex
from assistant.tools import ToolRegistry


def index_for(tmp_path):
    return JsonFileIndex(tmp_path / "files" / "index.json")


def tools_for(tmp_path):
    return {t.name: t for t in document_tools(tmp_path / "files", tmp_path / "texts", index_for(tmp_path))}


async def _chunks(data):
    yield data


def uploaded(tmp_path, name, text):
    """A markdown file as the upload endpoints would have stored it, and the path the listing gives it."""
    batches = up.DocBatches()
    batch = batches.start(name)
    asyncio.run(batches.receive(batch, f"{name}.md", _chunks(text.encode())))
    record, names = asyncio.run(batches.finish(index_for(tmp_path), batch))
    return texts.path_for(tmp_path / "texts", record, names)


def call(tool, **arguments):
    return json.loads(asyncio.run(tool.handler(arguments)))


def test_a_read_cannot_leave_the_stored_documents(tmp_path):
    uploaded(tmp_path, "cv", "# CV\n")
    (tmp_path / "secret.md").write_text("private")
    read = tools_for(tmp_path)["read_document"]
    assert "only uploaded documents" in call(read, path=str(tmp_path / "secret.md"))["error"]
    assert "only uploaded documents" in call(read, path=str(tmp_path / "texts" / ".." / "secret.md"))["error"]


def test_only_a_stored_markdown_document_is_read(tmp_path):
    cv = uploaded(tmp_path, "cv", "# CV\n")
    read = tools_for(tmp_path)["read_document"]
    # A file that happens to be where a document's copy would be is not the document.
    fake = tmp_path / "texts" / ("0" * 32) / "cv" / "cv.md"
    fake.parent.mkdir(parents=True)
    fake.write_text("planted")
    for path in (fake, cv.parent.parent / "other" / "cv.md", cv.parent / "missing.md"):
        assert "no markdown file" in call(read, path=str(path))["error"]


def test_an_uploaded_document_reads_back_whole_from_the_database(tmp_path):
    cv = uploaded(tmp_path, "cv", "# Ama Mensah\n\nData engineer, 4 years.\n")
    assert not cv.exists()  # nothing on disk: the text is read from the database
    read = call(tools_for(tmp_path)["read_document"], path=str(cv))
    assert read["text"] == "# Ama Mensah\n\nData engineer, 4 years.\n" and read["truncated"] is False
    # The folder names its one file too.
    assert call(tools_for(tmp_path)["read_document"], path=str(cv.parent))["text"].startswith("# Ama")


def test_a_draft_is_always_a_new_document_and_never_overwrites(tmp_path):
    """The original must survive to be compared against -- and so must an earlier draft."""
    tools = tools_for(tmp_path)
    first = call(tools["write_draft"], title="CV - ML engineer", markdown="# Ama\n\nv1")
    second = call(tools["write_draft"], title="CV - ML engineer", markdown="# Ama\n\nv2")
    assert first["path"] != second["path"]
    assert call(tools["read_document"], path=first["path"])["text"] == "# Ama\n\nv1\n"
    assert call(tools["read_document"], path=second["path"])["text"] == "# Ama\n\nv2\n"
    # Each is its own document, so the second keeps the title it was given: it is the Doc's title.
    assert first["title"] == second["title"] == "CV - ML engineer"
    assert not (tmp_path / "texts").exists()


def test_an_empty_draft_is_refused(tmp_path):
    assert call(tools_for(tmp_path)["write_draft"], title="x", markdown="  ")["error"] == "the draft is empty"


def test_the_approval_shows_the_draft_itself_not_a_json_string(tmp_path):
    """A person approves what they have read; a whole CV escaped into JSON cannot be read."""
    async def body():
        local = document_tools(tmp_path / "files", tmp_path / "texts", index_for(tmp_path))
        async with ToolRegistry([], local=local) as registry:
            tool = registry.find("assistant__write_draft")
            preview = await registry.preview_of(tool, {"title": "CV", "markdown": "# Ama\n\n- Python"})
            return tool, preview
    tool, preview = asyncio.run(body())
    assert tool.read_only is False and tool.preview is not None  # gated, with a preview promised
    assert preview == "New file: CV.md\n\n# Ama\n\n- Python"


def test_a_rewrite_shows_what_it_left_out_above_the_draft(tmp_path):
    """Found live: a 'tailored' CV silently stopped after its first project, and its reply
    said it had only reordered. The approval now says what is missing, measured."""
    original = uploaded(tmp_path, "cv", "# Ama\n\n## Experience\n\n- a\n- b\n\n## Skills\n\n- Python\n\n## Education\n\n- BSc\n")
    args = {"title": "CV - ML", "markdown": "# Ama\n\n## Experience\n\n- a\n", "based_on": str(original)}

    async def body():
        local = document_tools(tmp_path / "files", tmp_path / "texts", index_for(tmp_path))
        async with ToolRegistry([], local=local) as registry:
            return await registry.preview_of(registry.find("assistant__write_draft"), args)
    preview = asyncio.run(body())
    assert "sections missing or renamed: Skills, Education" in preview
    assert "Points kept: 1 of 4" in preview

    saved = call(tools_for(tmp_path)["write_draft"], **args)
    assert saved["compared_with_original"]["missing_sections"] == ["Skills", "Education"]


def test_uploads_can_be_found_without_a_path_in_the_conversation(tmp_path):
    """Found live: after a restart the upload's note was gone, and asked to make a CV the
    assistant asked for an upload that was already there -- it had no way to look."""
    uploaded(tmp_path, "01-resume", "# Ama\n")
    listed = call(tools_for(tmp_path)["list_uploads"])
    assert listed["documents"][0]["path"].endswith("01-resume/01-resume.md")


# A draft the assistant wrote is marked, and list_uploads says so. A tool that checks a draft against "the
# user's own material" (apply-ai) refuses a marked folder: found when the model passed its own earlier cover
# letter as a source and a claim it had made became supported by itself. The marker itself is written into
# the copy a tool is lent (test_texts.py).
def test_a_draft_is_marked_as_the_assistants_own_and_an_upload_is_not(tmp_path):
    uploaded(tmp_path, "01-resume", "# Ama\n")
    tools = tools_for(tmp_path)
    written = call(tools["write_draft"], title="CV - Role", markdown="# Ama\n\n- Built things.\n")
    listed = {d["name"]: d["draft"] for d in call(tools["list_uploads"])["documents"]}
    assert listed == {"CV - Role": True, "01-resume": False}
    assert written["path"].endswith("CV - Role/CV - Role.md")
    assert asyncio.run(index_for(tmp_path).all("docs"))[0].made_by == "assistant"


def test_the_listing_tells_the_model_what_draft_means(tmp_path):
    description = tools_for(tmp_path)["list_uploads"].description
    assert "draft: true" in description and "never the user's own material" in description
