#!/usr/bin/env python3
"""Shared plumbing for talking to the mod site.

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
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html import unescape
from http.cookiejar import CookieJar

BASE = "https://sp-mod.com"

# The site moved from forge.sp-tarkov.com to sp-mod.com, which runs the same
# software: the /api/v0/* routes, their parameters and their field names are
# unchanged, so everything below works against it as written. What did not
# come across is authorship -- see merge_with_archive() in scrape_mods.py.
#
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
                    # The site allows 300 requests/minute and says so in
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


# --- folding a scrape into the archive -----------------------------------
#
# The site this reads is not the site the archive was built from. It moved
# from forge.sp-tarkov.com to sp-mod.com, which runs the same software and
# kept the same ids, but does not serve everything the Forge did. So a scrape
# is merged into the archive rather than replacing it.

def load_archive(path, collection):
    """Whatever `path` already holds, keyed by id. Empty on a first run."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return {r["id"]: r for r in json.load(f).get(collection) or []}
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
        print(f"  existing {os.path.basename(path)} is unreadable; "
              f"treating this as a first run", file=sys.stderr)
        return {}


# Above this share of the overlap, a field emptying out is read as an API
# change rather than as data. Deliberately well under half: when sp-mod.com
# replaced the Forge it stopped serving `owner` on *every* mod at once, and a
# scraper that wrote that through would have blanked 1,830 authors and taken
# all 889 author pages with them.
WHOLESALE = 0.25


def merge_with_archive(records, archived, defended, noun="record"):
    """Fold a fresh scrape into what the archive already holds.

    Two rules, and both exist because the listing is no longer the archive's
    only source of truth about itself.

    A field that has emptied out across a quarter of the catalogue at once is
    not news about the mods, it is news about the API -- so the archived value
    is kept and the run says so loudly. Anything below that threshold is real
    and is written through, because one author really can delete their
    description.

    A record the site no longer lists is kept and marked `delisted`. An archive
    outliving the listing is the entire point, so a mod dropping off the site
    is when its record here starts mattering, not when to discard it.

    Returns (records, defended_fields).
    """
    if not archived:
        for record in records:
            record["delisted"] = False
        return records, {}

    overlap = [r for r in records if r["id"] in archived]
    emptied, had = {}, {}
    for record in overlap:
        old = archived[record["id"]]
        for field in defended:
            if not old.get(field):
                continue
            # Counted against the records that *had* the field, never against
            # the whole catalogue. Only 169 mods ever declared a dependency, so
            # when sp-mod.com stopped serving them it emptied 161 records --
            # 95% of the mods that had any, but under 9% of the catalogue. A
            # threshold measured against the catalogue sails straight past
            # that, which is exactly how the first run after the move deleted
            # every dependency in the archive.
            had[field] = had.get(field, 0) + 1
            if not record.get(field):
                emptied[field] = emptied.get(field, 0) + 1

    wholesale = {f: n for f, n in emptied.items()
                 if had.get(f) and n / had[f] >= WHOLESALE}
    for field, count in sorted(wholesale.items()):
        print(f"  !! {field} came back empty on {count} of the {had[field]} "
              f"{noun}s that had it ({count / had[field]:.0%}).\n"
              f"     Reading that as an API change, not as data: keeping the "
              f"archived values.", file=sys.stderr)
        for record in overlap:
            old = archived[record["id"]]
            if old.get(field) and not record.get(field):
                record[field] = old[field]

    for field, count in sorted(emptied.items()):
        if field not in wholesale:
            print(f"  {field} emptied on {count} {noun}(s) -- recorded as-is",
                  file=sys.stderr)

    seen = {r["id"] for r in records}
    for record in records:
        record["delisted"] = False

    gone = []
    for record_id, old in archived.items():
        if record_id in seen:
            continue
        old["delisted"] = True
        gone.append(old)
    if gone:
        print(f"  {len(gone)} archived {noun}(s) are no longer listed on the "
              f"site; keeping them", file=sys.stderr)

    return records + gone, wholesale


# --- authorship across the migration -------------------------------------
#
# sp-mod.com took over the Forge's catalogue but not its accounts: users have
# to reclaim theirs, and until someone does, their mods come back with
# `owner: null`. So authorship arrives gradually, one reclaimed account at a
# time, and every refresh has to answer the same question per author: is this
# person here now, or do we still only have what the Forge told us?
#
# The two id spaces are the reason this needs care. Forge user 27632 is DanW;
# sp-mod.com user 27632, if it ever exists, is somebody else entirely. Keeping
# an archived author under a bare numeric id would eventually merge two
# different people. So an author the live site has not confirmed is stamped
# "27632-arch", which cannot collide with anything sp-mod.com issues, and the
# stamp comes off the moment the account is reclaimed.

ARCH_SUFFIX = "-arch"


def archived_author_id(author_id):
    """Mark an id as the archive's own. Idempotent -- runs re-stamp freely."""
    if author_id in (None, ""):
        return None
    text = str(author_id)
    return text if text.endswith(ARCH_SUFFIX) else text + ARCH_SUFFIX


def is_archived_author(author):
    return str((author or {}).get("id") or "").endswith(ARCH_SUFFIX)


def _key(name):
    return (name or "").strip().casefold()


def reconcile_authors(live, archived):
    """One mod's authors, folding what the site says into what we hold.

    Name is the join, because it is the only thing the two eras share -- the
    ids do not, which is the whole problem. So:

      - An archived author whose name comes back from the site has reclaimed
        their account. The live record wins outright: the "-arch" stamp goes,
        and the id becomes whatever sp-mod.com issued, same or different.
      - An archived author the site still has not named is kept, stamped
        "-arch", and appended after the live ones.

    Reconciling per author rather than per mod matters for the mods with more
    than one: a lead author reclaiming their account should not delete the
    collaborator who has not got round to it yet.

    A reclaimed author who arrives without an avatar inherits the mirrored one,
    since the archive already holds that file and the alternative is a page
    that briefly loses its picture.

    Returns (authors, reclaimed_count).
    """
    live = [a for a in (live or []) if (a or {}).get("name")]
    archived = [a for a in (archived or []) if (a or {}).get("name")]

    if not archived:
        return live, 0
    if not live:
        return ([dict(a, id=archived_author_id(a.get("id"))) for a in archived],
                0)

    was = {_key(a["name"]): a for a in archived}
    out, reclaimed = [], 0
    for author in live:
        author = dict(author)
        previous = was.get(_key(author["name"]))
        if previous:
            # Only a *newly* reclaimed account counts. Once the archived entry
            # has been replaced by a live one, later runs match that live entry
            # instead, and counting those would report the same reclaim every
            # hour forever.
            if is_archived_author(previous):
                reclaimed += 1
            if not author.get("avatar") and previous.get("avatar"):
                author["avatar"] = previous["avatar"]
        out.append(author)

    named = {_key(a["name"]) for a in live}
    for author in archived:
        if _key(author["name"]) not in named:
            out.append(dict(author, id=archived_author_id(author.get("id"))))
    return out, reclaimed
