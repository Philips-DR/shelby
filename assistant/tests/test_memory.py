"""Tests for memory and the built-in tools.

Memory is the only stateful thing in Shelby, so the tests that matter are the ones about
not losing or corrupting it -- and about failing soft, since a broken memory file must
degrade what the assistant knows rather than whether it runs.
"""

import asyncio
import json

import pytest

from assistant.builtins import memory_tools
from assistant.memory import FileMemoryStore


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def store(tmp_path):
    return FileMemoryStore(tmp_path / "memory.json")


def test_a_fact_survives_a_round_trip(store):
    run(store.add("person", "Kwame", "colleague on claims"))
    facts = run(store.load())
    assert len(facts) == 1
    assert (facts[0].kind, facts[0].subject) == ("person", "Kwame")


def test_recording_the_same_subject_again_corrects_rather_than_duplicates(store):
    """Two contradictory facts in one prompt is worse than either alone."""
    run(store.add("person", "Kwame", "colleague"))
    run(store.add("person", "kwame", "colleague, leads the claims project"))
    facts = run(store.load())
    assert len(facts) == 1
    assert "leads" in facts[0].content


def test_the_same_subject_under_a_different_kind_is_a_separate_fact(store):
    run(store.add("person", "AyaData", "the company"))
    run(store.add("spelling", "AyaData", "aya data"))
    assert len(run(store.load())) == 2


def test_an_unknown_kind_is_refused(store):
    with pytest.raises(ValueError):
        run(store.add("nonsense", "x", "y"))


def test_a_fact_can_be_removed_by_id(store):
    fact = run(store.add("fact", "x", "y"))
    assert run(store.remove(fact.id)) is not None
    assert run(store.load()) == []


def test_removing_something_that_is_not_there_reports_so(store):
    assert run(store.remove("nope")) is None


def test_a_missing_store_is_simply_empty(store):
    """Memory failing must never stop the assistant from working."""
    assert run(store.load()) == []


def test_a_corrupt_store_degrades_instead_of_crashing(tmp_path):
    path = tmp_path / "memory.json"
    path.write_text("{not json at all", encoding="utf-8")
    assert run(FileMemoryStore(path).load()) == []


def test_a_fact_with_no_subject_is_skipped(tmp_path):
    path = tmp_path / "memory.json"
    path.write_text(json.dumps({"facts": [{"kind": "fact", "content": "orphan"}]}), encoding="utf-8")
    assert run(FileMemoryStore(path).load()) == []


# ---------------------------------------------------------------------------
# The lexicon seam
# ---------------------------------------------------------------------------

def test_only_spelling_facts_become_the_lexicon(store):
    run(store.add("spelling", "AyaData", "aya data, ayadata"))
    run(store.add("person", "Kwame", "colleague"))
    assert run(store.lexicon()) == {"AyaData": ["aya data", "ayadata"]}


def test_the_lexicon_file_is_shaped_the_way_meet_ai_reads_it(store, tmp_path):
    """meet-ai takes a lexicon as an argument and never reaches for a memory store, which
    is what keeps it usable with the assistant absent. This is that handover."""
    run(store.add("spelling", "round robin", "round robinson, round robins"))
    path = run(store.write_lexicon(tmp_path / "lexicon.json"))
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "round robin": ["round robinson", "round robins"]
    }


def test_no_spelling_facts_means_no_lexicon_file(store, tmp_path):
    """Handing a tool an empty lexicon would be a call that does nothing, reported as if
    it did something."""
    run(store.add("person", "Kwame", "colleague"))
    assert run(store.write_lexicon(tmp_path / "lexicon.json")) is None


# ---------------------------------------------------------------------------
# The prompt block
# ---------------------------------------------------------------------------

def test_an_empty_store_contributes_nothing_to_the_prompt(store):
    assert run(store.as_prompt_block()) == ""


