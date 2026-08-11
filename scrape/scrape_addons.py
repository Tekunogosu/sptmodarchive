#!/usr/bin/env python3
"""Archive every addon on the Forge into data/addons.json.

    python3 scrape/scrape_addons.py             # everything (~80 addons)
    python3 scrape/scrape_addons.py --limit 5   # small test run

Addons are the Forge's second content type: a file published *against* a
particular mod, most often the Fika-sync shim that makes someone else's mod
work in co-op. They are listed nowhere in the mod API, they have their own
pages, and nothing else preserves them -- mod descriptions already link to
37 of them, and every one of those links dies with whichever site is hosting.

Three endpoints, the same shape as the mod scraper:

  /api/v0/addons              enumerates addons, 50 per page. `include=versions`
                              inlines the version list, but only the teaser.
  /api/v0/addon/{id}          adds the full rendered description.
  /api/v0/addon/{id}/versions the complete version history, uncapped.

Plus the addon's own page, because **the API does not expose an addon's source
repository or its license** -- both are rendered into the HTML and appear in no
endpoint. That is the one thing here worth more than the listing itself: the
repository is where the addon still exists after the Forge does not. It is
plain server-rendered markup, so this needs a page fetch rather than the
Livewire handshake the comments require.

There is no raw cache here, unlike scrape_mods.py. The whole catalogue is two
enumeration requests and two per addon -- under three minutes cold -- so a
cache would add a file, a staleness rule and a compaction step to save a run
that is already short enough to do from scratch every time. Revisit that if
the Forge ever grows addons the way it grew mods.

If enumeration comes back empty -- which is what a dead Forge looks like --
the run aborts without writing, so a failed scrape can never blank an
existing archive.
"""

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from html import unescape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from forge import BASE, Fetcher, LivewireSession, scrub_signed_urls  # noqa: E402
from forge import (is_archived_author, load_archive,          # noqa: E402
                   merge_with_archive, reconcile_authors)

# See forge.merge_with_archive(). `authors` is absent for the same reason it is
# in scrape_mods: sp-mod.com serves `owner: null` on addons too, so authorship
# is reconciled per author rather than defended wholesale.
DEFENDED = ("description_html", "teaser", "versions",
            "source_links", "license", "thumbnail")

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")


# --- per-addon detail ----------------------------------------------------

def fetch_detail(fetcher, addon_id):
    """Full record for one addon, including the long description."""
    data, ok = fetcher.fetch(f"{BASE}/api/v0/addon/{addon_id}")
    return (data or {}).get("data"), ok


def fetch_versions(fetcher, addon_id):
    """Complete version history. The listing inlines only the first few."""
    return fetcher.paginate(f"/api/v0/addon/{addon_id}/versions", {})


# --- the addon page ------------------------------------------------------

# Each fact sits in its own <li>, headed by an <h3>. Anchored on that heading
# rather than on the surrounding classes, which are Tailwind utilities and
# change whenever the Forge is restyled.
_SECTION_RE = r'<h3[^>]*>\s*{}\s*</h3>(.*?)</li>'
# Whole tag first, attributes out of it second. Matching href and an optional
# title in one pattern quietly never captures the title: the optional group is
# free to match empty, and a lazy quantifier before it always prefers that.
_ANCHOR_RE = re.compile(r'<a\s[^>]*>', re.I)
_ATTR_RE = re.compile(r'\b(href|title)="([^"]*)"', re.I)


def _anchors(fragment):
    """Every <a> in a fragment, as {href, title} dicts."""
    out = []
    for tag in _ANCHOR_RE.findall(fragment):
        attrs = {k.lower(): v for k, v in _ATTR_RE.findall(tag)}
        if attrs.get("href"):
            out.append(attrs)
    return out


def parse_addon_page(html):
    """Source repositories and license, which exist only in the page HTML.

    Returns empty values for an addon that genuinely lists neither -- the
    caller distinguishes that from a page it could not fetch, because the two
    are indistinguishable in the output and very different in truth.
    """
    def section(heading):
        match = re.search(_SECTION_RE.format(heading), html, re.S | re.I)
        return match.group(1) if match else ""

    links = []
    for anchor in _anchors(section("Source Code")):
        url = unescape(anchor["href"]).strip()
        if url.startswith("http") and url not in [l["url"] for l in links]:
            links.append({"url": url, "label": ""})

    license_name, license_link = "", ""
    for anchor in _anchors(section("License")):
        license_link = unescape(anchor["href"]).strip()
        license_name = unescape(anchor.get("title", "")).strip()
        break

    return {"source_links": links,
            "license": {"name": license_name, "link": license_link}}


