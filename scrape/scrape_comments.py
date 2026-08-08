#!/usr/bin/env python3
"""Archive mod comment threads, which have no public API.

    python3 scrape/scrape_comments.py --probe        # check the handshake works
    python3 scrape/scrape_comments.py --spt '>=4.0.13'   # current-gen mods first
    python3 scrape/scrape_comments.py                # everything else
    python3 scrape/scrape_comments.py --fresh        # re-fetch mods already done

Comments live in a Livewire component that the mod page loads lazily, so there
is no endpoint to call -- we have to perform the same handshake a browser does:

  1. GET the mod page, which issues a session cookie and embeds a CSRF token,
     the (build-hashed) Livewire endpoint, and a signed snapshot of the
     comments component.
  2. POST that snapshot back with a __lazyLoad call to get page one.
  3. POST again with gotoPage(n, 'commentPage') for each further page, each
     time using the snapshot the previous response returned.

That makes this the most fragile part of the archive: it depends on markup and
on a signed checksum we cannot forge, only replay. It is therefore written to
fail loudly. `--probe` verifies the whole chain against one known-good mod, and
a mod whose fetch fails is left absent from the cache so a later run retries it
-- never written as "no comments", which is indistinguishable in the output but
very different in truth.

Results are one file per mod in data/comments/, so an interrupted run keeps
everything it already collected.
"""

import argparse
import json
import os
import re
import sys
import time
from html import unescape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from forge import (LivewireSession, SessionExpired, parse_component,  # noqa: E402
                   parse_csrf, parse_update_uri, scrub_signed_urls)

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
COMMENTS_DIR = os.path.join(DATA, "comments")

COMPONENT = "mod.show.comments-tab"
PAGER_COMPONENT = "comment-component"       # nested; owns gotoPage
PROBE_MOD = (1538, "ref-spt-friendly-quests")   # known to have paged comments

_TAG_RE = re.compile(r"<[^>]+>")
_DIV_RE = re.compile(r"<div\b|</div>", re.I)


# --- HTML helpers --------------------------------------------------------

def strip_tags(fragment):
    return re.sub(r"\s+", " ", unescape(_TAG_RE.sub(" ", fragment))).strip()


def inner_html(html, start):
    """Inner HTML of the div opening at `start`, by balancing div tags."""
    open_tag_end = html.find(">", start)
    if open_tag_end == -1:
        return ""
    depth, pos = 1, open_tag_end + 1
    for m in _DIV_RE.finditer(html, pos):
        depth += 1 if m.group(0).lower().startswith("<div") else -1
        if depth == 0:
            return html[open_tag_end + 1:m.start()].strip()
    return html[open_tag_end + 1:].strip()


def find_body(segment):
    """The comment text itself, kept as HTML so formatting survives."""
    m = re.search(r'<div[^>]*class="[^"]*user-markdown[^"]*"', segment)
    return inner_html(segment, m.start()) if m else ""


def to_int(text, default=0):
    """Digits only. `[\\d,]+` can match a bare comma, which int() rejects."""
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else default


def parse_comment(segment, comment_id, parent_id):
    author = re.search(
        r'<a\s+href="([^"]*?/user/(\d+)/[^"]*)"[^>]*class="font-bold[^"]*"[^>]*>'
        r'(.*?)</a>', segment, re.S)
    stamp = re.search(r'<time\s+datetime="([^"]+)"', segment)
    likes = re.search(r'([\d,]+)\s*Likes?', strip_tags(segment))

    return {
        "id": comment_id,
        "parent_id": parent_id,
        "author": strip_tags(author.group(3)) if author else "",
        "author_id": int(author.group(2)) if author else None,
        "author_url": author.group(1) if author else "",
        "created_at": stamp.group(1) if stamp else "",
        "body_html": scrub_signed_urls(find_body(segment)),
        "likes": to_int(likes.group(1)) if likes else 0,
    }


def parse_comments(html):
    """Every comment on one rendered page, replies attached to their parent.

    Top-level comments and replies are distinguished only by their wire:key,
    and replies are nested inside their parent's markup -- so the segment
    boundaries are taken from the sorted positions of *all* markers, and each
    reply's parent is whichever top-level comment it falls inside.
    """
    markers = (
        [(m.start(), int(m.group(1)), True)
         for m in re.finditer(r'wire:key="comment-container-(\d+)"', html)] +
        [(m.start(), int(m.group(1)), False)
         for m in re.finditer(r'wire:key="reply-(\d+)"', html)]
    )
    markers.sort()

    comments, parent = [], None
    for i, (pos, comment_id, is_top) in enumerate(markers):
        end = markers[i + 1][0] if i + 1 < len(markers) else len(html)
        if is_top:
            parent = comment_id
        comments.append(parse_comment(html[pos:end], comment_id,
                                      None if is_top else parent))
    return comments


