"""Tests for the backend's timer: what tools.yaml says to run, run whether or not a page is open.

No child process, no model, no network: a local tool stands in for mail-ai's sync, and the timer's sleep
is replaced, so a day of runs takes no time."""

import asyncio
import json

import pytest

from assistant.audit import FileAuditStore
from assistant.schedule import run_every, schedule_notice
from assistant.tools import LocalTool, ToolRegistry


class Stop(Exception):
    """Ends the timer after the runs a test asked for."""


def sync_tool(outcomes: list[str], calls: list[dict]) -> LocalTool:
    async def handler(arguments):
        calls.append(arguments)
        if outcomes.pop(0) == "failed":
            raise RuntimeError("invalid_grant: the Gmail login has lapsed")
        return '{"added": 3}'
    # Not read-only, as mail-ai's sync is not: it writes the local mailbox.
    return LocalTool(name="sync", description="Fetch new mail.", input_schema={"type": "object", "properties": {}},
                     read_only=False, handler=handler)


def run_schedule(tmp_path, outcomes: list[str], qualified: str = "assistant__sync"):
    """The timer through one run per outcome. Returns the tool's calls, the audit rows, the events, the sleeps."""
    calls: list[dict] = []
    events: list[dict] = []
    sleeps: list[float] = []
    tool = sync_tool(list(outcomes), calls)

    async def emit(event):
        events.append(event)

    async def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) >= len(outcomes):
            raise Stop

    async def main():
        async with ToolRegistry([], local=[tool]) as registry:
            await run_every(registry, FileAuditStore(tmp_path / "audit.jsonl"), emit, "mail-ai", qualified, 1800,
                            sleep=sleep)

    try:
        asyncio.run(main())
    except Stop:
        pass
    path = tmp_path / "audit.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    return calls, rows, events, sleeps


def test_a_scheduled_tool_runs_at_once_and_then_after_every_interval(tmp_path):
    calls, _, _, sleeps = run_schedule(tmp_path, ["ok", "ok", "ok"])
    assert calls == [{}, {}, {}]          # no arguments: a schedule names a tool, nothing else
    assert sleeps == [1800, 1800, 1800]   # the first run is at once, not half an hour after a restart


def test_a_tool_that_writes_runs_without_anyone_at_the_gate(tmp_path):
    """The schedule in tools.yaml is the standing order; nobody is there to press yes every half hour."""
    calls, rows, _, _ = run_schedule(tmp_path, ["ok"])
    assert calls == [{}] and rows[0]["outcome"] == "ok"


def test_only_a_change_of_outcome_is_audited(tmp_path):
    """Every run would bury a person's own actions in History and the Overview, as the page's timer did."""
    _, rows, _, _ = run_schedule(tmp_path, ["ok", "ok", "failed", "failed", "ok", "ok"])
    assert [r["outcome"] for r in rows] == ["ok", "failed", "ok"]
    assert {(r["tool"], r["origin"]) for r in rows} == {("assistant__sync", "schedule")}
    assert "invalid_grant" in rows[1]["error"]


def test_failing_and_recovering_are_each_said_once_and_nothing_else_is(tmp_path):
    _, _, events, _ = run_schedule(tmp_path, ["ok", "failed", "failed", "ok", "ok"])
    assert [(e["type"], e["level"]) for e in events] == [("notice", "warning"), ("notice", "success")]
    assert events[0]["title"] == "mail-ai sync is failing on its schedule"
    assert "invalid_grant" in events[0]["body"]
    assert events[1]["title"] == "mail-ai sync is working again"


def test_a_first_run_that_fails_is_said_and_audited(tmp_path):
    _, rows, events, _ = run_schedule(tmp_path, ["failed", "failed"])
    assert [r["outcome"] for r in rows] == ["failed"]
    assert [e["level"] for e in events] == ["warning"]


def test_a_failure_does_not_stop_the_timer(tmp_path):
    calls, _, _, sleeps = run_schedule(tmp_path, ["failed", "failed", "ok"])
    assert len(calls) == 3 and len(sleeps) == 3


def test_a_schedule_naming_a_tool_that_does_not_exist_says_so_and_stops(tmp_path):
    calls, rows, events, sleeps = run_schedule(tmp_path, ["ok"], qualified="assistant__nope")
    assert calls == [] and rows == [] and sleeps == []
    assert events[0]["level"] == "error" and "assistant__nope" in events[0]["title"]


def test_the_notices_are_decided_by_the_change_alone():
    assert schedule_notice("mail-ai", "sync", None, "ok", "") is None
    assert schedule_notice("mail-ai", "sync", "ok", "ok", "") is None
    assert schedule_notice("mail-ai", "sync", "failed", "failed", "x") is None
    assert schedule_notice("mail-ai", "sync", "ok", "failed", "x" * 500)["body"] == "x" * 200


@pytest.mark.parametrize("entry", [
    "{every_minutes: 30}",             # no tool
    "{tool: sync}",                    # no interval
    "{tool: sync, every_minutes: 2}",  # a poll, not a schedule
    "{tool: sync, every_minutes: '30'}",
    "{tool: sync, every_minutes: true}",
    "sync",                            # not an entry at all
])
def test_a_schedule_that_is_wrong_stops_the_server_starting(tmp_path, entry):
    """A schedule that silently never ran is how a mailbox went five days stale."""
    from assistant.config import load_tool_servers
    path = tmp_path / "tools.yaml"
    path.write_text(f"servers:\n  - name: mail-ai\n    command: /bin/true\n    schedule: [{entry}]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="schedule"):
        load_tool_servers(path)


def test_tools_yaml_declares_a_schedule_and_the_registry_names_its_tool(tmp_path):
    from assistant.config import Schedule, load_tool_servers
    path = tmp_path / "tools.yaml"
    path.write_text("servers:\n"
                    "  - name: mail-ai\n    command: /bin/true\n"
                    "    schedule:\n      - tool: sync\n        every_minutes: 30\n"
                    "  - name: meet-ai\n    command: /bin/true\n", encoding="utf-8")
    mail, meet = load_tool_servers(path)
    assert mail.schedule == [Schedule(tool="sync", every_seconds=1800)] and meet.schedule == []
    assert ToolRegistry([mail, meet]).schedules == [("mail-ai", "mail_ai__sync", 1800)]


def test_the_shipped_tools_yaml_syncs_mail_every_quarter_hour():
    """Every 15 minutes since 2026-11-07, the user's choice (it was 30)."""
    from pathlib import Path
    from assistant.config import load_tool_servers
    servers = load_tool_servers(Path(__file__).resolve().parents[1] / "tools.yaml")
    assert ToolRegistry(servers).schedules == [("mail-ai", "mail_ai__sync", 900)]
