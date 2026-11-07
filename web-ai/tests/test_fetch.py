"""The fetcher, against a real server on this machine's loopback. Each test says what was put on the wire or
refused, because that is what the fetcher is for."""

import asyncio
import gzip
import shutil
import ssl
import subprocess
import time

import pytest

from fakesite import Site, fetcher, html
from webai import FetchError
from webai.fetch import Fetcher


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# What goes on the wire
# ---------------------------------------------------------------------------

def test_a_page_is_fetched_with_its_real_name_in_host_and_nothing_else_added():
    with Site({"/jobs": html("<p>hi</p>")}) as site:
        got = run(fetcher({"jobs.test": ["127.0.0.1"]}).get(site.url("/jobs", "jobs.test")))
    sent = site.requests[0]
    assert (got.status, got.body, got.content_type) == (200, b"<p>hi</p>", "text/html")
    assert sent["method"] == "GET"
    assert sent["headers"]["host"] == f"jobs.test:{site.port}"          # the name, though the connection went to the address
    assert sent["headers"]["user-agent"].startswith("shelby-web-ai/")
    assert not {"cookie", "authorization", "referer", "proxy-authorization"} & set(sent["headers"])


def test_the_name_is_resolved_once_per_request_and_the_connection_goes_to_that_answer():
    """Resolving a second time would let a hostile DNS answer differently the second time (rebinding)."""
    with Site({"/": html("ok")}) as site:
        f = fetcher({"jobs.test": ["127.0.0.1"]})
        run(f.get(site.url("/", "jobs.test")))
    assert f.resolved == ["jobs.test"]


def test_a_cookie_set_by_one_response_is_not_sent_on_the_next_request():
    routes = {"/first": (302, {"Location": "/second", "Set-Cookie": "session=abc123; Path=/"}, b""),
              "/second": html("done")}
    with Site(routes) as site:
        got = run(fetcher().get(site.url("/first")))
    assert got.body == b"done"
    assert "cookie" not in site.requests[1]["headers"]


def test_the_proxy_settings_of_the_environment_are_ignored(monkeypatch):
    """A proxy resolves names itself, which would walk around the address check."""
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:9")
    with Site({"/": html("direct")}) as site:
        assert run(fetcher().get(site.url())).body == b"direct"


def test_head_asks_for_no_body_and_reads_none():
    with Site({"/big": html("x" * 100_000)}) as site:
        got = run(fetcher().head(site.url("/big")))
    assert site.requests[0]["method"] == "HEAD"
    assert (got.status, got.body, got.content_type) == (200, b"", "text/html")


def test_the_second_address_is_tried_when_the_first_does_not_answer():
    with Site({"/": html("second")}) as site:
        got = run(fetcher({"two.test": ["127.0.0.3", "127.0.0.1"]}, allowed=("127.0.0.1", "127.0.0.3"))
                  .get(site.url("/", "two.test")))
    assert got.body == b"second"


def test_when_no_address_answers_the_error_says_how_many_were_tried_and_what_happened():
    """Found on the real network: "could not connect" hid that every address had timed out."""
    with pytest.raises(FetchError, match=r"has 2 addresses and 2 failed\. If the network is only unreliable"):
        run(fetcher({"down.test": ["127.0.0.5", "127.0.0.6"]}, allowed=("127.0.0.5", "127.0.0.6"))
            .get("http://down.test:9/"))


# ---------------------------------------------------------------------------
# What is refused
# ---------------------------------------------------------------------------

def test_the_default_fetcher_refuses_this_machine_and_never_connects():
    """No policy given, so the real one: the fake server is on 127.0.0.1 and must not be reached."""
    with Site({"/": html("secret")}) as site:
        with pytest.raises(FetchError, match="not a public internet address"):
            run(Fetcher().get(site.url()))
    assert site.requests == []


def test_a_redirect_to_an_address_that_is_not_allowed_is_refused_at_that_hop():
    with Site({"/": html("inside")}, host="127.0.0.2") as private:
        with Site({"/go": (302, {"Location": private.url("/")}, b"")}) as public:
            with pytest.raises(FetchError, match="127.0.0.2.*not a public internet address"):
                run(fetcher().get(public.url("/go")))
        assert private.requests == []          # the second server was never spoken to


def test_a_redirect_to_a_file_or_another_scheme_is_refused():
    with Site({"/": (302, {"Location": "file:///etc/passwd"}, b"")}) as site:
        with pytest.raises(FetchError, match="Only http and https"):
            run(fetcher().get(site.url()))