def parse_total(html):
    """The "Showing 1 to 10 of 46 results" line, used to verify completeness."""
    m = re.search(r"of\s+([\d,]+)\s+results?", strip_tags(html))
    return to_int(m.group(1), None) if m else None


def parse_last_page(html):
    pages = [int(p) for p in re.findall(r"gotoPage\((\d+),\s*'commentPage'\)", html)]
    return max(pages) if pages else 1


# --- one mod -------------------------------------------------------------

class NoCommentComponent(Exception):
    """The page rendered without a comments tab (mod has comments disabled)."""


def fetch_mod_comments(session, mod_id, slug, max_pages=200):
    """Every comment on one mod. Raises rather than returning partial data."""
    path = f"/mod/{mod_id}/{slug}"
    page_html = session.get_page(path)

    # Both are per-deploy values, so refresh them from every page rather than
    # trusting what a previous mod's page happened to contain.
    session.update_uri = parse_update_uri(page_html) or session.update_uri
    session.csrf = parse_csrf(page_html) or session.csrf
    if not (session.update_uri and session.csrf):
        raise RuntimeError("could not locate Livewire endpoint or CSRF token")

    snapshot, lazy = parse_component(page_html, COMPONENT)
    if not snapshot:
        raise NoCommentComponent()

    if lazy:
        effects, snapshot = session.call(snapshot, "__lazyLoad", [lazy], path)
    else:
        # Already rendered inline; no lazy payload to replay.
        effects = {"html": page_html}

    html = effects.get("html", "")
    total = parse_total(html)
    last_page = parse_last_page(html)

    comments = parse_comments(html)

    # Paging is owned by a *nested* component, not the tab we just loaded --
    # calling gotoPage on the outer snapshot 500s. Its snapshot only exists
    # inside the HTML the lazy load returned.
    if last_page > 1:
        snapshot, _ = parse_component(html, PAGER_COMPONENT)
        if not snapshot:
            raise RuntimeError(f"{PAGER_COMPONENT} snapshot not found; "
                               f"cannot page past 1 of {last_page}")

    for page in range(2, min(last_page, max_pages) + 1):
        effects, snapshot = session.call(
            snapshot, "gotoPage", [page, "commentPage"], path)
        comments.extend(parse_comments(effects.get("html", "")))

    # De-duplicate defensively: a shifting paginator can repeat a comment.
    seen, unique = set(), []
    for c in comments:
        if c["id"] not in seen:
            seen.add(c["id"])
            unique.append(c)

    return {
        "mod_id": mod_id,
        "slug": slug,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "reported_total": total,
        "pages": last_page,
        "count": len(unique),
        "comments": sorted(unique, key=lambda c: c["created_at"]),
    }


# --- driver --------------------------------------------------------------

def probe(session):
    """Verify the whole handshake end to end before a long run."""
    mod_id, slug = PROBE_MOD
    print(f"Probing mod {mod_id} ({slug})...", file=sys.stderr)
    result = fetch_mod_comments(session, mod_id, slug)

    # The Forge's "N results" counts top-level comments only; replies are
    # nested inside them and are not part of that total.
    top = [c for c in result["comments"] if c["parent_id"] is None]
    replies = result["count"] - len(top)

    print(f"  endpoint:   {session.update_uri}", file=sys.stderr)
    print(f"  pages:      {result['pages']}", file=sys.stderr)
    print(f"  reported:   {result['reported_total']} top-level", file=sys.stderr)
    print(f"  parsed:     {len(top)} top-level + {replies} replies", file=sys.stderr)

    sample = next((c for c in result["comments"] if c["body_html"]), None)
    if sample:
        print(f"  sample:     {sample['author']} at {sample['created_at']}: "
              f"{strip_tags(sample['body_html'])[:70]}", file=sys.stderr)

    ok = (result["count"] > 0
          and result["reported_total"] == len(top)
          and all(c["author"] and c["created_at"] and c["body_html"]
                  for c in result["comments"]))
    print(f"\n  {'OK' if ok else 'MISMATCH -- parser needs updating'}",
          file=sys.stderr)
    return 0 if ok else 1


