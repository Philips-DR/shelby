"""Counting what the model takes, and pricing it for the Overview.

A fake model and a fake registry, no network. What must hold: every request to the model is counted once, a
tool's own report is counted only when it is exactly the agreed shape, a model with no known price is shown in
tokens and never with a guessed price, and counting can never break the work it counts.
"""

import asyncio
import json
from types import SimpleNamespace

from assistant import session
from assistant.audit import FileAuditStore
from assistant.session import execute, run_turn
from assistant.tools import RemoteTool
from assistant.usage import (
    PRICES,
    FileUsageStore,
    cost_usd,
    count_response,
    price_key,
    priced,
    usage_from_result,
    usage_of,
)
from tests.test_server import AUTH, app_for, with_client

NOTES = RemoteTool(server="meet_ai", name="generate_notes", qualified_name="meet_ai__generate_notes",
                   description="", input_schema={}, read_only=False)
CONFIG = SimpleNamespace(resolved_model="claude-opus-5-5", provider="anthropic")


def run(coro):
    return asyncio.run(coro)


# --- price -------------------------------------------------------------------------------------------------------

def test_a_providers_name_for_a_model_is_the_models_own_id():
    assert price_key("claude-opus-5-5") == "claude-opus-5-5"
    assert price_key("us.anthropic.claude-opus-4-6-v1") == "claude-opus-4-6"  # Bedrock's default here
    assert price_key("anthropic.claude-opus-4-6-v1:0") == "claude-opus-4-6"
    assert price_key("claude-opus-4-5-20251101") == "claude-opus-4-5"
    assert price_key("  Claude-Sonnet-5-5 ") == "claude-sonnet-5-5"
    assert price_key("some-other-model") == "some-other-model"  # not ours to rewrite


def test_the_cost_is_input_and_output_at_list_price_per_million_tokens():
    assert cost_usd("claude-opus-5-5", 1_000_000, 1_000_000) == 24.0  # $4 in + $20 out
    assert cost_usd("claude-opus-5-5", 18_000, 3_000) == round(18_000 * 4 / 1e6 + 3_000 * 20 / 1e6, 6) == 0.132
    assert cost_usd("us.anthropic.claude-opus-4-6-v1", 1_000_000, 0) == 5.0
    assert cost_usd("claude-opus-5-5", 0, 0) == 0.0


def test_a_model_with_no_price_here_is_counted_but_never_priced():
    assert cost_usd("claude-haiku-5-5", 1000, 1000) is None  # its price depends on prompt size: left out
    assert cost_usd("a-model-nobody-listed", 1000, 1000) is None
    row = {"at": "2026-11-20T10:00:00+00:00", "source": "chat", "model": "mystery", "provider": "anthropic",
           "input_tokens": 5, "output_tokens": 6}
    assert priced(row) == {**row, "cost_usd": None}


def test_every_price_in_the_table_is_input_cheaper_than_output_and_positive():
    for model, (cheap, dear) in PRICES.items():
        assert model.startswith("claude-") and 0 < cheap < dear, model


# --- reading what a response or a tool says --------------------------------------------------------------------------

def test_a_response_with_no_usage_counts_nothing_rather_than_zero():
    assert usage_of(SimpleNamespace(usage=SimpleNamespace(input_tokens=7, output_tokens=9))) == (7, 9)
    assert usage_of(SimpleNamespace()) is None
    assert usage_of(SimpleNamespace(usage=SimpleNamespace(input_tokens=None, output_tokens=9))) is None
    assert usage_of(SimpleNamespace(usage=SimpleNamespace(input_tokens=7.5, output_tokens=9))) is None


GOOD = {"model": "claude-opus-5-5", "provider": "anthropic", "input_tokens": 1234, "output_tokens": 567}


