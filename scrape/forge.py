#!/usr/bin/env python3
"""Shared plumbing for talking to the Forge.

Two very different channels live here:

  Fetcher       the public JSON API at /api/v0/*. Simple, documented enough,
                and the source of every mod field we keep.

  LivewireSession
                the comment threads, which have no API at all. They are
                rendered by a Livewire component that the page loads lazily,
                so reading them means impersonating the browser handshake.
                See scrape_comments.py for what that costs us.

Both retry on the failure modes the Forge actually exhibits (429s and 5xx
under load) and count what they could not recover, because a dropped request
that returns empty data is indistinguishable from a mod with no data.
"""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from html import unescape
from http.cookiejar import CookieJar

BASE = "https://forge.sp-tarkov.com"

# The API is happy with an honest identifier. The Livewire endpoint sits
# behind Cloudflare and is only served to something that looks like a browser.
API_UA = "Mozilla/5.0 (SPT mod archive; personal archival script)"
BROWSER_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

PAGE_SIZE = 50          # the server caps per_page at 50 whatever we ask for
RETRY_CODES = (429, 500, 502, 503, 504)


class Fetcher:
    """JSON GET with retry/backoff. Records failures instead of hiding them."""

    def __init__(self, delay=0.0):
        self.failures = []
        self.delay = delay
        self.count = 0

    def fetch(self, url, attempts=6):
        """Return (data, ok). `ok` is False only when the request failed.

        A 404 is a definitive answer, not a failure: it yields (None, True).
        The distinction matters everywhere, because a dropped request and an
        empty result look identical downstream -- that is how a rate-limited
        run quietly records hundreds of mods as having no versions.
        """
        for attempt in range(attempts):
            if self.delay:
                time.sleep(self.delay)
            try:
                req = urllib.request.Request(
                    url, headers={"Accept": "application/json",
                                  "User-Agent": API_UA})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    self.count += 1
                    return json.loads(resp.read().decode("utf-8", "replace")), True
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None, True
                if e.code in RETRY_CODES:
                    if attempt == attempts - 1:
                        self.failures.append((url, f"HTTP {e.code} (gave up)"))
                        return None, False
                    # The Forge allows 300 requests/minute and says so in
                    # Retry-After when we exceed it. Honour that rather than
                    # guessing, then back off geometrically for plain 5xx.
                    wait = e.headers.get("Retry-After") if e.headers else None
                    time.sleep(float(wait) if wait and wait.isdigit()
                               else 2 ** attempt * 2)
                    continue
                self.failures.append((url, f"HTTP {e.code}"))
                return None, False
            except Exception as e:
                if attempt == attempts - 1:
                    self.failures.append((url, type(e).__name__))
                    return None, False
                time.sleep(2 ** attempt)
        return None, False

    def get(self, url, attempts=6):
        """fetch() for callers that cannot act on the difference."""
        return self.fetch(url, attempts)[0]

    def paginate(self, path, params, progress=None):
        """Walk a paginated collection. Returns (rows, ok).

        The Forge's default ordering is not stable across pages, so callers
        should pass an explicit sort where the endpoint supports one. Without
        it, rows shift between requests and mods are both duplicated and
        skipped. `ok` is False if any page failed, so a partial collection is
        never mistaken for a complete one.
        """
        page, rows = 1, []
        while True:
            qs = urllib.parse.urlencode({**params, "page": page,
                                         "per_page": PAGE_SIZE})
            data, ok = self.fetch(f"{BASE}{path}?{qs}")
            if not ok:
                return rows, False
            if not data or not data.get("data"):
                break
            rows.extend(data["data"])
            meta = data.get("meta", {})
            last = meta.get("last_page", page)
            if progress:
                progress(page, last, len(rows), meta.get("total"))
            if page >= last:
                break
            page += 1
        return rows, True