def fetch_page(session, addon):
    """The addon's own page. Returns (parsed, ok)."""
    slug = addon.get("slug") or "addon"
    try:
        html = session.get_page(f"/addon/{addon['id']}/{slug}")
    except Exception:
        return None, False
    return parse_addon_page(html), True


def fetch_one(fetcher, session, addon):
    """All three per-addon fetches, kept or discarded as a unit.

    Returning None on any failure keeps a half-fetched addon out of the
    output entirely, rather than recording it as one with no versions or no
    repository -- indistinguishable afterwards, and very different in truth.
    """
    detail, detail_ok = fetch_detail(fetcher, addon["id"])
    versions, versions_ok = fetch_versions(fetcher, addon["id"])
    page, page_ok = fetch_page(session, addon)
    if not (detail_ok and versions_ok and page_ok):
        return None
    return {"detail": detail, "versions": versions, "page": page}


# --- shaping -------------------------------------------------------------

def norm_version(version):
    return {
        "id": version.get("id"),
        "version": version.get("version", ""),
        "description": scrub_signed_urls(version.get("description") or ""),
        # Which release of the parent mod this addon was built against. The
        # addon equivalent of an SPT constraint, and the only compatibility
        # statement an addon makes.
        "mod_constraint": version.get("mod_version_constraint") or "",
        "downloads": version.get("downloads") or 0,
        "size": version.get("content_length"),
        "link": version.get("link") or "",
        "published_at": version.get("published_at") or "",
    }


def newest_first(versions):
    """Same rule as the mod scraper: only re-sort when every date is present."""
    if versions and all(v.get("published_at") for v in versions):
        return sorted(versions, key=lambda v: v["published_at"], reverse=True)
    return versions


def build_record(listing, fetched):
    """One archive record from the listing entry plus its per-addon payloads."""
    detail = (fetched or {}).get("detail") or {}
    page = (fetched or {}).get("page") or {}
    base = {**listing, **detail}      # detail wins; it is the fuller record

    versions = [norm_version(v) for v in
                newest_first((fetched or {}).get("versions")
                             or base.get("versions") or [])]
    latest = versions[0] if versions else {}

    owner = base.get("owner") or {}
    authors = [{"id": owner.get("id"), "name": owner.get("name", ""),
                "avatar": owner.get("profile_photo_url") or ""}]
    authors += [{"id": a.get("id"), "name": a.get("name", ""),
                 "avatar": a.get("profile_photo_url") or ""}
                for a in base.get("additional_authors") or []]

    return {
        "id": base["id"],
        "name": base.get("name", ""),
        "slug": base.get("slug", ""),
        "teaser": (base.get("teaser") or "").strip(),
        "description_html": scrub_signed_urls(base.get("description") or ""),
        "thumbnail": base.get("thumbnail") or "",
        "forge_url": base.get("detail_url") or "",
        "downloads": base.get("downloads") or 0,
        # The mod this addon extends. Every addon has one until it is
        # detached, which is the Forge's word for an addon whose parent was
        # taken down -- it outlives the mod it was written for.
        "mod_id": base.get("mod_id"),
        "detached": bool(base.get("is_detached")),
        "detached_at": base.get("detached_at") or "",
        # Page-only, both of them: the API exposes neither.
        "source_links": page.get("source_links") or [],
        "license": page.get("license") or {"name": "", "link": ""},
        "authors": [a for a in authors if a["name"]],
        "versions": versions,
        "latest_version": latest.get("version", ""),
        "mod_constraint": latest.get("mod_constraint", ""),
        "published_at": base.get("published_at") or "",
        "updated_at": base.get("updated_at") or "",
        "flags": {
            "contains_ads": bool(base.get("contains_ads")),
            "contains_ai_content": bool(base.get("contains_ai_content")),
            "ai_disclosure": base.get("custom_ai_disclosure") or "",
        },
        "origin": "forge",
    }