def test_a_tools_report_is_taken_only_in_exactly_the_agreed_shape():
    assert usage_from_result(json.dumps({"title": "x", "model_usage": GOOD})) == GOOD
    for bad in (
        {**GOOD, "input_tokens": -1}, {**GOOD, "input_tokens": True}, {**GOOD, "output_tokens": "5"},
        {**GOOD, "input_tokens": 1.5}, {**GOOD, "model": ""}, {**GOOD, "provider": None},
        {k: v for k, v in GOOD.items() if k != "model"}, "5 tokens", [GOOD],
    ):
        assert usage_from_result(json.dumps({"model_usage": bad})) is None, bad


def test_a_result_that_is_not_json_or_not_an_object_reports_nothing():
    assert usage_from_result("Notes written. model_usage: none") is None
    assert usage_from_result('{"model_usage": ') is None  # cut off
    assert usage_from_result(json.dumps([{"model_usage": GOOD}])) is None
    assert usage_from_result("") is None


def test_a_tool_may_not_say_more_than_the_four_fields():
    """Whatever else the result held (a path, a title) is not stored: the row is the four fields and where it came from."""
    taken = usage_from_result(json.dumps({"model_usage": {**GOOD, "cost_usd": 0.0, "note": "x"}}))
    assert taken == GOOD


# --- the stores --------------------------------------------------------------------------------------------------------

def test_the_file_reads_back_newest_first_and_skips_a_corrupt_line(tmp_path):
    store = FileUsageStore(tmp_path / "usage.jsonl")

    async def go():
        await store.record(source="chat", **{**GOOD, "input_tokens": 1})
        (tmp_path / "usage.jsonl").open("a").write("{not json\n[1, 2]\n" + json.dumps({"at": "x"}) + "\n")
        await store.record(source="meet_ai__generate_notes", **{**GOOD, "input_tokens": 2})
        return await store.recent(10), await store.recent(1)

    both, newest = run(go())
    assert [(r["source"], r["input_tokens"]) for r in both] == [("meet_ai__generate_notes", 2), ("chat", 1)]
    assert [r["input_tokens"] for r in newest] == [2]