def test_a_chain_of_redirects_is_followed_and_remembered_up_to_a_limit():
    routes = {f"/{n}": (301, {"Location": f"/{n + 1}"}, b"") for n in range(10)}
    routes["/3"] = html("arrived")
    routes["/0"] = (301, {"Location": "/1"}, b"")
    with Site(routes) as site:
        got = run(fetcher().get(site.url("/0")))
        assert got.body == b"arrived" and got.final_url == site.url("/3")
        assert got.redirects == [site.url("/1"), site.url("/2"), site.url("/3")]
        with pytest.raises(FetchError, match="redirects more than 2 times"):
            run(fetcher(max_redirects=2).get(site.url("/0")))


def test_a_redirect_loop_ends():
    with Site({"/a": (302, {"Location": "/b"}, b""), "/b": (302, {"Location": "/a"}, b"")}) as site:
        with pytest.raises(FetchError, match="redirects more than"):
            run(fetcher().get(site.url("/a")))


def test_a_file_type_the_caller_does_not_want_is_refused_from_the_headers():
    def refuse(media):
        return "no PDFs" if media == "application/pdf" else None

    with Site({"/cv": (200, {"Content-Type": "application/pdf"}, b"%PDF-1.4 ...")}) as site:
        with pytest.raises(FetchError, match="no PDFs"):
            run(fetcher().get(site.url("/cv"), check_type=refuse))


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------

def test_a_body_longer_than_the_cap_is_cut_and_said_to_be():
    with Site({"/": html("y" * 50_000)}) as site:
        got = run(fetcher(max_bytes=10_000).get(site.url()))
    assert len(got.body) == 10_000 and got.truncated is True


def test_a_few_kilobytes_of_gzip_cannot_become_a_gigabyte():
    """The cap counts bytes after decompression, so a compressed bomb is stopped at the cap."""
    bomb = gzip.compress(b"A" * 80_000_000)
    assert len(bomb) < 200_000
    with Site({"/": (200, {"Content-Type": "text/plain", "Content-Encoding": "gzip"}, bomb)}) as site:
        got = run(fetcher(max_bytes=1_000_000).get(site.url()))
    assert len(got.body) == 1_000_000 and got.truncated and set(got.body) == {ord("A")}


def test_a_site_that_does_not_answer_is_given_up_on():
    def slow(_request):
        time.sleep(2)
        return html("late")

    with Site({"/": slow}) as site:
        started = time.monotonic()
        with pytest.raises(FetchError, match="did not answer within 0.3 seconds"):
            run(fetcher(timeout=0.3).get(site.url()))
        assert time.monotonic() - started < 1.5


def test_the_whole_request_has_a_deadline_too():
    def slow(_request):
        time.sleep(2)
        return html("late")

    with Site({"/": slow}) as site:
        with pytest.raises(FetchError, match="took longer than 0.4 seconds"):
            run(fetcher(timeout=10, deadline=0.4).get(site.url()))


# ---------------------------------------------------------------------------
# A certificate is checked against the NAME, though the connection goes to an address
# ---------------------------------------------------------------------------

def make_certificate(directory, name: str):
    key, cert = str(directory / f"{name}.key"), str(directory / f"{name}.crt")
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", cert,
                    "-days", "2", "-subj", f"/CN={name}", "-addext", f"subjectAltName=DNS:{name}"],
                   check=True, capture_output=True)
    return cert, key


needs_openssl = pytest.mark.skipif(shutil.which("openssl") is None, reason="needs the openssl command")


@needs_openssl
def test_https_checks_the_certificate_against_the_name_not_the_address(tmp_path):
    good, good_key = make_certificate(tmp_path, "site.test")
    other, other_key = make_certificate(tmp_path, "other.test")
    trusting_both = ssl.create_default_context()
    trusting_both.load_verify_locations(good)
    trusting_both.load_verify_locations(other)

    with Site({"/": html("secure")}, certificate=(good, good_key)) as right, \
         Site({"/": html("wrong cert")}, certificate=(other, other_key)) as wrong:
        names = {"site.test": ["127.0.0.1"]}
        f = fetcher(names, verify=trusting_both)
        got = run(f.get(f"https://site.test:{right.port}/"))
        assert got.body == b"secure"
        # A trusted certificate, but for another name: it must fail for the name that was asked for.
        with pytest.raises(FetchError, match="security certificate of site.test did not check out"):
            run(f.get(f"https://site.test:{wrong.port}/"))
