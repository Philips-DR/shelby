"""Tests for the MCP front door.

No network, no model, no credentials. The door is driven directly through list_tools() and
call_tool(), which is the same path a real session takes once the transport is stripped
away.
"""

import asyncio
import contextlib
import io
import json
from pathlib import Path

import pytest

from meetnotes.client import ModelConfig
from meetnotes.mcp_server import ServerPaths, create_meet_ai_server
from meetnotes.operations import MAX_SYNC_AUDIO_SECONDS, OperationError, transcribe_audio


SEGMENTS = [
    {"start": 0.0, "end": 4.0, "text": "We should move billing to the new provider.", "speaker": 0},
    {"start": 4.0, "end": 8.0, "text": "Kwame will send the contract on Friday.", "speaker": 1},
]


@pytest.fixture
def workspace(tmp_path):
    audio = tmp_path / "audio"
    transcripts = tmp_path / "transcripts"
    audio.mkdir()
    transcripts.mkdir()
    (transcripts / "meeting.md").write_text("# meeting\n\nbody\n", encoding="utf-8")
    (transcripts / "meeting.timeline.json").write_text(
        json.dumps({"version": 1, "source": "meeting.m4a", "duration": 8.0, "segments": SEGMENTS}),
        encoding="utf-8",
    )
    (transcripts / "orphan.md").write_text("# orphan\n\nno timeline\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def server(workspace):
    return create_meet_ai_server(
        ServerPaths(audio_dir=workspace / "audio", transcript_dir=workspace / "transcripts"),
        ModelConfig(region="us-east-1"),
    )


def call(server, name, **arguments) -> dict:
    result = asyncio.run(server.call_tool(name, arguments))
    text = "".join(block.text for block in result.content if block.type == "text")
    return json.loads(text)


def test_the_door_advertises_exactly_its_operations(server):
    names = sorted(tool.name for tool in asyncio.run(server.list_tools()))
    assert names == [
        "dictate", "generate_minutes", "generate_notes", "list_audio_sources", "list_recordings",
        "preview_minutes", "preview_notes", "read_transcript", "read_written", "recording_status",
        "start_recording", "start_transcription", "stop_recording", "transcribe",
        "transcription_status",
    ]


def test_the_operations_that_spend_nothing_are_marked_read_only(server):
    read_only = {
        tool.name: tool.annotations.read_only_hint
        for tool in asyncio.run(server.list_tools())
    }
    assert read_only["preview_notes"] is True
    assert read_only["list_recordings"] is True
    assert read_only["list_audio_sources"] is True
    assert read_only["recording_status"] is True
    assert read_only["read_transcript"] is True
    assert read_only["read_written"] is True
    assert read_only["preview_minutes"] is True
    assert read_only["dictate"] is True
    assert read_only["generate_notes"] is False
    assert read_only["generate_minutes"] is False
    assert read_only["transcribe"] is False
    # Starting a recording turns on a microphone; it must pass through an approval gate.
    assert read_only["start_recording"] is False
    assert read_only["stop_recording"] is False


def test_listing_reports_which_transcripts_can_actually_have_notes(server):
    """A transcript with no timeline beside it is unusable, and saying so here is what
    stops a caller discovering that only after a failed call."""
    listed = call(server, "list_recordings")
    by_name = {Path(t["markdown"]).name: t for t in listed["transcripts"]}
    assert by_name["meeting.md"]["timeline"] is not None
    assert by_name["orphan.md"]["timeline"] is None


HEADER = """---
source: "Members 20260812_102457.m4a"
duration: 02:05:10
language: en
speakers: 9
transcribed: 2026-09-26 18:53
---

# Members 20260812 102457

body
"""


def test_listing_says_what_is_known_of_each_meeting_and_no_more(workspace, server):
    """The page shows a meeting by its name, date, length and speakers, not its file name.
    Each comes from what is on disk; a meeting whose file name holds no date gets none."""
    transcripts = workspace / "transcripts"
    (transcripts / "members.md").write_text(HEADER, encoding="utf-8")
    (transcripts / "members.minutes.md").write_text("---\ngenerated: x\n---\n\n# Minutes\n", encoding="utf-8")
    (transcripts / "members.minutes.json").write_text(json.dumps({"meeting": " third quarter meeting "}), encoding="utf-8")
    listed = call(server, "list_recordings")
    by_name = {Path(t["markdown"]).name: t for t in listed["transcripts"]}
    members = by_name["members.md"]
    assert members["source"] == "Members 20260812_102457.m4a"
    assert members["recorded"] == "2026-08-12T10:24"
    assert members["duration_seconds"] == 7510.0
    assert members["speakers"] == 9
    assert members["meeting"] == "third quarter meeting"
    # meeting.md opens with no header at all: nothing is made up for it
    plain = by_name["meeting.md"]
    assert (plain["source"], plain["recorded"], plain["duration_seconds"], plain["speakers"], plain["meeting"]) == (
        None, None, None, None, None)


def test_a_header_never_closed_is_not_read_as_one(workspace, server):
    (workspace / "transcripts" / "open.md").write_text("---\nduration: 01:00:00\n# open\n", encoding="utf-8")
    listed = call(server, "list_recordings")
    entry = next(t for t in listed["transcripts"] if t["markdown"].endswith("open.md"))
    assert entry["duration_seconds"] is None


def test_a_meeting_name_the_minutes_could_not_verify_is_not_shown(workspace, server):
    transcripts = workspace / "transcripts"
    (transcripts / "meeting.minutes.md").write_text("# Minutes\n", encoding="utf-8")
    (transcripts / "meeting.minutes.json").write_text(json.dumps({"meeting": ""}), encoding="utf-8")
    (transcripts / "meeting.notes.md").write_text("# Notes\n", encoding="utf-8")
    (transcripts / "meeting.notes.json").write_text("not json", encoding="utf-8")
    listed = call(server, "list_recordings")
    entry = next(t for t in listed["transcripts"] if t["markdown"].endswith("/meeting.md"))
    assert entry["meeting"] is None


def test_audio_no_transcript_was_made_from_is_listed_as_untranscribed(workspace, server):
    audio = workspace / "audio"
    (audio / "2026-09-28-000036.flac").write_bytes(b"x")    # meet-ai's own recorder's name
    (audio / "meeting.m4a").write_bytes(b"x")               # meeting.md was made from it
    (audio / "Members 20260812_102457.m4a").write_bytes(b"x")
    (workspace / "transcripts" / "members.md").write_text(HEADER, encoding="utf-8")  # names it as its source
    listed = call(server, "list_recordings")
    assert listed["untranscribed"] == [
        {"path": str(audio / "2026-09-28-000036.flac"), "recorded": "2026-09-28T00:00"},
    ]


def test_read_written_returns_the_notes_without_their_header(workspace, server):
    (workspace / "transcripts" / "meeting.notes.md").write_text(
        "---\nsource: meeting.m4a\ngenerated: 2026-09-26 18:57\n---\n\n# Notes\n\n- A point.\n", encoding="utf-8")
    read = call(server, "read_written", path="meeting.notes.md")
    assert read["kind"] == "notes"
    assert read["generated"] == "2026-09-26 18:57"
    assert read["text"] == "# Notes\n\n- A point.\n"


def test_read_written_reads_only_what_meet_ai_wrote_in_its_own_folder(workspace, server, tmp_path):
    transcripts = workspace / "transcripts"
    elsewhere = tmp_path / "elsewhere.notes.md"
    elsewhere.write_text("# not ours\n", encoding="utf-8")
    (transcripts / "link.notes.md").symlink_to(elsewhere)
    for path in ("meeting.md", "meeting.timeline.json", str(elsewhere), "link.notes.md", "../elsewhere.notes.md", "gone.minutes.md"):
        assert "error" in call(server, "read_written", path=path), path


def test_a_transcript_from_before_timelines_is_read_from_its_markdown(workspace, server):
    """Two of the user's five meetings were transcribed before timelines existed, and the page could
    not show them at all. Their markdown holds the stamps transcribe.py wrote."""
    transcripts = workspace / "transcripts"
    (transcripts / "old.md").write_text(
        "---\nsource: \"old.m4a\"\nduration: 00:10:00\nspeakers: 2\n---\n\n# old\n\n"
        "**Speaker 1** *[00:00:01]*\n\nOkay, so this is the background.\n\nAnd a second paragraph.\n\n"
        "**Speaker 2** *[00:01:05]*\n\nWho are you logged in as?\n",
        encoding="utf-8",
    )
    (transcripts / "plain.md").write_text(
        "---\nduration: 00:02:00\n---\n\n# plain\n\n**[00:00:01]** Okay, so this\nis the background.\n\n**[00:00:27]** Why?\n",
        encoding="utf-8",
    )
    old = call(server, "read_transcript", transcript=str(transcripts / "old.md"))
    assert old["timeline"] is None
    assert old["duration"] == 600.0
    assert old["text"] == ("[00:00:01] Speaker 1: Okay, so this is the background. And a second paragraph.\n\n"
                           "[00:01:05] Speaker 2: Who are you logged in as?")
    plain = call(server, "read_transcript", transcript=str(transcripts / "plain.md"))
    assert plain["text"] == "[00:00:01] Okay, so this is the background.\n\n[00:00:27] Why?"
    part = call(server, "read_transcript", transcript=str(transcripts / "old.md"), start=60)
    assert part["text"] == "[00:01:05] Speaker 2: Who are you logged in as?"


def test_a_transcript_with_a_timeline_is_still_read_from_the_timeline(workspace, server):
    (workspace / "transcripts" / "meeting.md").write_text("# meeting\n\n**[00:00:00]** not this text\n", encoding="utf-8")
    read = call(server, "read_transcript", transcript=str(workspace / "transcripts" / "meeting.md"))
    assert read["timeline"].endswith("meeting.timeline.json")
    assert "billing" in read["text"] and "not this text" not in read["text"]


def test_preview_runs_without_any_credentials(server, workspace):
    preview = call(
        server, "preview_notes", timeline=str(workspace / "transcripts" / "meeting.timeline.json")
    )
    assert preview["segments"] == 2
    assert preview["approx_tokens"] > 0
    assert preview["would_write"].endswith("meeting.notes.md")


def test_a_missing_timeline_comes_back_as_an_error_not_an_exception(server, workspace):
    """A door that raises takes the session down with it."""
    result = call(server, "preview_notes", timeline=str(workspace / "nope.timeline.json"))
    assert "error" in result
    assert "no timeline" in result["error"]


def test_nothing_is_written_to_stdout_while_a_tool_runs(server, workspace):
    """On stdio, stdout IS the protocol stream: one stray line of progress corrupts it.
    transcribe.py predates this door and prints as it goes, so this is a real hazard and
    not a hypothetical one."""
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink):
        call(server, "list_recordings")
        call(
            server,
            "preview_notes",
            timeline=str(workspace / "transcripts" / "meeting.timeline.json"),
        )
    assert sink.getvalue() == ""


