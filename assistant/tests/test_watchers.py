"""Tests for job notifications. The decisions are pure functions, so no server is needed."""

from assistant.watchers import audiobook_notice, login_notice, recording_notice, transcription_notice


def job(state, **extra):
    return {"id": "j1", "audio": "/x/meeting.m4a", "state": state, **extra}


def test_a_finished_transcription_is_announced():
    notice = transcription_notice("running", job("done"))
    assert notice["title"] == "Transcript ready"
    assert "meeting.m4a" in notice["body"]


def test_a_failure_says_why():
    notice = transcription_notice("running", job("failed", detail="ffmpeg could not decode"))
    assert notice["level"] == "error"
    assert "could not decode" in notice["body"]


def test_an_interruption_is_not_called_a_failure():
    """Killed or slept is not an error, and restarting resumes -- so it must not read as one."""
    notice = transcription_notice("running", job("interrupted"))
    assert notice["level"] == "warning"
    assert "resumes" in notice["body"]


def test_nothing_is_announced_on_the_first_sighting_of_a_finished_job():
    """A job that was already done when the server started is old news. Announcing it on every
    restart would teach people to ignore the notifications."""
    assert transcription_notice(None, job("done")) is None


def test_nothing_is_announced_while_a_job_is_still_running():
    assert transcription_notice("running", job("running")) is None


def test_a_recording_that_dies_mid_meeting_is_announced():
    notice = recording_notice("recording", {"id": "r1", "state": "orphaned"})
    assert notice["title"] == "Recording interrupted"


def test_a_recording_stopped_normally_is_not_an_alarm():
    assert recording_notice("recording", None) is None


def test_a_failing_login_is_announced_once_with_the_fix():
    from assistant.status import SIGN_IN_AGAIN
    status = {"level": "error", "hint": SIGN_IN_AGAIN}
    notice = login_notice("ok", status)
    assert notice["title"] == "AWS login needs renewing"
    assert "./auth" in notice["body"]  # the one command, whichever login it was
    assert login_notice("error", status) is None  # not again on every poll


def test_a_login_that_recovers_says_so():
    assert login_notice("error", {"level": "ok"})["title"] == "AWS login working again"
    assert login_notice(None, {"level": "ok"}) is None


def book_job(kind, state, **extra):
    return {"id": "j1", "kind": kind, "target": "/x/uploads/books/Novel.pdf", "state": state, **extra}


def test_each_kind_of_audiobook_job_is_announced_in_its_own_words():
    titles = {kind: audiobook_notice("running", book_job(kind, "done"))["title"]
              for kind in ("analyse", "render", "voice", "sample")}
    assert titles == {"analyse": "Book read", "render": "Audiobook ready",
                      "voice": "Voice cloned", "sample": "Sample ready"}
    assert "Novel.pdf" in audiobook_notice("running", book_job("render", "done"))["body"]


def test_a_failed_or_interrupted_audiobook_job_is_not_called_a_success():
    failed = audiobook_notice("running", book_job("render", "failed", detail="no such voice"))
    assert failed["level"] == "error" and "no such voice" in failed["body"]
    interrupted = audiobook_notice("running", book_job("render", "interrupted"))
    assert interrupted["level"] == "warning" and "resumes" in interrupted["body"]


def test_a_job_the_user_cancelled_is_not_announced_back_to_them():
    assert audiobook_notice("running", book_job("render", "cancelled")) is None


def test_an_old_or_running_audiobook_job_is_not_announced():
    assert audiobook_notice(None, book_job("render", "done")) is None
    assert audiobook_notice("running", book_job("render", "running")) is None
    assert audiobook_notice("running", None) is None
