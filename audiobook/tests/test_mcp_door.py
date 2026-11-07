"""The MCP door, driven through list_tools() and call_tool(): the path a real session takes
once the transport is stripped away. No model, no Docling, no audio."""

import asyncio
import json

import pytest

from audiobook.mcp_server import ServerPaths, create_audiobook_server

READ_ONLY = {"describe_audiobook", "get_corrections", "inventory", "job_status", "list_audiobooks", "list_voices",
             "preview_book", "read_chapter", "speak"}
# `release` deletes, so it is a write: asked about in chat like delete_audiobook (Shelby calls it itself).
WRITES = {"cancel_job", "delete_audiobook", "release", "set_corrections", "start_analysis", "start_render",
          "start_voice_clone", "start_voice_sample"}


@pytest.fixture
def server(tmp_path):
    return create_audiobook_server(ServerPaths(jobs_dir=tmp_path / "jobs"))


def call(server, tool, **arguments) -> dict:
    result = asyncio.run(server.call_tool(tool, arguments))
    return json.loads("".join(block.text for block in result.content if block.type == "text"))


def test_the_door_advertises_exactly_its_operations(server):
    names = {tool.name for tool in asyncio.run(server.list_tools())}
    assert names == READ_ONLY | WRITES


def test_what_may_run_without_asking_is_exactly_what_only_reads(server):
    """The assistant decides approval from this annotation alone, and treats a missing one as a
    write. A tool that starts hours of work must never be listed as read-only."""
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    read_only = {n for n, t in tools.items() if t.annotations and t.annotations.read_only_hint}
    assert read_only == READ_ONLY
    assert all(tools[n].annotations is not None for n in tools)


def test_failures_come_back_as_data_not_as_crashes(server, tmp_path):
    assert "no PDF at" in call(server, "preview_book", pdf=str(tmp_path / "gone.pdf"))["error"]
    assert "not a PDF" in call(server, "start_analysis", pdf=str(tmp_path / "x.txt"))["error"]
    assert "consent" in call(server, "start_voice_clone", name="tina", recording=str(tmp_path / "a.wav"), consent="")["error"]


def test_with_no_jobs_status_says_so(server):
    assert call(server, "job_status") == {"job": None}
    assert "no audiobook job" in call(server, "job_status", job_id="nope")["error"]


def test_deleting_a_books_audio_is_destructive_and_shows_what_it_will_remove_before_it_asks(server):
    """The gate shows the named preview instead of {book}, and refuses a preview that is not read-only."""
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    delete = tools["delete_audiobook"]
    assert delete.annotations.destructive_hint is True and not delete.annotations.read_only_hint
    approval = delete.meta["approval"]
    assert approval == {"preview_tool": "describe_audiobook", "argument_map": {"book": "book"}, "field": "summary"}
    assert tools[approval["preview_tool"]].annotations.read_only_hint is True
