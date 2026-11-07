"""What this tool hands to the suite for keeping, and letting go of it after (keeping.py). The suite files what
`inventory` lists and then asks `release` to delete the working copies: so release must delete only finished audio
in output/, and only the very copy that was filed."""

import hashlib
import json
from pathlib import Path

import pytest

from audiobook import background, keeping
from audiobook.background import Job


@pytest.fixture
def bench(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # output/ and voices/ are relative to the tool's own folder
    monkeypatch.setattr(keeping, "_tags", lambda path: {"title": "Chapter I", "album": "Great Expectations", "track": "3"})
    monkeypatch.setattr(background, "current", lambda jobs_dir: None)
    (tmp_path / "output").mkdir()
    (tmp_path / "jobs").mkdir()
    return tmp_path


def write(path: Path, data: bytes | str = b"ID3 audio") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    (path.write_bytes if isinstance(data, bytes) else path.write_text)(data)
    return path


def by_key(jobs_dir):
    return {(i["kind"], i["key"]): i for i in keeping.inventory(jobs_dir)["items"]}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_chapter_carries_the_text_its_render_wrote_down_and_is_let_go(bench):
    mp3 = write(bench / "output" / "novel" / "03-chapter-i-0.95x.mp3")
    write(mp3.with_suffix(".json"), json.dumps({"number": 3, "title": "Chapter I", "album": "Great Expectations",
                                                "speed": 0.95, "voice": "abigail", "pdf": "/books/novel.pdf",
                                                "seconds": 812.4, "text": "Chapter I.\n\nMy father's family name…"}))
    item = by_key(bench / "jobs")[("chapter", "novel/03-chapter-i-0.95x.mp3")]
    assert item["labels"] == {"book": "novel", "number": 3, "title": "Chapter I", "album": "Great Expectations",
                              "speed": 0.95, "voice": "abigail", "pdf": "/books/novel.pdf", "seconds": 812.4}
    assert item["text"] == "Chapter I.\n\nMy father's family name…"
    assert item["files"] == [{"path": str(mp3.resolve()), "role": "audio"}] and item["release"] is True


def test_a_chapter_rendered_before_the_text_was_written_down_is_labelled_from_its_own_tags(bench):
    write(bench / "output" / "novel" / "03-chapter-i-0.95x.mp3")
    item = by_key(bench / "jobs")[("chapter", "novel/03-chapter-i-0.95x.mp3")]
    assert item["labels"] == {"book": "novel", "number": 3, "title": "Chapter I", "album": "Great Expectations", "speed": 0.95}
    assert item["text"] is None  # not guessed from today's plan: that may not be what it says


def test_a_whole_book_a_sample_and_a_voice_are_handed_over_and_only_audio_is_let_go(bench):
    write(bench / "output" / "novel" / "great-expectations-0.95x.m4b")
    write(bench / "output" / "voices" / "abigail-test.mp3")
    write(bench / "voices" / "abigail.safetensors", b"state")
    write(bench / "voices" / "abigail.wav", b"RIFF")
    write(bench / "voices" / "abigail.json", json.dumps({"name": "abigail", "kind": "cloned", "source": "voice/abigail.mp3",
                                                         "consent": "My own voice; I agree."}))
    write(bench / "voice" / "abigail.mp3", b"ID3 recording")
    items = by_key(bench / "jobs")
    assert items[("audiobook", "novel/great-expectations-0.95x.m4b")]["release"] is True
    assert items[("sample", "abigail-test.mp3")]["labels"] == {"voice": "abigail"}
    voice = items[("voice", "abigail")]
    assert {f["role"] for f in voice["files"]} == {"state", "sample", "source"}
    assert voice["text"] == "My own voice; I agree." and voice["release"] is False  # a render needs it
    assert not any(k[0] == "chapter" and k[1].startswith("voices/") for k in items)  # samples are not a book


def test_a_finished_job_is_kept_with_its_log_as_a_person_reads_it(bench):
    jobs = bench / "jobs"
    job = Job(id="20261101-render", kind="render", target="/books/novel.pdf", log="", started_at="now", state="done",
              outputs=["/o/03.mp3"])
    write(jobs / f"{job.id}.json", json.dumps(job.__dict__))
    write(jobs / f"{job.id}.log", "Loading\n  [ 10%] chapter 3  \r  [ 90%] chapter 3  \r  [100%] chapter 3\n  -> o/03.mp3\n")
    running = Job(id="20261101-render-2", kind="render", target="/books/other.pdf", log="", started_at="now",
                  state="running")
    write(jobs / f"{running.id}.json", json.dumps(running.__dict__))
    items = by_key(jobs)
    kept = items[("job", job.id)]
    assert kept["text"] == "Loading\n  [100%] chapter 3\n  -> o/03.mp3"
    assert kept["labels"]["outputs"] == ["/o/03.mp3"] and "pid" not in kept["labels"] and kept["release"] is False
    assert ("job", running.id) not in items  # not finished: not yet a record


def test_a_books_corrections_are_kept_beside_its_pdf(bench):
    jobs = bench / "jobs"
    pdf = write(bench / "books" / "novel.pdf", b"%PDF")
    write(pdf.with_suffix(".corrections.txt"), "teh => the\n")
    job = Job(id="j", kind="analyse", target=str(pdf), log="", started_at="now", state="done")
    write(jobs / "j.json", json.dumps(job.__dict__))
    item = by_key(jobs)[("corrections", str(pdf))]
    assert item["text"] == "teh => the\n" and item["files"] == [] and item["release"] is False


def test_while_a_render_runs_only_the_chapters_it_has_finished_are_handed_over(bench, monkeypatch):
    done = write(bench / "output" / "novel" / "03-chapter-i-0.95x.mp3")
    write(bench / "output" / "novel" / "04-chapter-ii-0.95x.mp3")  # being written over right now
    write(bench / "output" / "paper" / "01-intro.mp3")  # another book: not touched by the render
    job = Job(id="j", kind="render", target="/books/novel.pdf", log="", started_at="now", state="running",
              outputs=[str(done)])
    monkeypatch.setattr(background, "current", lambda jobs_dir: job)
    keys = {k for k in by_key(bench / "jobs") if k[0] == "chapter"}
    assert keys == {("chapter", "novel/03-chapter-i-0.95x.mp3"), ("chapter", "paper/01-intro.mp3")}


def test_release_deletes_only_the_filed_copy_of_finished_audio_and_its_text(bench):
    mp3 = write(bench / "output" / "novel" / "03-chapter-i-0.95x.mp3")
    side = write(mp3.with_suffix(".json"), "{}")
    changed = write(bench / "output" / "novel" / "04-chapter-ii-0.95x.mp3")
    voice = write(bench / "voices" / "abigail.safetensors", b"state")
    notes = write(bench / "output" / "novel" / "preview.md", "# text")
    outside = write(bench / "elsewhere.mp3")
    link = bench / "output" / "novel" / "link.mp3"
    link.symlink_to(outside)
    wanted = [
        {"path": str(mp3), "sha256": sha(mp3)},
        {"path": str(changed), "sha256": "0" * 64},  # not the copy that was filed
        {"path": str(voice), "sha256": sha(voice)},  # a working copy a render needs
        {"path": str(notes), "sha256": sha(notes)},  # not audio
        {"path": str(outside), "sha256": sha(outside)},
        {"path": str(link), "sha256": sha(outside)},
        {"path": "output/novel/03-chapter-i-0.95x.mp3", "sha256": sha(mp3)},  # not a full path
    ]
    done = keeping.release(wanted)
    assert done["released"] == [str(mp3)] and len(done["kept"]) == 6
    assert not mp3.exists() and not side.exists()
    assert changed.exists() and voice.exists() and notes.exists() and outside.exists() and link.is_symlink()


def test_a_render_writes_down_beside_each_chapter_exactly_what_it_says(tmp_path, monkeypatch):
    """What the suite keeps with the audio. Written from the chapter as it was spoken, so a later change to the plan
    (a correction, a better reading) does not change what the file is said to say."""
    import numpy as np

    from audiobook import render
    from audiobook.plan import Chapter, Segment

    class Voice(render.ChunkRenderer):
        def __init__(self, narrator):
            pass

        def __call__(self, text):
            return np.ones(len(text.split()) * 100, dtype=np.float32)

        def is_cached(self, text):
            return True

        def choose(self, texts):
            pass

        def missing(self, texts):
            return []

    monkeypatch.setattr(render, "ChunkRenderer", Voice)
    monkeypatch.setattr(render, "encode_mp3", lambda wav, mp3, *a: mp3.write_bytes(b"ID3"))
    told = []
    chapter = Chapter(title="Chapter 6 Knowing the Source", announce="", segments=[
        Segment("paragraph", "The first paragraph.", []), Segment("paragraph", "And the second.", [])])
    render.render_book([(6, chapter)], type("N", (), {"sample_rate": 100})(), tmp_path, "Dreams and Visions", False,
                       0.95, on_chapter_done=lambda mp3, seconds: told.append((mp3, mp3.with_suffix(".json").exists())),
                       labels={"voice": "abigail", "pdf": "/books/dreams.pdf"})
    written = json.loads((tmp_path / "06-chapter-6-knowing-the-source-0.95x.json").read_text())
    assert written["text"] == "Chapter 6.\n\nKnowing the Source\n\nThe first paragraph.\n\nAnd the second."
    assert {k: written[k] for k in ("number", "title", "album", "speed", "voice", "pdf")} == {
        "number": 6, "title": "Chapter 6 Knowing the Source", "album": "Dreams and Visions", "speed": 0.95,
        "voice": "abigail", "pdf": "/books/dreams.pdf"}
    # Written before the render says the chapter is finished, which is when the suite may take it.
    assert told == [(tmp_path / "06-chapter-6-knowing-the-source-0.95x.mp3", True)]


def test_audio_loose_at_the_top_of_output_is_handed_over_too(bench):
    """Found on the real data: four early voice tests sat at the top of output/, in no book's folder. They are the
    user's, so they are kept like the rest, not left behind on the bench."""
    loose = write(bench / "output" / "compare-A-before.mp3")
    write(bench / "output" / "serve.log", "")
    items = by_key(bench / "jobs")
    assert items[("other", "compare-A-before.mp3")]["release"] is True
    assert not any(k[1] == "serve.log" for k in items)
    assert keeping.release([{"path": str(loose), "sha256": sha(loose)}])["released"] == [str(loose)]


def test_each_books_title_and_author_are_handed_over_so_it_can_be_named_without_its_audio(bench):
    """Found live on deploying: once a book's audio was kept and released, the page named it from an old chapter's
    own tag ("Praise for", from an early wrong reading) because the tool no longer listed the book."""
    write(bench / "output" / "dreams" / "plan.json", json.dumps({"title": "Dreams and Visions", "author": "Jane Hamon"}))
    write(bench / "output" / "dreams" / "01-opening-0.95x.mp3")
    write(bench / "output" / "novel" / "01-opening-0.95x.mp3")  # no reading yet: named as its folder is
    (bench / "output" / "empty").mkdir()
    write(bench / "output" / "voices" / "abigail-test.mp3")  # samples are not a book
    items = by_key(bench / "jobs")
    dreams = items[("book", "dreams")]
    assert dreams["labels"] == {"book": "dreams", "title": "Dreams and Visions", "author": "Jane Hamon"}
    assert dreams["files"] == [] and dreams["release"] is False
    assert items[("book", "novel")]["labels"]["title"] == "novel"
    assert not any(k[0] == "book" and k[1] in ("empty", "voices") for k in items)


def test_a_book_whose_audio_has_gone_is_still_named_by_what_remains_of_it(bench):
    write(bench / "output" / "dreams" / "plan.json", json.dumps({"title": "Dreams and Visions", "author": None}))
    write(bench / "output" / "dreams" / "preview.md", "# text")  # only the working files are left
    assert by_key(bench / "jobs")[("book", "dreams")]["labels"]["title"] == "Dreams and Visions"


def test_a_books_title_changing_is_a_new_version_of_it(bench):
    plan = write(bench / "output" / "dreams" / "plan.json", json.dumps({"title": "Praise for", "author": None}))
    first = by_key(bench / "jobs")[("book", "dreams")]["version"]
    plan.write_text(json.dumps({"title": "Dreams and Visions", "author": None}))
    assert by_key(bench / "jobs")[("book", "dreams")]["version"] != first