def needs_fetch(mod, fresh, max_age_days):
    """Whether this mod's comments should be (re)fetched.

    Skipping mods that already have a file is what makes an interrupted run
    resumable, but taken alone it also means an archived mod never picks up
    new comments. `max_age_days` reopens that: a thread set older than the
    given age is refetched, so a maintenance run stays incremental instead of
    being all-or-nothing.
    """
    path = os.path.join(COMMENTS_DIR, f"{mod['id']}.json")
    if fresh or not os.path.exists(path):
        return True
    if max_age_days is None:
        return False

    try:
        with open(path) as f:
            fetched = json.load(f).get("fetched_at", "")
        when = time.strptime(fetched, "%Y-%m-%dT%H:%M:%SZ")
    except (json.JSONDecodeError, ValueError, OSError):
        return True     # unreadable or undated: safest to fetch again

    age_days = (time.time() - time.mktime(when) + time.timezone) / 86400
    return age_days >= max_age_days


def load_mods(spt_filter):
    path = os.path.join(DATA, "mods.json")
    if not os.path.exists(path):
        sys.exit("data/mods.json not found -- run scrape_mods.py first")
    with open(path) as f:
        mods = json.load(f)["mods"]

    if spt_filter:
        # Cheap prefix match on the SPT line, e.g. "4." selects 4.x mods.
        mods = [m for m in mods
                if any(c.lstrip("^~>=< ").startswith(spt_filter)
                       for c in m["all_spt_constraints"])]
    return mods


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--probe", action="store_true",
                    help="verify the Livewire handshake and exit")
    ap.add_argument("--spt", default="", help='only mods on an SPT line, e.g. "4."')
    ap.add_argument("--limit", type=int)
    ap.add_argument("--fresh", action="store_true", help="re-fetch mods already done")
    ap.add_argument("--max-age", type=float, metavar="DAYS",
                    help="also refetch thread sets older than DAYS "
                         "(omit to only fetch mods never archived)")
    ap.add_argument("--delay", type=float, default=0.6,
                    help="seconds between requests")
    args = ap.parse_args()

    os.makedirs(COMMENTS_DIR, exist_ok=True)
    session = LivewireSession(delay=args.delay)

    if args.probe:
        return probe(session)

    mods = load_mods(args.spt)
    if args.limit:
        mods = mods[:args.limit]

    todo = [m for m in mods if needs_fetch(m, args.fresh, args.max_age)]
    print(f"{len(mods)} mods in scope, {len(todo)} to fetch", file=sys.stderr)

    stats = {"comments": 0, "with": 0, "none": 0, "failed": 0}
    started = time.time()

    for n, mod in enumerate(todo, 1):
        try:
            result = fetch_mod_comments(session, mod["id"], mod["slug"])
        except NoCommentComponent:
            result = {"mod_id": mod["id"], "slug": mod["slug"], "count": 0,
                      "comments": [], "no_comment_section": True,
                      "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                  time.gmtime())}
        except SessionExpired:
            # The next mod page re-establishes cookies and CSRF, so this mod
            # is simply left for a later run rather than cached as empty.
            print(f"  [{n}] session expired on {mod['id']}; will retry next run",
                  file=sys.stderr)
            stats["failed"] += 1
            continue
        except Exception as e:
            print(f"  [{n}] mod {mod['id']} failed: {type(e).__name__}: {e}",
                  file=sys.stderr)
            stats["failed"] += 1
            continue

        with open(os.path.join(COMMENTS_DIR, f"{mod['id']}.json"), "w") as f:
            json.dump(result, f, indent=1)

        stats["comments"] += result["count"]
        stats["with" if result["count"] else "none"] += 1

        if n % 25 == 0 or n == len(todo):
            rate = n / max(time.time() - started, 1)
            left = (len(todo) - n) / rate if rate else 0
            print(f"  {n}/{len(todo)}  {stats['comments']} comments  "
                  f"~{left / 60:.0f}m left", file=sys.stderr)

    print(f"\nMods with comments: {stats['with']}", file=sys.stderr)
    print(f"Mods without:       {stats['none']}", file=sys.stderr)
    print(f"Comments archived:  {stats['comments']}", file=sys.stderr)
    if stats["failed"]:
        print(f"Failed (retry later): {stats['failed']}", file=sys.stderr)
    print(f"Done in {(time.time() - started) / 60:.1f}m", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
