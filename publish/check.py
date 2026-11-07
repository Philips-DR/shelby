"""./publish-check: what is about to leave this machine for the public repository, looked at before it goes.

`shelby` has been public since 2026-10-24. Making it so needed a hand-built scan of every commit, and each push
since was scanned by hand again. This is that scan, the same every time:

  must fix   a key or token in a known shape, any secret value that is in this machine's own login files,
             and a file that should never be committed (.env, a client secret, a token file, a private key)
  look first an email address, a phone number, a server id, an AWS account number, a public IP address, and
             any word in the git-ignored `.publish-watch` -- unless it is already public on the remote, since
             the public history was left as it is (2026-10-30, the user's call)

By default it reads the commits the remote does not have: every added line, every commit message and every
author's email. `--all` reads every commit ever made, for what must be fixed only. It reads git and the login
files and writes nothing; a secret is never printed, only a few of its characters and where it came from.

Exit: 0 nothing found, 1 something to fix, 2 only something to look at.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# What it looks for
# ---------------------------------------------------------------------------

# Keys and tokens whose shape gives them away. Short, literal, and named, so a finding says what it is.
SECRET_SHAPES: dict[str, re.Pattern[str]] = {name: re.compile(pattern) for name, pattern in {
    "AWS access key": r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",
    "AWS secret key": r"(?i)aws_secret_access_key\s*[=:]\s*['\"]?[A-Za-z0-9/+=]{40}",
    "private key": r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----",
    "Google client secret": r"\bGOCSPX-[A-Za-z0-9_-]{20,}",
    "Google refresh token": r"\b1//0[A-Za-z0-9_-]{30,}",
    "Google access token": r"\bya29\.[A-Za-z0-9_-]{30,}",
    "Google API key": r"\bAIza[0-9A-Za-z_-]{35}\b",
    "Anthropic key": r"\bsk-ant-[A-Za-z0-9_-]{20,}",
    "OpenAI key": r"\bsk-(?!ant-)(?:proj-)?[A-Za-z0-9_-]{32,}",
    "GitHub token": r"\b(?:gh[pousr]_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{60,})\b",
    "Slack token": r"\bxox[abposr]-[A-Za-z0-9-]{10,}",
    "Hugging Face token": r"\bhf_[A-Za-z0-9]{30,}\b",
    "JSON web token": r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
}.items()}

# Files that hold credentials by their nature, whatever is in this copy of them.
FORBIDDEN_FILES = re.compile(
    r"(?:^|/)(?:\.env|\.netrc|credentials(?:\.json)?|token[\w-]*\.json|client_secret[^/]*\.json"
    r"|id_(?:rsa|dsa|ecdsa|ed25519)|[^/]+\.(?:pem|key|p12|pfx))$")
# Files that are a person's data rather than code: the mailbox, memory, the audit log, uploads.
DATA_FILES = re.compile(r"(?:^|/)(?:data|uploads)/|\.(?:sqlite3?|db)$|(?:^|/)(?:memory\.json|audit\.jsonl)$")

EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")
# Addresses that are nobody's: the attribution line, documentation domains, GitHub's own.
EMAIL_ALLOWED = re.compile(r"(?i)^(?:noreply@anthropic\.com|git@github\.com|[^@]+@users\.noreply\.github\.com"
                           r"|[^@]+@(?:[\w-]+\.)*(?:example\.(?:com|org|net)|example|test|invalid|localhost))$")
PHONE = re.compile(r"(?<![\w+])\+\d{1,3}(?:[ -]?\(?\d{1,4}\)?){2,5}(?!\w)")
SERVER_ID = re.compile(r"\bi-(?:[0-9a-f]{17}|[0-9a-f]{8})\b")
ACCOUNT = re.compile(r"\barn:aws[a-z-]*:[a-z0-9-]+:[a-z0-9-]*:(\d{12}):|(?i:\baccount\b)[^\n\d]{0,20}\b(\d{12})\b")
# Not inside a longer dotted number (a version, 1.2.3.4.5), but a full stop that ends a sentence is fine.
IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?!\d|\.\d)")

# Where this machine keeps its logins, relative to the repository or to home. Read for their values only.
SECRET_FILES = (".env", "audiobook/.env", "client_secret*.json", "data/config/**/*.json", "data/config/**/token*",
                "~/.config/docu-ai/*.json", "~/.config/mail-ai/*.json", "~/.aws/credentials", "~/.aws/sso/cache/*.json")
# A key that names a secret by its ending: `token` and `refresh_token` do, `token_uri` and `expiry` do not.
_SECRET_KEY = re.compile(r"(?i)(?:secret|password|passwd|token|api_?key|private_?key)$")
MIN_SECRET = 12


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Finding:
    level: str      # "fix" or "look"
    kind: str
    where: str      # commit and file:line, or commit and what part of it
    shown: str      # what may be printed: never a whole secret


@dataclass
class Report:
    scope: str
    commits: int = 0
    findings: list[Finding] = field(default_factory=list)
    already_public: int = 0

    def add(self, finding: Finding) -> None:
        if finding not in self.findings:
            self.findings.append(finding)

    @property
    def exit_code(self) -> int:
        if any(f.level == "fix" for f in self.findings):
            return 1
        return 2 if self.findings else 0


def mask(value: str) -> str:
    """Enough to recognise a secret by, never enough to use it."""
    return f"{value[:4]}… ({len(value)} characters)"


# ---------------------------------------------------------------------------
# Reading git
# ---------------------------------------------------------------------------

def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, errors="replace")


def remote_ref(repo: Path) -> str | None:
    """What the public side already has: the branch's upstream, or origin's main."""
    for ref in ("@{upstream}", "origin/HEAD", "origin/main", "origin/master"):
        if git(repo, "rev-parse", "--verify", "--quiet", ref).returncode == 0:
            return ref
    return None


@dataclass
class Commit:
    sha: str
    author: str
    committer: str
    message: str
    added: list[tuple[str, int, str]] = field(default_factory=list)   # (path, line number, text)
    files: list[str] = field(default_factory=list)                     # added or changed paths


def commits(repo: Path, revisions: list[str]) -> list[Commit]:
    """Each commit in the range with its added lines. No context lines: only what the commit put there."""
    out = git(repo, "log", "-p", "-U0", "--no-color", "--no-ext-diff", "--no-renames",
              "--format=%x00%H%x01%ae%x01%ce%x01%B%x02", *revisions)
    if out.returncode != 0:
        raise SystemExit(f"publish-check: git log failed: {out.stderr.strip()}")
    found: list[Commit] = []
    for chunk in out.stdout.split("\x00")[1:]:
        header, _, diff = chunk.partition("\x02")
        sha, author, committer, message = header.split("\x01", 3)
        commit = Commit(sha, author, committer, message.strip())
        path, line = "", 0
        for raw in diff.splitlines():
            if raw.startswith("+++ "):
                path = raw[6:] if raw.startswith("+++ b/") else ""
                if path:
                    commit.files.append(path)
            elif raw.startswith("Binary files ") and raw.endswith(" differ"):
                target = raw.rsplit(" and ", 1)[-1].removesuffix(" differ")
                if target.startswith("b/"):
                    commit.files.append(target[2:])
            elif raw.startswith("@@"):
                m = re.search(r"\+(\d+)", raw)
                line = int(m.group(1)) if m else 0
            elif raw.startswith("+") and path:
                commit.added.append((path, line, raw[1:]))
                line += 1
        found.append(commit)
    return found


class Public:
    """What the remote already shows: its files at their latest, and every author's email in its history."""

    def __init__(self, repo: Path, ref: str | None) -> None:
        self.repo, self.ref = repo, ref
        self.emails: set[str] = set()
        if ref:
            log = git(repo, "log", "--format=%ae%n%ce", ref).stdout
            self.emails = {e.strip().lower() for e in log.splitlines() if e.strip()}
        self._seen: dict[str, bool] = {}

    def has(self, text: str) -> bool:
        if not self.ref:
            return False
        if text.lower() in self.emails:
            return True
        if text not in self._seen:
            self._seen[text] = git(self.repo, "grep", "-q", "-F", "-i", "-e", text, self.ref, "--").returncode == 0
        return self._seen[text]