def test_a_file_that_cannot_be_written_never_breaks_the_work(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where a folder should be")
    store = FileUsageStore(blocker / "usage.jsonl")
    run(store.record(source="chat", **GOOD))  # must not raise
    assert run(store.recent(10)) == []


def test_counting_with_nowhere_to_count_is_a_quiet_nothing():
    run(count_response(None, CONFIG, SimpleNamespace(usage=SimpleNamespace(input_tokens=1, output_tokens=2))))


# --- chat steps and tool reports are counted on their way past ------------------------------------------------------

class FakeModel:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.messages = SimpleNamespace(create=lambda **_: self.answers.pop(0))


class FakeTools:
    def __init__(self, text, is_error=False):
        self.text, self.is_error = text, is_error

    def find(self, name):
        return NOTES if name == NOTES.qualified_name else None

    def anthropic_tools(self):
        return []

    async def preview_of(self, tool, arguments):
        return None

    async def call(self, tool, arguments):
        return SimpleNamespace(text=self.text, is_error=self.is_error)


def reply(tokens, *content, stop_reason="end_turn"):
    usage = SimpleNamespace(input_tokens=tokens[0], output_tokens=tokens[1])
    return SimpleNamespace(content=list(content), stop_reason=stop_reason, usage=usage)


def a_turn(monkeypatch, tmp_path, model, tools, usage):
    monkeypatch.setattr(session, "build_client", lambda config: model)

    async def allow(request):
        return True

    return run(run_turn(tools, CONFIG, [{"role": "user", "content": "hi"}], FileAuditStore(tmp_path / "audit.jsonl"),
                        gate=allow, usage=usage))


def test_every_request_in_a_turn_is_counted_once_with_its_own_tokens(monkeypatch, tmp_path):
    store = FileUsageStore(tmp_path / "usage.jsonl")
    call = SimpleNamespace(type="tool_use", id="t1", name=NOTES.qualified_name, input={})
    model = FakeModel(reply((100, 40), call, stop_reason="tool_use"),
                      reply((260, 15), SimpleNamespace(type="text", text="Done.")))

    a_turn(monkeypatch, tmp_path, model, FakeTools("notes written"), store)

    rows = run(store.recent(10))
    assert [(r["source"], r["input_tokens"], r["output_tokens"]) for r in reversed(rows)] == [
        ("chat", 100, 40), ("chat", 260, 15)]
    assert {(r["model"], r["provider"]) for r in rows} == {("claude-opus-5-5", "anthropic")}


def test_a_turn_with_no_store_runs_as_it_always_did(monkeypatch, tmp_path):
    model = FakeModel(reply((1, 1), SimpleNamespace(type="text", text="Hello.")))
    assert a_turn(monkeypatch, tmp_path, model, FakeTools(""), None) == "Hello."


def test_a_response_that_carries_no_usage_is_not_counted_and_does_not_stop_the_turn(monkeypatch, tmp_path):
    store = FileUsageStore(tmp_path / "usage.jsonl")
    model = FakeModel(SimpleNamespace(content=[SimpleNamespace(type="text", text="Hello.")], stop_reason="end_turn"))
    assert a_turn(monkeypatch, tmp_path, model, FakeTools(""), store) == "Hello."
    assert run(store.recent(10)) == []


def executed(tmp_path, tools, usage):
    async def allow(request):
        return True

    return run(execute(tools, NOTES, {}, FileAuditStore(tmp_path / "audit.jsonl"), allow, usage=usage))


def test_the_tokens_a_tool_reports_are_counted_whoever_asked_for_it(tmp_path):
    store = FileUsageStore(tmp_path / "usage.jsonl")
    output, outcome = executed(tmp_path, FakeTools(json.dumps({"markdown": "m.md", "model_usage": GOOD})), store)

    assert outcome == "ok"
    (row,) = run(store.recent(10))
    assert row["source"] == "meet_ai__generate_notes"
    assert {k: row[k] for k in GOOD} == GOOD
    assert "model_usage" in output  # the tool's answer is passed on untouched


def test_a_failed_call_or_one_that_reports_nothing_counts_nothing(tmp_path):
    store = FileUsageStore(tmp_path / "usage.jsonl")
    report = json.dumps({"model_usage": GOOD})
    assert executed(tmp_path, FakeTools(report, is_error=True), store)[1] == "failed"
    assert executed(tmp_path, FakeTools("Notes written."), store)[1] == "ok"
    assert run(store.recent(10)) == []


# --- what the page is given --------------------------------------------------------------------------------------------

def test_the_page_gets_every_row_with_an_estimated_cost_and_when_counting_began(tmp_path):
    seeded = FileUsageStore(tmp_path / "usage.jsonl")

    async def body(client):
        empty = (await client.get("/api/usage", headers=AUTH)).json()
        await seeded.record(source="chat", **GOOD)
        await seeded.record(source="meet_ai__generate_notes", **{**GOOD, "model": "mystery"})
        full = (await client.get("/api/usage", headers=AUTH)).json()
        cut = (await client.get("/api/usage?limit=1", headers=AUTH)).json()
        return empty, full, cut, (await client.get("/api/usage")).status_code

    empty, full, cut, anonymous = run(with_client(app_for(tmp_path), body))

    assert empty == {"rows": [], "since": None, "complete": True, "prices_as_of": empty["prices_as_of"]}
    assert [r["source"] for r in full["rows"]] == ["meet_ai__generate_notes", "chat"]
    assert [r["cost_usd"] for r in full["rows"]] == [None, round(1234 * 4 / 1e6 + 567 * 20 / 1e6, 6)]
    assert full["since"] == full["rows"][-1]["at"] and full["complete"] is True
    assert len(cut["rows"]) == 1 and cut["complete"] is False  # the limit cut the list short: not "since the start"
    assert anonymous == 401  # the same token guard as every other /api route