class LivewireSession:
    """A browser-shaped session for driving the comment component.

    Livewire is a server-rendered component framework: the page ships a
    *snapshot* of each component's state, and the client posts that snapshot
    back alongside a method call to get new HTML. Nothing here is a public
    interface, so every piece is discovered from the page rather than assumed:

      - the update endpoint carries a build hash (/livewire-<hash>/update)
        that changes when the Forge redeploys
      - the CSRF token must match the session cookie issued by the same fetch
      - the component snapshot embeds a signed checksum, so it cannot be
        synthesised, only replayed

    Consequently this class is inherently fragile. It is verified against the
    live site at import time by scrape_comments.py's --probe, and every failure
    is surfaced loudly rather than being logged as "no comments".
    """

    def __init__(self, delay=0.5):
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar))
        self.delay = delay
        self.update_uri = None
        self.csrf = None

    # --- low level -------------------------------------------------------

    def _open(self, req, attempts=4):
        for attempt in range(attempts):
            time.sleep(self.delay)
            try:
                with self.opener.open(req, timeout=45) as resp:
                    return resp.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                # 419 means the session/CSRF pair went stale; the caller has to
                # re-read a mod page, so report it distinctly.
                if e.code == 419:
                    raise SessionExpired()
                if e.code in RETRY_CODES and attempt < attempts - 1:
                    time.sleep(2 ** attempt * 2)
                    continue
                raise
            except Exception:
                if attempt == attempts - 1:
                    raise
                time.sleep(2 ** attempt)

    def get_page(self, path):
        req = urllib.request.Request(f"{BASE}{path}", headers={
            "User-Agent": BROWSER_UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        })
        return self._open(req)

    def call(self, snapshot, method, params, referer):
        """Invoke one method on a component and return the effects payload."""
        body = json.dumps({
            "_token": self.csrf,
            "components": [{
                "snapshot": snapshot,
                "updates": {},
                "calls": [{"path": "", "method": method, "params": params}],
            }],
        }).encode()

        req = urllib.request.Request(self.update_uri, data=body, headers={
            "Content-Type": "application/json",
            "Accept": "*/*",
            "X-Livewire": "1",
            "X-CSRF-TOKEN": self.csrf,
            "User-Agent": BROWSER_UA,
            "Referer": f"{BASE}{referer}",
            "Origin": BASE,
        })
        payload = json.loads(self._open(req))
        component = payload["components"][0]
        return component.get("effects", {}), component.get("snapshot")


class SessionExpired(Exception):
    """The Livewire session or CSRF token is no longer accepted."""


# --- parsing the bits of the page Livewire needs -------------------------

_SNAPSHOT_RE = re.compile(r'wire:snapshot="(.*?)"(?=\s+wire:)', re.S)
_LAZY_RE = re.compile(r'__lazyLoad\((?:&#039;|&quot;|\')([^&\')]+)')


# Query separators appear as "&amp;" as often as "&", because this HTML is
# escaped -- matching only the bare form silently scrubs nothing.
_SIGNED_PARAMS_RE = re.compile(
    r"(?:\?|&amp;|&)"
    r"(?:X-Amz-[A-Za-z-]*|Signature|Expires|GoogleAccessId|AWSAccessKeyId)"
    r"=[^\"'\s&<]*", re.I)


def scrub_signed_urls(html):
    """Strip signing parameters from URLs in archived HTML.

    Mod descriptions and comments frequently embed images that GitHub serves
    from S3 via pre-signed URLs. Those carry `X-Amz-Credential=AKIA...`, which
    is GitHub's own access key *id* -- an identifier, not a credential, and the
    signature expires within hours, so the parameters are worthless to keep.

    They are removed anyway, because secret scanners match the AKIA shape and
    will block a push containing them. Scrubbing here means the archive stays
    pushable no matter what a re-scrape picks up, rather than needing a
    per-string exemption every time. The URL itself is preserved, so the record
    of where an image lived survives.
    """
    if not html or "X-Amz-" not in html and "Signature=" not in html:
        return html
    return _SIGNED_PARAMS_RE.sub("", html)


def parse_update_uri(page_html):
    """The Livewire endpoint, whose path contains a per-deploy build hash."""
    m = re.search(r'"uri":"([^"]*livewire[^"]*)"', page_html)
    return json.loads(f'"{m.group(1)}"') if m else None


def parse_csrf(page_html):
    m = re.search(r'name="csrf-token"\s+content="([^"]+)"', page_html)
    return m.group(1) if m else None


def parse_component(page_html, name):
    """Find one Livewire component by name, returning (snapshot, lazy_param).

    Components appear as a div carrying its state; a lazily-loaded one also
    carries the opaque payload to hand back to __lazyLoad. Both are extracted
    from the same tag so they cannot be mismatched across components.
    """
    marker = page_html.find(f'wire:name="{name}"')
    if marker == -1:
        return None, None

    start = page_html.rfind("<div", 0, marker)
    tag = page_html[start:page_html.find(">", marker) + 1]

    snap = _SNAPSHOT_RE.search(tag)
    lazy = _LAZY_RE.search(tag)
    return (unescape(snap.group(1)) if snap else None,
            lazy.group(1) if lazy else None)
