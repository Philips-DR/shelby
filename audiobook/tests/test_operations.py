"""What a model (or the suite's web app) can ask of the tool, against the saved test paper."""

import gzip
from pathlib import Path

import pytest
from docling_core.types.doc import DoclingDocument

from audiobook import background, operations
from audiobook.names import chapter_stem
from audiobook.plan import build_plan

FIXTURE = Path(__file__).parent / "fixtures/paper.docling.json.gz"


@pytest.fixture
def analysed(monkeypatch, tmp_path):
    """A PDF the tool believes Docling has already read, with the real plan of the test paper."""
    doc = DoclingDocument.model_validate_json(gzip.decompress(FIXTURE.read_bytes()))
    plan = build_plan(doc, file_name="paper")
    monkeypatch.setattr("audiobook.extract.is_extracted", lambda pdf: True)
    monkeypatch.setattr(operations, "plan_book", lambda pdf: plan)
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 stand-in")
    return pdf


def test_output_dir_uses_the_cleaned_title(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    clean = operations.output_dir(Path("Overcoming Addictive Behavior (Author [A, B]) (z-library.sk, 1lib.sk).pdf"))
    assert clean == Path("output/Overcoming Addictive Behavior")
    clean = operations.output_dir(Path("_OceanofPDF.com_The_King_Is_Coming_-_John_Bevere.pdf"))
    assert clean == Path("output/The King Is Coming")
    assert operations.output_dir(Path("final-quest.pdf")) == Path("output/final-quest")
    assert operations.output_dir(Path("2609.09153v1.pdf")) == Path("output/2609.09153v1")


def test_output_dir_falls_back_to_old_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    old = tmp_path / "output" / "Big Title (Author [A, B]) (Z-Library)"
    old.mkdir(parents=True)
    (old / "01-opening-0.95x.mp3").write_bytes(b"x")
    result = operations.output_dir(Path("Big Title (Author [A, B]) (Z-Library).pdf"))
    assert result.name == "Big Title (Author [A, B]) (Z-Library)"


def test_selection_of_chapters():
    assert operations.parse_selection("1-3,5", 6) == [1, 2, 3, 5]
    assert operations.parse_selection(" 2 ", 6) == [2]
    with pytest.raises(ValueError, match="no chapter 7: this book has 6"):
        operations.parse_selection("1,7", 6)
    with pytest.raises(ValueError, match="chapters must look like"):
        operations.parse_selection("first", 6)


def test_a_chapter_selection_cannot_be_backwards_or_enormous():
    """A reversed range used to select nothing -- and "nothing selected" means "render everything"."""
    with pytest.raises(ValueError, match="runs backwards: write it as 3-5"):
        operations.parse_selection("5-3", 6)
    with pytest.raises(ValueError, match="no chapter 99999999999"):
        operations.parse_selection("1-99999999999", 6)  # returns at once; it never builds that range
    with pytest.raises(ValueError, match="no chapter 0"):
        operations.parse_selection("0-2", 6)


def test_speed_and_pdf_checks(tmp_path):
    assert operations.check_speed(0.95) == 0.95
    with pytest.raises(ValueError, match="between 0.5 and 2.0"):
        operations.check_speed(5)
    with pytest.raises(ValueError, match="not a PDF"):
        operations.pdf_file(tmp_path / "notes.txt")
    with pytest.raises(FileNotFoundError):
        operations.pdf_file(tmp_path / "missing.pdf")


def test_an_unanalysed_pdf_says_what_to_do_instead_of_waiting(monkeypatch, tmp_path):
    monkeypatch.setattr("audiobook.extract.is_extracted", lambda pdf: False)
    pdf = tmp_path / "new.pdf"
    pdf.write_bytes(b"%PDF")
    overview = operations.book_overview(pdf)
    assert overview["analysed"] is False and "start_analysis" in overview["hint"]
    # Named before it is read, from its file name: the library listed it as the whole of that.
    named = tmp_path / "Ann Writer - Rivers of Light (2004, Some House ) - libgen.li-1.pdf"
    named.write_bytes(b"%PDF")
    overview = operations.book_overview(named)
    assert (overview["title"], overview["author"]) == ("Rivers of Light", "Ann Writer")
    with pytest.raises(ValueError, match="start_analysis"):
        operations.chapter_text(pdf, 1)
    with pytest.raises(ValueError, match="start_analysis"):
        operations.start_render(pdf, "alba", tmp_path / "jobs")


def test_overview_of_the_paper(analysed):
    overview = operations.book_overview(analysed)
    assert overview["analysed"] and overview["title"].startswith("Procedural Graphs")
    labels = [c["label"] for c in overview["chapters"]]
    assert labels[:3] == ["Opening", "1. Introduction", "2. Related Work"]
    assert overview["chapters"][0]["number"] == 1
    assert overview["skipped"] and overview["render_time"]


def test_the_overview_gives_each_chapter_its_audio_and_keeps_the_rest_apart(analysed, monkeypatch, tmp_path):
    """So the page can put a play button on a chapter's own row. A file from an earlier reading, when the chapters
    were found differently, has the same number and another title: it belongs to no chapter of this one."""
    monkeypatch.chdir(tmp_path)  # output/ is relative to the tool's own folder
    folder = tmp_path / "output/paper"
    folder.mkdir(parents=True)
    title = operations.plan_book(analysed).chapters[1].title
    mine = f"{chapter_stem(2, title)}-0.95x.mp3"
    for name in (mine, "02-an-older-reading-0.95x.mp3", "procedural-graphs-0.95x.m4b"):
        (folder / name).write_bytes(b"x")
    overview = operations.book_overview(analysed)
    assert [(a["name"], a["speed"]) for a in overview["chapters"][1]["audio"]] == [(mine, 0.95)]
    assert overview["chapters"][0]["audio"] == []
    assert {a["name"] for a in overview["other_audio"]} == {"02-an-older-reading-0.95x.mp3", "procedural-graphs-0.95x.m4b"}


def test_a_listed_book_carries_its_title_not_only_its_file_name(tmp_path):
    """The folder is named for the PDF, which can be 120 characters of title, subtitle, author and download site."""
    read = tmp_path / "Dreams Long Subtitle Here (Ann Writer [Writer, Ann]) (Z-Library)"
    unread = tmp_path / "Rivers and Seas A Guide (Bo Lake) (z-lib.org)"
    for folder in (read, unread, tmp_path / "voices"):
        folder.mkdir()
        (folder / "01-opening.mp3").write_bytes(b"x")
    (read / "plan.json").write_text('{"title": "Dreams", "author": "Ann Writer", "chapters": []}')
    books = {b["book"]: (b["title"], b["author"]) for b in operations.list_audiobooks(tmp_path)}
    assert books[read.name] == ("Dreams", "Ann Writer")  # as reading the book found it
    assert books[unread.name] == ("Rivers and Seas A Guide", "Bo Lake")  # from the file name alone
    assert books["voices"] == ("Voice samples", None)


def test_a_job_names_its_book_by_title(analysed, monkeypatch, tmp_path):
    """The job card and the Overview showed "Rendering: <120 characters of file name>.pdf"."""
    started = []

    def start(kind, target, jobs_dir, arguments, title=None):
        started.append(title)
        return background.Job(id="j", kind=kind, target=target, log="", started_at="now", title=title)

    monkeypatch.setattr(operations.background, "start", start)
    unread = tmp_path / "Rivers and Seas A Guide (Bo Lake) (Z-Library).pdf"
    unread.write_bytes(b"%PDF-1.4 stand-in")  # pdfium cannot open it, so its file name names it
    assert operations.start_analysis(unread, tmp_path / "jobs")["title"] == "Rivers and Seas A Guide"
    operations.start_render(analysed, "alba", tmp_path / "jobs")
    assert started[-1].startswith("Procedural Graphs")  # as reading the book found it


def test_reading_a_chapter_pages_through_it(analysed):
    whole = operations.chapter_text(analysed, 2, limit_chars=10**9)
    assert whole["truncated"] is False and whole["segments"][0]["kind"] in ("heading", "paragraph")
    first = operations.chapter_text(analysed, 2, limit_chars=500)
    assert first["truncated"] and first["next_start"] == len(first["segments"])
    rest = operations.chapter_text(analysed, 2, start=first["next_start"], limit_chars=10**9)
    assert first["segments"] + rest["segments"] == whole["segments"]
    with pytest.raises(ValueError, match="no chapter 99"):
        operations.chapter_text(analysed, 99)


def test_corrections_round_trip_and_report_what_was_ignored(analysed):
    assert operations.get_corrections(analysed)["text"] == ""
    result = operations.set_corrections(analysed, "# names\nProcedural Graph => PG\nthis line has a typo\n")
    assert (result["pairs"], result["ignored"]) == (1, ["this line has a typo"])
    assert "Procedural Graph => PG" in operations.get_corrections(analysed)["text"]
    assert operations.book_overview(analysed)["corrections"].endswith("paper.corrections.txt")


def test_a_correction_with_nothing_to_find_is_ignored_not_applied(analysed):
    """`=> PG` would replace "" and put PG between every character of the book."""
    result = operations.set_corrections(analysed, "=> PG\n   => x\nreal => fixed\n")
    assert (result["pairs"], result["ignored"]) == (1, ["=> PG", "=> x"])
    from audiobook.speech import apply_corrections, parse_corrections
    assert apply_corrections("some text", parse_corrections("=> PG")) == "some text"


def test_a_sample_is_for_a_voice_by_name_never_a_path(tmp_path, monkeypatch):
    clip = tmp_path / "me.wav"
    clip.write_bytes(b"RIFF")
    monkeypatch.setattr("audiobook.voices.list_voices", lambda: [_voice("alba", "preset")])
    with pytest.raises(ValueError, match="no voice"):
        operations.start_voice_sample(str(clip), tmp_path / "jobs")  # would write beside the clip
    assert operations.check_voice(str(clip)) == str(clip)  # a render may clone from a file...
    monkeypatch.setenv("HOME", str(tmp_path))
    assert operations.check_voice("~/me.wav") == str(clip)  # ...and gets the path the job can use


def test_render_is_refused_before_a_job_exists_for_anything_that_would_fail(analysed, tmp_path, monkeypatch):
    jobs = tmp_path / "jobs"
    monkeypatch.setattr("audiobook.voices.list_voices", lambda: [])
    with pytest.raises(ValueError, match="between 0.5"):
        operations.start_render(analysed, "alba", jobs, speed=9)
    with pytest.raises(ValueError, match="no voice 'nobody'"):
        operations.start_render(analysed, "nobody", jobs)
    monkeypatch.setattr("audiobook.voices.list_voices", lambda: [_voice("alba", "preset")])
    with pytest.raises(ValueError, match="no chapter 40"):
        operations.start_render(analysed, "alba", jobs, chapters="40")
    assert not jobs.exists() or not list(jobs.glob("*.json"))


def _voice(name, kind):
    from audiobook.voices import Voice

    return Voice(name, kind)


def test_a_clone_needs_a_consent_statement_and_a_sound_name(tmp_path):
    clip = tmp_path / "clip.wav"
    clip.write_bytes(b"RIFF")
    jobs = tmp_path / "jobs"
    with pytest.raises(ValueError, match="consent"):
        operations.start_voice_clone("tina", clip, "  ", jobs)
    with pytest.raises(ValueError, match="lowercase"):
        operations.start_voice_clone("Tina Turner", clip, "my own voice", jobs)
    with pytest.raises(ValueError, match="built-in"):
        operations.start_voice_clone("alba", clip, "my own voice", jobs)
    with pytest.raises(FileNotFoundError):
        operations.start_voice_clone("tina-2", tmp_path / "nope.wav", "my own voice", jobs)
    assert not jobs.exists() or not list(jobs.glob("*.json"))


def test_finished_audio_is_listed_newest_first(tmp_path):
    (tmp_path / "old").mkdir()
    (tmp_path / "old/01.mp3").write_bytes(b"x" * 10)
    (tmp_path / "new").mkdir()
    (tmp_path / "new/book.m4b").write_bytes(b"x" * 20)
    (tmp_path / "new/notes.txt").write_text("not audio")
    (tmp_path / "empty").mkdir()
    import os
    os.utime(tmp_path / "old/01.mp3", (1, 1))
    books = operations.list_audiobooks(tmp_path)
    assert [b["book"] for b in books] == ["new", "old"]
    assert [f["name"] for f in books[0]["files"]] == ["book.m4b"]
    assert books[0]["files"][0]["modified"] > 0  # lets the page tell a re-rendered file from the old one
    assert operations.list_audiobooks(tmp_path / "missing") == []