def test_long_audio_is_refused_before_anything_is_decoded(tmp_path, monkeypatch):
    """Decoding takes roughly as long as the recording, so a two-hour file would hang the
    call for two hours and then time out with nothing to show. Refusing is the honest
    answer until there is a background job to hand it to."""
    import transcribe

    audio = tmp_path / "long.wav"
    audio.write_bytes(b"not really audio")
    monkeypatch.setattr(transcribe, "probe_duration", lambda _p: MAX_SYNC_AUDIO_SECONDS + 1)

    with pytest.raises(OperationError) as excinfo:
        transcribe_audio(audio, tmp_path)
    # It used to send you to a terminal. Now there is somewhere better to go.
    assert "start_transcription" in str(excinfo.value)


def test_short_audio_passes_the_duration_gate(tmp_path, monkeypatch):
    """The gate must not be so blunt that a voice note cannot be transcribed. Stops at the decode --
    proving the gate opened, without decoding anything.

    The model is stubbed as well as the decode: transcribe_audio builds the real WhisperModel BEFORE
    it reaches transcribe_file, so stubbing only the decode (as this once did) quietly loaded the
    1.5 GB model, and downloaded it on any machine that did not already have it -- a test that
    passed on a developer's cache and needed the network anywhere else."""
    import faster_whisper
    import transcribe

    audio = tmp_path / "short.wav"
    audio.write_bytes(b"not really audio")
    monkeypatch.setattr(faster_whisper, "WhisperModel", lambda *_a, **_k: object())
    monkeypatch.setattr(transcribe, "probe_duration", lambda _p: 60.0)
    monkeypatch.setattr(
        transcribe, "transcribe_file", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("reached decode"))
    )

    with pytest.raises(RuntimeError, match="reached decode"):
        transcribe_audio(audio, tmp_path)