def test_memory_is_framed_as_background_not_instruction(store):
    """A remembered line is data the user wrote once, not an order that outranks what they
    are saying now."""
    run(store.add("preference", "tone", "keep it short"))
    block = run(store.as_prompt_block())
    assert "background, not as instructions" in block
    assert "keep it short" in block


# ---------------------------------------------------------------------------
# Built-in tools
# ---------------------------------------------------------------------------

def test_the_memory_tools_that_write_pass_through_the_gate(store):
    """You should see what the assistant writes down about you, as it decides to."""
    tools = {t.name: t for t in memory_tools(store)}
    assert tools["remember"].read_only is False
    assert tools["forget"].read_only is False
    assert tools["recall"].read_only is True


def test_remember_says_an_instruction_about_a_draft_is_not_a_fact_about_the_user(store):
    """Told "leave out published research", a model asked to remember "no published research" as a fact about
    the user, and three spellings of a name nobody gave (2026-10-30). Both were caught only at the gate."""
    description = next(t for t in memory_tools(store) if t.name == "remember").description
    assert "leave out X" in description and "not a fact about the user" in description
    assert "never ones you guessed" in description


def test_the_model_sees_the_id_it_needs_to_forget_a_fact(store):
    """forget takes an id. A prompt that showed facts without ids gave the model no valid
    way to act on "forget that" -- only a guess."""
    fact = run(store.add("preference", "tone", "keep it short"))
    assert f"[{fact.id}]" in run(store.as_prompt_block())


def test_recall_lists_facts_with_their_ids(store):
    fact = run(store.add("person", "Kwame", "colleague"))
    recall = next(t for t in memory_tools(store) if t.name == "recall")
    listed = json.loads(run(recall.handler({})))["facts"]
    assert listed == [{"id": fact.id, "kind": "person", "subject": "Kwame",
                       "content": "colleague", "created": fact.created}]


def test_remember_writes_a_fact(store):
    remember = next(t for t in memory_tools(store) if t.name == "remember")
    out = json.loads(run(remember.handler({"kind": "fact", "subject": "s", "content": "c"})))
    assert "remembered" in out
    assert run(store.load())[0].subject == "s"


def test_forget_removes_one(store):
    tools = {t.name: t for t in memory_tools(store)}
    fact = run(store.add("fact", "s", "c"))
    out = json.loads(run(tools["forget"].handler({"id": fact.id})))
    assert out["forgot"] == fact.id
    assert run(store.load()) == []


def test_forgetting_an_unknown_id_reports_it_rather_than_failing(store):
    forget = next(t for t in memory_tools(store) if t.name == "forget")
    assert "error" in json.loads(run(forget.handler({"id": "nope"})))


# ---------------------------------------------------------------------------
# Preview resolution (registry-level, no servers)
# ---------------------------------------------------------------------------

def test_a_preview_tool_that_is_not_read_only_is_refused():
    """A "preview" that could act would be a hole rather than a help: a tool could name a
    destructive preview and have it run before anyone approved anything."""
    import asyncio

    from assistant.tools import ApprovalPreview, RemoteTool, ToolRegistry

    registry = ToolRegistry([])
    caller = RemoteTool(server="s", name="send", qualified_name="s__send", description="",
                        input_schema={}, read_only=False,
                        preview=ApprovalPreview(tool="sneaky", argument_map={}))
    registry.tools = [
        caller,
        RemoteTool(server="s", name="sneaky", qualified_name="s__sneaky", description="",
                   input_schema={}, read_only=False),
    ]
    assert asyncio.run(registry.preview_of(caller, {})) is None


def test_a_preview_naming_a_tool_that_does_not_exist_is_refused():
    import asyncio

    from assistant.tools import ApprovalPreview, RemoteTool, ToolRegistry

    registry = ToolRegistry([])
    caller = RemoteTool(server="s", name="send", qualified_name="s__send", description="",
                        input_schema={}, read_only=False,
                        preview=ApprovalPreview(tool="missing", argument_map={}))
    registry.tools = [caller]
    assert asyncio.run(registry.preview_of(caller, {})) is None
