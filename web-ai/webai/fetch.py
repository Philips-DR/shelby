"""One safe GET or HEAD. Every rule from safety.py is applied here, to every request and every redirect.

What it does, and what it never does:

  * GET and HEAD only. No request body, no cookies kept or sent, no login, no proxy (`trust_env=False`
    ignores HTTP_PROXY and ~/.netrc: a proxy would resolve names itself and skip the check).
  * The host is resolved and vetted, then the connection goes to that address -- the URL handed to the HTTP
    client has the address in it, with the real name kept for the `Host` header, for TLS's server name and
    for certificate checking. The name is never resolved a second time.
  * Redirects are followed by hand, up to five, and each one is checked from the start: a public page that
    redirects to http://169.254.169.254/ is refused at that hop.
  * A body larger than 5 MB is cut there, counting what it is *after* decompression, so a few kilobytes of
    gzip cannot become a gigabyte. A request is given 30 s to answer and 60 s in all.
"""

from __future__ import annotations

import asyncio
import ipaddress
import ssl
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import SplitResult, urljoin

import httpx

from webai import VERSION, FetchError
from webai.safety import Policy, Resolver, check_url, is_public, system_resolver, vet

MAX_BYTES = 5_000_000
TIMEOUT = 30.0
CONNECT_TIMEOUT = 10.0     # shorter, so a black-holed address (IPv6 with no route) falls through to the next one
DEADLINE = 60.0
MAX_REDIRECTS = 5
REDIRECTS = {301, 302, 303, 307, 308}
USER_AGENT = f"shelby-web-ai/{VERSION} (a read-only page reader)"
ACCEPT = "text/html,application/xhtml+xml,text/plain;q=0.9,application/json;q=0.5,*/*;q=0.1"


@dataclass
class Fetched:
    url: str                       # as asked
    final_url: str                 # the address that answered, after any redirects
    status: int
    reason: str
    content_type: str              # the media type alone, lower case: "text/html"
    content_type_header: str       # as sent, with its charset
    body: bytes
    truncated: bool
    redirects: list[str] = field(default_factory=list)
    location: str = ""


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _netloc(address: str, port: int | None) -> str:
    host = f"[{address}]" if ":" in address else address
    return f"{host}:{port}" if port else host


def _certificate_problem(error: BaseException) -> bool:
    cause: BaseException | None = error
    while cause is not None:
        if isinstance(cause, ssl.SSLCertVerificationError):
            return True
        cause = cause.__cause__ or cause.__context__
    return False


class Fetcher:
    """Safe by default. `resolver` and `policy` can be replaced, which a test does to reach a server on this
    machine's own loopback; no front door does."""

    def __init__(self, *, resolver: Resolver = system_resolver, policy: Policy = is_public,
                 verify: ssl.SSLContext | bool = True, timeout: float = TIMEOUT, deadline: float = DEADLINE,
                 max_bytes: int = MAX_BYTES, max_redirects: int = MAX_REDIRECTS) -> None:
        self.resolver, self.policy, self.verify = resolver, policy, verify
        self.timeout, self.deadline = timeout, deadline
        self.max_bytes, self.max_redirects = max_bytes, max_redirects

    async def get(self, url: str, check_type: Callable[[str], str | None] | None = None) -> Fetched:
        """A page. `check_type` sees the media type once the headers are in and, if it returns a reason, the
        body is never read and that reason is the error."""
        return await self._run("GET", url, check_type)

    async def head(self, url: str) -> Fetched:
        return await self._run("HEAD", url, None)

    async def _run(self, method: str, url: str, check_type: Callable[[str], str | None] | None) -> Fetched:
        try:
            async with asyncio.timeout(self.deadline):
                return await self._follow(method, url, check_type)
        except TimeoutError:
            raise FetchError(f"The site took longer than {self.deadline:g} seconds, so it was given up on.") from None

    async def _follow(self, method: str, url: str, check_type: Callable[[str], str | None] | None) -> Fetched:
        current, chain = url.strip(), []
        for _ in range(self.max_redirects + 1):
            parts = check_url(current)
            port = parts.port or (443 if parts.scheme == "https" else 80)
            addresses = await vet(parts.hostname or "", port, self.resolver, self.policy)
            fetched = await self._hop(method, parts, addresses, check_type)
            if fetched.status in REDIRECTS and fetched.location:
                current = urljoin(current, fetched.location)
                chain.append(current)
                continue
            fetched.url, fetched.final_url, fetched.redirects = url.strip(), current, chain
            return fetched
        raise FetchError(f"That address redirects more than {self.max_redirects} times.")

    async def _hop(self, method: str, parts: SplitResult, addresses: list[str],
                   check_type: Callable[[str], str | None] | None) -> Fetched:
        host = parts.hostname or ""
        headers = {"Host": parts.netloc, "User-Agent": USER_AGENT, "Accept": ACCEPT}
        # The name to put on the TLS handshake and check the certificate against. An address typed as an
        # address has no name to give.
        extensions = {} if _is_ip(host) else {"sni_hostname": host}
        timeout = httpx.Timeout(self.timeout, connect=min(CONNECT_TIMEOUT, self.timeout))
        # A new client for every hop: no cookie from one response can reach the next request.
        async with httpx.AsyncClient(timeout=timeout, verify=self.verify, follow_redirects=False,
                                     trust_env=False) as client:
            failures: list[str] = []
            for address in addresses:
                target = parts._replace(netloc=_netloc(address, parts.port)).geturl()
                try:
                    async with client.stream(method, target, headers=headers, extensions=extensions) as response:
                        return await self._read(response, method, check_type)
                except httpx.ConnectError as error:
                    if _certificate_problem(error):
                        raise FetchError(f"The security certificate of {host} did not check out, so it was not read.") from None
                    failures.append("failed")             # try the next address
                except httpx.ConnectTimeout:
                    failures.append("timed out")          # and the next
                except httpx.TimeoutException:
                    raise FetchError(f"{host} did not answer within {self.timeout:g} seconds.") from None
                except httpx.HTTPError as error:
                    raise FetchError(f"{host} could not be read ({type(error).__name__}).") from None
        tried = ", ".join(f"{n} {what}" for what, n in Counter(failures).items())
        raise FetchError(f"Could not connect to {host}: it has {len(addresses)} address{'es' if len(addresses) != 1 else ''} "
                         f"and {tried}. If the network is only unreliable, trying again may work.")

    async def _read(self, response: httpx.Response, method: str,
                    check_type: Callable[[str], str | None] | None) -> Fetched:
        header = response.headers.get("content-type", "")
        media = header.split(";", 1)[0].strip().lower()
        if check_type is not None and response.status_code < 300:
            reason = check_type(media)
            if reason:
                raise FetchError(reason)
        body, truncated = bytearray(), False
        if method != "HEAD" and response.status_code not in REDIRECTS:
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > self.max_bytes:
                    del body[self.max_bytes:]
                    truncated = True
                    break
        return Fetched(url="", final_url="", status=response.status_code, reason=response.reason_phrase,
                       content_type=media, content_type_header=header, body=bytes(body), truncated=truncated,
                       location=response.headers.get("location", ""))