def test_a_transcript_can_be_read_by_its_markdown_path(server, workspace):
    """Callers hold the .md -- it is what list_recordings and people point at -- so the
    read must not insist on the timeline's name."""
    read = call(server, "read_transcript", transcript=str(workspace / "transcripts" / "meeting.md"))
    assert read["text"].startswith("[00:00:00] Speaker 1: We should move billing")
    assert "[00:00:04] Speaker 2: Kwame will send the contract" in read["text"]
    assert read["truncated"] is False


def test_a_transcript_can_be_read_in_part(server, workspace):
    read = call(server, "read_transcript",
                transcript=str(workspace / "transcripts" / "meeting.md"), start=5)
    assert "billing" not in read["text"]
    assert "Kwame" in read["text"]


def test_minutes_preview_names_its_own_file(server, workspace):
    preview = call(server, "preview_minutes", timeline=str(workspace / "transcripts" / "meeting.md"))
    assert preview["would_write"].endswith("meeting.minutes.md")


def test_a_long_read_stops_at_a_paragraph_and_says_where(server, workspace, monkeypatch):
    """Half a meeting must never look like the whole of one."""
    import meetnotes.operations as operations
    monkeypatch.setattr(operations, "MAX_READ_CHARS", 60)
    path = str(workspace / "transcripts" / "meeting.md")
    first = call(server, "read_transcript", transcript=path)
    assert first["truncated"] is True
    assert first["end"] == 4.0
    assert "Kwame" not in first["text"]
    rest = call(server, "read_transcript", transcript=path, start=first["end"])
    assert "Kwame" in rest["text"] and rest["truncated"] is False


def test_minutes_are_reported_beside_their_transcript_never_as_one(server, workspace):
    (workspace / "transcripts" / "meeting.minutes.md").write_text("# Minutes\n", encoding="utf-8")
    listed = call(server, "list_recordings")
    names = [Path(t["markdown"]).name for t in listed["transcripts"]]
    assert "meeting.minutes.md" not in names
    entry = next(t for t in listed["transcripts"] if t["markdown"].endswith("meeting.md"))
    assert entry["minutes"].endswith("meeting.minutes.md")


def test_a_meeting_can_be_named_the_way_a_person_names_it(server):
    """"meeting" alone finds the transcript in the door's own directory -- found live: the
    assistant's first read passed the bare name a person had typed, failed, and had to list
    every recording to recover the path."""
    read = call(server, "read_transcript", transcript="meeting")
    assert "Kwame" in read["text"]
    assert call(server, "preview_minutes", timeline="meeting")["segments"] == 2