def gather(fetcher, session, addons, workers):
    """Fetch every addon's detail, versions and page, retrying what drops."""
    fetched, pending = {}, addons
    for attempt in range(1, 4):
        missed = []
        with ThreadPoolExecutor(workers) as pool:
            for addon, rec in pool.map(
                    lambda a: (a, fetch_one(fetcher, session, a)), pending):
                if rec is None:
                    missed.append(addon)
                else:
                    fetched[str(addon["id"])] = rec
        pending = missed
        if not pending:
            break
        print(f"  retrying {len(pending)} missed (pass {attempt + 1})",
              file=sys.stderr)
        time.sleep(3 * attempt)
    return fetched, pending


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workers", type=int, default=4)
    # Same arithmetic as the mod scraper: 4 workers sleeping 1s each sits at
    # roughly 240 requests/minute, under the Forge's 300.
    ap.add_argument("--delay", type=float, default=1.0,
                    help="seconds each worker waits between requests")
    ap.add_argument("--limit", type=int, help="stop after N addons (testing)")
    args = ap.parse_args()

    os.makedirs(DATA, exist_ok=True)
    fetcher = Fetcher(delay=args.delay)
    started = time.time()

    print("Enumerating addons...", file=sys.stderr)
    listing, listing_ok = fetcher.paginate(
        "/api/v0/addons", {"include": "versions"},
        progress=lambda p, last, got, total: print(
            f"  page {p}/{last}  ({got}/{total or '?'})", file=sys.stderr))

    if not listing_ok:
        print("Enumeration was incomplete, so addons are missing from this "
              "run. Aborting rather than writing a truncated archive.",
              file=sys.stderr)
        return 1

    if not listing:
        print("No addons returned -- the Forge may be gone. Aborting without "
              "touching existing data.", file=sys.stderr)
        return 1

    seen, addons = set(), []
    for a in listing:
        if a["id"] not in seen:
            seen.add(a["id"])
            addons.append(a)
    if len(addons) != len(listing):
        print(f"  dropped {len(listing) - len(addons)} duplicate rows",
              file=sys.stderr)
    if args.limit:
        addons = addons[:args.limit]

    print(f"\nPer-addon detail, versions and page for {len(addons)} addons...",
          file=sys.stderr)
    # One session shared by every worker: the page fetches are ordinary GETs,
    # but they go through Cloudflare, which wants a browser-shaped client.
    session = LivewireSession(delay=args.delay)
    fetched, unresolved = gather(fetcher, session, addons, args.workers)

    if unresolved:
        print(f"{len(unresolved)} addon(s) could not be fetched. Aborting "
              f"rather than writing a partial catalogue; re-run to retry.",
              file=sys.stderr)
        return 1

    records = [build_record(a, fetched.get(str(a["id"]))) for a in addons]

    # Folded into the archive rather than replacing it, exactly as mods are:
    # an addon the site stops listing is kept and marked, and a field that
    # empties out across the whole catalogue is read as an API change.
    archived = load_archive(os.path.join(DATA, "addons.json"), "addons")
    if archived and not args.limit:
        # Same stamping as mods, and it has to be the same: an author with a
        # mod and an addon is one person, and if only one of the two carried
        # the "-arch" mark they would come out as two author pages.
        live = 0
        for record in records:
            old = archived.get(record["id"])
            if old:
                record["authors"], _ = reconcile_authors(
                    record["authors"], old.get("authors") or [])
            if any(not is_archived_author(a) for a in record["authors"]):
                live += 1
        for addon_id, old in archived.items():
            if addon_id not in {r["id"] for r in records} and old.get("authors"):
                old["authors"], _ = reconcile_authors([], old["authors"])
        print(f"  authorship: {live} addon(s) named by the site, "
              f"{len(records) - live} still archive-only", file=sys.stderr)

        records, _ = merge_with_archive(records, archived, DEFENDED,
                                        noun="addon")
    elif archived:
        print("  --limit set: skipping the archive merge, not writing "
              "addons.json", file=sys.stderr)

    # Sorted by id for the same reason mods.json is: the file is committed and
    # re-scraped often, and id is the one key that never moves.
    records.sort(key=lambda r: r["id"])

    out = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": BASE,
        "addon_count": len(records),
        "addons": records,
    }
    path = os.path.join(DATA, "addons.json")
    if args.limit and archived:
        print(f"\nDry run: {len(records)} addon(s) built, addons.json left "
              f"alone.", file=sys.stderr)
        return 0
    with open(path, "w") as f:
        json.dump(out, f, indent=1)

    parents = {r["mod_id"] for r in records if r["mod_id"]}
    print(f"\nAddons:      {len(records)}", file=sys.stderr)
    print(f"Parent mods: {len(parents)}", file=sys.stderr)
    print(f"Detached:    {sum(1 for r in records if r['detached'])}",
          file=sys.stderr)
    # Printed because these come from parsing markup rather than an API: a
    # restyle that breaks the parser shows up here as a sudden zero, which is
    # the only warning this kind of scraping ever gives.
    print(f"With source: {sum(1 for r in records if r['source_links'])}",
          file=sys.stderr)
    print(f"With license:{sum(1 for r in records if r['license']['name'])}",
          file=sys.stderr)
    print(f"Authors:     {len({a['id'] for r in records for a in r['authors']})}",
          file=sys.stderr)

    if fetcher.failures:
        print(f"\n{len(fetcher.failures)} request(s) failed after retries:",
              file=sys.stderr)
        for url, why in fetcher.failures[:5]:
            print(f"  {why}  {url}", file=sys.stderr)

    print(f"\nWrote {path} in {time.time() - started:.0f}s "
          f"({fetcher.count} requests)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
