"""The cloud side check: plain HTTP status and latency, no browser, no
model call. Uptime and the CI failure watch stay here rather than on the
self hosted worker, per docs/mercury.md, because they should not depend on
a machine that sleeps.
"""

import http.client
import ipaddress
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit

# Private and loopback hosts are refused, so a URL from a chat cannot reach
# the environment's internal network. The tests set this, as their servers
# are local. Link local (the 169.254.169.254 metadata address) stays refused.
ALLOW_PRIVATE_HOSTS = False


class _Refused(Exception):
    pass


def _refusal(url: str) -> str | None:
    """Why this URL must not be fetched, or None when it may be.

    shortcut: checks the addresses DNS gives now, so a host that rebinds
    between this lookup and the connection gets through; pin the connection
    to the checked address if a check URL ever comes from someone untrusted.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return f"refused: only http and https URLs are checked, not {url}"
    try:
        infos = socket.getaddrinfo(parts.hostname, None, proto=socket.IPPROTO_TCP)
    except OSError:
        return None  # urlopen reports the lookup failure as the finding
    for info in infos:
        address = ipaddress.ip_address(info[4][0].split("%", 1)[0])
        if address.is_link_local or address.is_multicast or address.is_unspecified:
            return f"refused: {parts.hostname} is {address}, a reserved address"
        if not ALLOW_PRIVATE_HOSTS and not address.is_global:
            return f"refused: {parts.hostname} is {address}, a private address"
    return None


class _RefuseInternalRedirects(urllib.request.HTTPRedirectHandler):
    """Follows redirects as urllib does, refusing a hop _refusal refuses."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        refusal = _refusal(newurl)
        if refusal:
            raise _Refused(refusal)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_RefuseInternalRedirects)


@dataclass(frozen=True)
class SiteCheckResult:
    url: str
    status_code: int | None
    latency_ms: float | None
    passed: bool
    error: str | None = None


def check_site(url: str, timeout_seconds: float = 10.0) -> SiteCheckResult:
    """A 2xx within the timeout passes; redirects are followed first, so the
    status seen is the final hop's. Anything else, including a
    timeout or a connection error, is a finding, not an exception."""
    # Cloudflare refuses urllib's default agent with a 403, as the other
    # clients here (app/github.py, app/d1.py) already found.
    request = urllib.request.Request(url, headers={"User-Agent": "mercury"})
    started = time.monotonic()
    try:
        refusal = _refusal(url)
        if refusal:
            raise _Refused(refusal)
        with _opener.open(request, timeout=timeout_seconds) as response:
            return SiteCheckResult(
                url=url,
                status_code=response.status,
                latency_ms=(time.monotonic() - started) * 1000,
                passed=response.status < 400,
            )
    except urllib.error.HTTPError as error:
        return SiteCheckResult(
            url=url,
            status_code=error.code,
            latency_ms=(time.monotonic() - started) * 1000,
            passed=error.code < 400,
        )
    except (_Refused, urllib.error.URLError, OSError, http.client.HTTPException) as error:
        return SiteCheckResult(
            url=url,
            status_code=None,
            latency_ms=(time.monotonic() - started) * 1000,
            passed=False,
            error=str(error),
        )
