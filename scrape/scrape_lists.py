#!/usr/bin/env python3
"""Archive the Forge's user-curated mod lists into data/lists.json.

    python3 scrape/scrape_lists.py            # every list
    python3 scrape/scrape_lists.py --limit 5  # small test run
    python3 scrape/scrape_lists.py --fresh    # ignore the cache

Mod lists are the closest thing the Forge has to a working modpack: somebody
picked a set of mods that run together on a given SPT version and published
it. That curation is knowledge no repository contains, and it disappears with
the site, so it is worth as much as the mod records themselves.

There is no API for them, but unlike comments they need no Livewire handshake
-- the list pages server-render their mods, so this is ordinary HTML scraping:

  /lists            paginated index, ~13 lists per page
  /list/{id}/{slug} the list itself, with every mod id in the markup

Cheap enough to re-run at will: roughly one request per list.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from html import unescape

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
BASE = "https://forge.sp-tarkov.com"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

LIST_HREF_RE = re.compile(r'href="' + BASE + r'/list/(\d+)/([a-z0-9-]+)"')
MOD_HREF_RE = re.compile(r'href="' + BASE + r'/mod/(\d+)/')
USER_RE = re.compile(r'href="' + BASE + r'/user/(\d+)/([a-z0-9-]+)"')
TIME_RE = re.compile(r'<time[^>]*datetime="([^"]+)"')
H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
TAG_RE = re.compile(r"<[^>]+>")


def text_of(fragment):
    return re.sub(r"\s+", " ", unescape(TAG_RE.sub(" ", fragment))).strip()


def fetch(url, delay=0.4, attempts=4):
    for attempt in range(attempts):
        time.sleep(delay)
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA, "Accept": "text/html,application/xhtml+xml"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if attempt == attempts - 1:
                return None
            time.sleep(2 ** attempt * 2)
        except Exception:
            if attempt == attempts - 1:
                return None
            time.sleep(2 ** attempt)
    return None


# --- index ---------------------------------------------------------------

def find_lists(page_html):
    """(id, slug) for every list linked from an index page, in page order."""
    seen, out = set(), []
    for list_id, slug in LIST_HREF_RE.findall(page_html):
        if list_id not in seen:
            seen.add(list_id)
            out.append((int(list_id), slug))
    return out


def last_page(page_html):
    pages = [int(p) for p in re.findall(r"gotoPage\((\d+)", page_html)]
    return max(pages) if pages else 1


def enumerate_lists(delay):
    """Every list on the Forge. Returns (lists, complete)."""
    first = fetch(f"{BASE}/lists", delay)
    if not first:
        return [], False

    total_pages = last_page(first)
    found, complete = find_lists(first), True

    for page in range(2, total_pages + 1):
        html = fetch(f"{BASE}/lists?page={page}", delay)
        if not html:
            complete = False        # a gap here means lists would go missing
            print(f"  page {page} failed", file=sys.stderr)
            continue
        found += find_lists(html)
        print(f"  page {page}/{total_pages} ({len(found)} lists)", file=sys.stderr)

    seen, unique = set(), []
    for entry in found:
        if entry[0] not in seen:
            seen.add(entry[0])
            unique.append(entry)
    return unique, complete


# --- one list ------------------------------------------------------------

def parse_list(html, list_id, slug):
    """Everything a list page holds, or None if it does not look like one."""
    mod_ids, seen = [], set()
    for mod_id in MOD_HREF_RE.findall(html):
        value = int(mod_id)
        if value not in seen:
            seen.add(value)
            mod_ids.append(value)

    titles = [text_of(h) for h in H1_RE.findall(html)]
    # The first <h1> is the site masthead; the list's own title follows.
    title = next((t for t in titles if t and t.lower() != "forge"), "")

    owner_id, owner_name = None, ""
    for uid, uslug in USER_RE.findall(html):
        owner_id, owner_name = int(uid), uslug
        break

    plain = text_of(html)
    spt = re.search(r"\bSPT\s+([0-9][0-9.]*)", plain)
    visibility = "public" if re.search(r"\bPublic\b", plain) else ""

    stamps = sorted(TIME_RE.findall(html))
    description = ""
    meta = re.search(r'property="og:description"\s+content="([^"]*)"', html)
    if meta:
        description = unescape(meta.group(1))

    if not title and not mod_ids:
        return None

    return {
        "id": list_id,
        "slug": slug,
        "title": title,
        "description": description,
        "owner": {"id": owner_id, "name": owner_name},
        "spt_version": spt.group(1) if spt else "",
        "visibility": visibility,
        "mod_ids": mod_ids,
        "mod_count": len(mod_ids),
        "created_at": stamps[0] if stamps else "",
        "updated_at": stamps[-1] if stamps else "",
        "forge_url": f"{BASE}/list/{list_id}/{slug}",
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--fresh", action="store_true", help="ignore the cache")
    ap.add_argument("--delay", type=float, default=0.4,
                    help="seconds between requests")
    args = ap.parse_args()

    os.makedirs(DATA, exist_ok=True)
    path = os.path.join(DATA, "lists.json")

    cached = {}
    if not args.fresh and os.path.exists(path):
        with open(path) as f:
            try:
                cached = {str(l["id"]): l for l in json.load(f).get("lists", [])}
            except (json.JSONDecodeError, KeyError):
                cached = {}

    started = time.time()
    print("Enumerating mod lists...", file=sys.stderr)
    found, complete = enumerate_lists(args.delay)

    if not found:
        print("No lists returned -- the Forge may be gone. Aborting without "
              "touching existing data.", file=sys.stderr)
        return 1
    if not complete:
        print("Enumeration was incomplete; aborting rather than writing a "
              "truncated archive. Re-run to try again.", file=sys.stderr)
        return 1

    if args.limit:
        found = found[:args.limit]
    print(f"\n{len(found)} lists; fetching...", file=sys.stderr)

    lists, failed = [], 0
    for n, (list_id, slug) in enumerate(found, 1):
        html = fetch(f"{BASE}/list/{list_id}/{slug}", args.delay)
        record = parse_list(html, list_id, slug) if html else None
        if record is None:
            # Keep whatever we archived previously rather than dropping a list
            # because one fetch failed.
            if str(list_id) in cached:
                lists.append(cached[str(list_id)])
            failed += 1
        else:
            lists.append(record)
        if n % 25 == 0 or n == len(found):
            print(f"  {n}/{len(found)}", file=sys.stderr)

    out = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": BASE,
        "list_count": len(lists),
        "lists": sorted(lists, key=lambda l: -l["mod_count"]),
    }
    with open(path, "w") as f:
        json.dump(out, f, indent=1, sort_keys=True)

    total_mods = sum(l["mod_count"] for l in lists)
    print(f"\nLists:        {len(lists)}", file=sys.stderr)
    print(f"Mod entries:  {total_mods:,}", file=sys.stderr)
    print(f"Largest:      {max((l['mod_count'] for l in lists), default=0)} mods",
          file=sys.stderr)
    if failed:
        print(f"Failed:       {failed} (re-run to retry)", file=sys.stderr)
    print(f"\nWrote {path} in {time.time() - started:.0f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