# ---------------------------------------------------------------------------
# This machine's own secrets
# ---------------------------------------------------------------------------

def _values(data: object, key: str = "") -> list[str]:
    """String values under a key that names a secret, anywhere in a JSON document."""
    if isinstance(data, dict):
        return [v for k, item in data.items() for v in _values(item, str(k))]
    if isinstance(data, list):
        return [v for item in data for v in _values(item, key)]
    if isinstance(data, str) and _SECRET_KEY.search(key):
        return [data]
    return []


def known_secrets(repo: Path, patterns: tuple[str, ...] = SECRET_FILES) -> dict[str, str]:
    """Every secret value in this machine's login files, mapped to the file it came from (home as ~)."""
    home = Path.home()
    found: dict[str, str] = {}
    for pattern in patterns:
        base, glob = (home, pattern[2:]) if pattern.startswith("~/") else (repo, pattern)
        for path in sorted(base.glob(glob)):
            if not path.is_file():
                continue
            label = f"~/{path.relative_to(home)}" if base == home else str(path.relative_to(repo))
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            try:
                values = _values(json.loads(text))
            except json.JSONDecodeError:
                # KEY=value lines (.env) and `key = value` lines (~/.aws/credentials).
                values = [v.strip().strip("'\"") for k, _, v in
                          (line.partition("=") for line in text.splitlines() if "=" in line and not line.lstrip().startswith("#"))
                          if _SECRET_KEY.search(k.strip())]
            for value in values:
                if len(value) >= MIN_SECRET and " " not in value and not value.startswith(("http://", "https://")):
                    found.setdefault(value, label)
    return found


def watch_words(repo: Path) -> list[str]:
    """`.publish-watch`, one word or phrase per line: names and details that are private but have no shape.
    It is git-ignored, since it is itself the list of what must not go out."""
    path = repo / ".publish-watch"
    if not path.is_file():
        return []
    return [w.strip() for w in path.read_text(encoding="utf-8").splitlines() if w.strip() and not w.startswith("#")]


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------

def _public_ip(text: str) -> bool:
    try:
        address = ipaddress.IPv4Address(text)
    except ValueError:
        return False
    return address.is_global


def look_for(text: str, watch: list[str]) -> list[tuple[str, str]]:
    """The personal details in one piece of text: (kind, the text found)."""
    found = [("email address", m.group(0)) for m in EMAIL.finditer(text) if not EMAIL_ALLOWED.match(m.group(0))]
    found += [("phone number", m.group(0).strip()) for m in PHONE.finditer(text)
              if 9 <= sum(c.isdigit() for c in m.group(0)) <= 15]
    found += [("server id", m.group(0)) for m in SERVER_ID.finditer(text)]
    found += [("AWS account number", m.group(1) or m.group(2)) for m in ACCOUNT.finditer(text)]
    found += [("public IP address", m.group(0)) for m in IPV4.finditer(text) if _public_ip(m.group(0))]
    lowered = text.lower()
    found += [("watched word", w) for w in watch if w.lower() in lowered]
    return found


def check(repo: Path, all_history: bool = False, secrets: dict[str, str] | None = None,
          watch: list[str] | None = None) -> Report:
    ref = remote_ref(repo)
    if all_history:
        revisions, scope = ["--all"], "every commit"
    else:
        revisions = [f"{ref}..HEAD"] if ref else ["HEAD"]
        scope = f"commits not on {ref}" if ref else "every commit (no remote branch found)"
    report = Report(scope)
    secrets = known_secrets(repo) if secrets is None else secrets
    watch = watch_words(repo) if watch is None else watch
    public = Public(repo, None if all_history else ref)

    for commit in commits(repo, revisions):
        report.commits += 1
        short = commit.sha[:7]
        pieces = [(f"{short} {path}:{line}", text) for path, line, text in commit.added]
        pieces.append((f"{short} commit message", commit.message))

        for where, text in pieces:
            for name, shape in SECRET_SHAPES.items():
                for m in shape.finditer(text):
                    report.add(Finding("fix", name, where, mask(m.group(0))))
            for value, source in secrets.items():
                if value in text:
                    report.add(Finding("fix", f"a secret from {source}", where, mask(value)))

        for path in commit.files:
            if FORBIDDEN_FILES.search(path):   # `.env` exactly: `.env.example` is meant to be shared
                report.add(Finding("fix", "a file that holds credentials", f"{short} {path}", path))
            elif DATA_FILES.search(path) and not all_history:
                report.add(Finding("look", "a file of personal data", f"{short} {path}", path))

        if all_history:
            continue  # the public history was left as it is: only secrets are worth reporting in it
        for where, text in [*pieces, (f"{short} author", commit.author), (f"{short} committer", commit.committer)]:
            for kind, found in look_for(text, watch):
                if public.has(found):
                    report.already_public += 1
                else:
                    report.add(Finding("look", kind, where, found))
    return report


def render(report: Report) -> str:
    lines = [f"publish-check: {report.commits} commit{'s' * (report.commits != 1)} read ({report.scope})."]
    for level, title in (("fix", "MUST FIX before pushing"), ("look", "LOOK AT before pushing")):
        chosen = [f for f in report.findings if f.level == level]
        if chosen:
            lines += ["", f"{title}:"] + [f"  {f.where}  {f.kind}: {f.shown}" for f in chosen]
    if report.already_public:
        lines.append(f"\n{report.already_public} personal detail(s) not listed: already public on the remote.")
    if not report.findings:
        lines.append("Nothing found.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--all", action="store_true", help="every commit ever made, for what must be fixed only")
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parent.parent), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    report = check(Path(args.repo), all_history=args.all)
    print(render(report))
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
