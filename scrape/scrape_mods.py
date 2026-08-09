#!/usr/bin/env python3
"""Archive every mod on the Forge into data/mods.json.

    python3 scrape/scrape_mods.py               # everything (~1,800 mods)
    python3 scrape/scrape_mods.py --spt '4.*'   # only mods matching a filter
    python3 scrape/scrape_mods.py --fresh       # ignore the cache
    python3 scrape/scrape_mods.py --limit 20    # small test run

Three passes, because no single endpoint carries everything:

  /api/v0/mods              enumerates mods, 50 per page. Gives the listing
                            fields but only the short teaser.
  /api/v0/mod/{id}          adds the full rendered description, which is the
                            part most worth preserving and exists nowhere else.
  /api/v0/mod/{id}/versions adds dependencies and the *complete* version
                            history; both other endpoints cap versions at 10.

Per-mod results are cached in data/raw_mods.jsonl keyed by the mod's
updated_at, so a re-run only refetches mods that actually changed.

If enumeration comes back empty -- which is what a dead Forge looks like --
the run aborts without writing, so a failed scrape can never blank an
existing archive.
"""

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from forge import BASE, PAGE_SIZE, Fetcher, scrub_signed_urls  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")


# --- per-mod detail ------------------------------------------------------

def fetch_detail(fetcher, mod_id):
    """Full record for one mod, including the long description."""
    url = (f"{BASE}/api/v0/mod/{mod_id}"
           "?include=versions,license,category,source_code_links")
    data, ok = fetcher.fetch(url)
    return (data or {}).get("data"), ok


def fetch_versions(fetcher, mod_id):
    """Complete version history with dependencies.

    This endpoint 500s if given a `sort` parameter, and returns pages in no
    dependable order, so ordering is imposed afterwards by newest_first().
    """
    return fetcher.paginate(f"/api/v0/mod/{mod_id}/versions",
                            {"include": "dependencies"})


def fetch_one(fetcher, mod):
    """Both per-mod requests, cached as a unit or not at all.

    Returning None on any failure is deliberate: a half-fetched mod that got
    cached would look permanently dependency-free, and the cache would never
    revisit it because its updated_at had not changed.
    """
    detail, detail_ok = fetch_detail(fetcher, mod["id"])
    versions, versions_ok = fetch_versions(fetcher, mod["id"])
    if not (detail_ok and versions_ok):
        return None
    # Scrubbed on the way in, so what lands in the committed cache is already
    # safe to push even if the run never reaches compaction.
    return scrub_record({"id": mod["id"], "stamp": mod.get("updated_at"),
                         "detail": detail, "versions": versions})


# --- shaping -------------------------------------------------------------

def norm_dependency(dep):
    """Dependency rows vary in shape; keep what is present, drop the rest."""
    mod_id = dep.get("id")
    slug = dep.get("slug", "")
    return {
        "id": mod_id,
        "name": dep.get("name", ""),
        "slug": slug,
        "constraint": dep.get("constraint") or dep.get("version_constraint") or "",
        "url": f"{BASE}/mod/{mod_id}/{slug}" if mod_id else "",
    }


def norm_version(version):
    deps = [norm_dependency(d) for d in version.get("dependencies") or []]
    return {
        "id": version.get("id"),
        "version": version.get("version", ""),
        "description": scrub_signed_urls(version.get("description") or ""),
        "spt_constraint": version.get("spt_version_constraint") or "",
        "fika": version.get("fika_compatibility") or "unknown",
        "downloads": version.get("downloads") or 0,
        "size": version.get("content_length"),
        "link": version.get("link") or "",
        "published_at": version.get("published_at") or "",
        "dependencies": deps,
    }


def union_dependencies(versions):
    """Every mod this one has ever depended on, first-seen order."""
    seen, out = set(), []
    for version in versions:
        for dep in version["dependencies"]:
            if dep["id"] not in seen:
                seen.add(dep["id"])
                out.append(dep)
    return out


def newest_first(versions):
    """The API returns versions newest-first; re-sort only when we safely can."""
    if versions and all(v.get("published_at") for v in versions):
        return sorted(versions, key=lambda v: v["published_at"], reverse=True)
    return versions


def build_record(listing, cached, overrides):
    """One archive record from the listing entry plus its per-mod payloads."""
    detail = (cached or {}).get("detail") or {}
    base = {**listing, **detail}      # detail wins; it is the fuller record

    versions = newest_first((cached or {}).get("versions")
                            or base.get("versions") or [])
    versions = [norm_version(v) for v in versions]
    latest = versions[0] if versions else {}

    links = [{"url": l.get("url", ""), "label": l.get("label", "")}
             for l in base.get("source_code_links") or [] if l.get("url")]

    # A manual correction outranks whatever the Forge lists, but never
    # discards the original -- a dead link is still evidence of where a mod was.
    override = overrides.get(str(base["id"]))
    if override and override.get("source_code_url"):
        fixed = override["source_code_url"]
        links = ([{"url": fixed, "label": override.get("label", "corrected")}]
                 + [l for l in links if l["url"] != fixed])

    owner = base.get("owner") or {}
    authors = [{"id": owner.get("id"), "name": owner.get("name", ""),
                "avatar": owner.get("profile_photo_url") or ""}]
    authors += [{"id": a.get("id"), "name": a.get("name", ""),
                 "avatar": a.get("profile_photo_url") or ""}
                for a in base.get("additional_authors") or []]

    category = base.get("category") or {}

    return {
        "id": base["id"],
        "hub_id": base.get("hub_id"),
        "guid": base.get("guid"),
        "name": base.get("name", ""),
        "slug": base.get("slug", ""),
        "teaser": (base.get("teaser") or "").strip(),
        "description_html": scrub_signed_urls(base.get("description") or ""),
        "thumbnail": base.get("thumbnail") or "",
        "forge_url": base.get("detail_url") or "",
        "downloads": base.get("downloads") or 0,
        "favourites": base.get("favourites_count") or 0,
        "featured": bool(base.get("featured")),
        "fika": bool(base.get("fika_compatibility")),
        "fika_latest": latest.get("fika", "unknown"),
        "category": {"id": category.get("id"), "title": category.get("title", ""),
                     "slug": category.get("slug", "")} if category else None,
        "license": {"name": (base.get("license") or {}).get("name", ""),
                    "link": (base.get("license") or {}).get("link", "")},
        "authors": [a for a in authors if a["name"]],
        "source_links": links,
        "versions": versions,
        "latest_version": latest.get("version", ""),
        "spt_constraint": latest.get("spt_constraint", ""),
        "all_spt_constraints": sorted({v["spt_constraint"] for v in versions
                                       if v["spt_constraint"]}),
        # Dependencies are declared per version. The latest version is what a
        # user installing today needs; the union is what the archive knows
        # about, and is what "mods that need CommonLib" should search against,
        # since a mod may have dropped or gained a dependency over time.
        "dependencies": latest.get("dependencies", []),
        "all_dependencies": union_dependencies(versions),
        "published_at": base.get("published_at") or "",
        "updated_at": base.get("updated_at") or "",
        "flags": {
            "contains_ads": bool(base.get("contains_ads")),
            "contains_ai_content": bool(base.get("contains_ai_content")),
            "ai_disclosure": base.get("custom_ai_disclosure") or "",
            "cheat_notice": bool(base.get("cheat_notice")),
            "profile_binding_notice": bool(base.get("shows_profile_binding_notice")),
        },
        "origin": "forge",
    }


# --- cache ---------------------------------------------------------------

def load_cache(path):
    if not os.path.exists(path):
        return {}
    cache = {}
    with open(path) as f:
        for line in f:
            try:
                rec = json.loads(line)
                cache[str(rec["id"])] = rec
            except (json.JSONDecodeError, KeyError):
                continue
    return cache


def scrub_record(value):
    """Apply scrub_signed_urls() to every string in a nested payload.

    The cache holds the API's raw responses, which is the point of keeping it
    -- but "raw" cannot include AWS pre-signed parameters now that the file is
    committed. GitHub serves images from S3 with `X-Amz-Credential=AKIA...`,
    and push protection matches that shape and rejects the push.

    build_record() already scrubs the two description fields on their way into
    mods.json. This covers every field of the payload, including the ones the
    archive does not otherwise keep.

    Scrubbing the serialised line instead would be shorter and wrong: inside
    JSON, a signed URL in an HTML attribute ends at \\", and the trailing
    backslash falls inside the pattern's character class -- so it would eat the
    escape and leave the file unparseable.
    """
    if isinstance(value, str):
        return scrub_signed_urls(value)
    if isinstance(value, list):
        return [scrub_record(v) for v in value]
    if isinstance(value, dict):
        return {k: scrub_record(v) for k, v in value.items()}
    return value


def compact_cache(path):
    """Rewrite the cache as one line per mod, sorted by id.

    Records are *appended* during a run, which is what makes an interrupted run
    resumable -- but it also means a refetched mod leaves its old record behind
    forever. That is invisible while the file is a local scratch file, and
    unacceptable once it is committed: the file would grow without bound and
    every duplicate would be dead weight in the repository.

    Compacting afterwards gets both. The run keeps appending as it goes, and
    the finished file is stable, deduplicated, and diffs one line per mod that
    actually changed -- the same reason repos.json is written with sorted keys.

    It re-reads from disk rather than taking the in-memory cache, so that
    --fresh, --limit and --spt (which only ever hold a subset in memory) cannot
    drop the records they were not asked about. The replace is atomic, so an
    interrupted compaction leaves the original intact.
    """
    cache = load_cache(path)
    if not cache:
        return 0

    def key(record):
        value = record.get("id")
        return (0, value, "") if isinstance(value, int) else (1, 0, str(value))

    # Scrubbed here as well as at fetch time, so records written before this
    # was added -- or by a run that died before compacting -- are healed rather
    # than sitting in the file waiting to block a push.
    temp = f"{path}.tmp"
    with open(temp, "w") as f:
        for record in sorted(cache.values(), key=key):
            f.write(json.dumps(scrub_record(record)) + "\n")
    os.replace(temp, path)
    return len(cache)


def gather(fetcher, mods, cache_path, workers, fresh):
    """Fetch per-mod payloads, reusing cache entries for unchanged mods."""
    cache = {} if fresh else load_cache(cache_path)
    stale = [m for m in mods
             if cache.get(str(m["id"]), {}).get("stamp") != m.get("updated_at")]
    print(f"  {len(mods) - len(stale)} cached, {len(stale)} to fetch",
          file=sys.stderr)
    if not stale:
        return cache

    with open(cache_path, "a") as sink:
        pending = stale
        # A dropped request looks exactly like a mod with no versions, so
        # sweep the misses again rather than recording the gap as fact.
        for attempt in range(1, 4):
            missed = []
            with ThreadPoolExecutor(workers) as pool:
                for n, (mod, rec) in enumerate(
                        pool.map(lambda m: (m, fetch_one(fetcher, m)), pending), 1):
                    if rec is None:
                        missed.append(mod)
                        continue
                    sink.write(json.dumps(rec) + "\n")
                    sink.flush()
                    cache[str(mod["id"])] = rec
                    if n % 50 == 0 or n == len(pending):
                        print(f"  {n}/{len(pending)}", file=sys.stderr)
            pending = missed
            if not pending:
                break
            print(f"  retrying {len(pending)} missed (pass {attempt + 1})",
                  file=sys.stderr)
            time.sleep(3 * attempt)

        if pending:
            print(f"  {len(pending)} unresolved; re-run to pick them up",
                  file=sys.stderr)
    return cache


def load_overrides(path):
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return {k: v for k, v in json.load(f).items() if not k.startswith("_")}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spt", default="", help="SPT version filter (default: all mods)")
    ap.add_argument("--workers", type=int, default=4)
    # The Forge allows 300 requests/minute. Each worker sleeps this long
    # before every request, so 4 workers at 1.0s sits at ~240/min -- under the
    # limit with room for the retries that a burst would otherwise trigger.
    ap.add_argument("--delay", type=float, default=1.0,
                    help="seconds each worker waits between requests")
    ap.add_argument("--limit", type=int, help="stop after N mods (testing)")
    ap.add_argument("--fresh", action="store_true", help="ignore the cache")
    args = ap.parse_args()

    os.makedirs(DATA, exist_ok=True)
    fetcher = Fetcher(delay=args.delay)
    started = time.time()

    params = {"include": "source_code_links,license,category,versions",
              "sort": "created_at"}
    if args.spt:
        params["filter[spt_version]"] = args.spt

    print(f"Enumerating mods ({args.spt or 'all versions'})...", file=sys.stderr)
    listing, listing_ok = fetcher.paginate(
        "/api/v0/mods", params,
        progress=lambda p, last, got, total: print(
            f"  page {p}/{last}  ({got}/{total or '?'})", file=sys.stderr))

    if not listing_ok:
        print("Enumeration was incomplete, so mods are missing from this run. "
              "Aborting rather than writing a truncated archive; re-run to "
              "continue (per-mod work is cached).", file=sys.stderr)
        return 1

    if not listing:
        print("No mods returned -- the Forge may be gone. Aborting without "
              "touching existing data.", file=sys.stderr)
        return 1

    seen, mods = set(), []
    for m in listing:
        if m["id"] not in seen:
            seen.add(m["id"])
            mods.append(m)
    if len(mods) != len(listing):
        print(f"  dropped {len(listing) - len(mods)} duplicate rows",
              file=sys.stderr)
    if args.limit:
        mods = mods[:args.limit]

    print(f"\nPer-mod detail and versions for {len(mods)} mods...", file=sys.stderr)
    cache_path = os.path.join(DATA, "raw_mods.jsonl")
    cache = gather(fetcher, mods, cache_path, args.workers, args.fresh)
    compact_cache(cache_path)

    overrides = load_overrides(os.path.join(HERE, "source_overrides.json"))
    if overrides:
        print(f"Applying {len(overrides)} source override(s)", file=sys.stderr)

    records = [build_record(m, cache.get(str(m["id"])), overrides) for m in mods]
    # Sorted by id, which never changes, so the file diffs small. Ordering by
    # downloads instead moves a mod's whole record every time two of them swap
    # rank -- turning a handful of changed counters into thousands of changed
    # lines, on a file CI commits every couple of hours. build.py sorts by
    # downloads at render time, so nothing on the site depends on this order.
    records.sort(key=lambda r: r["id"])

    categories = {}
    for r in records:
        if r["category"] and r["category"]["id"]:
            categories[r["category"]["id"]] = r["category"]

    out = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": BASE,
        "filter": args.spt or "all",
        "mod_count": len(records),
        "categories": sorted(categories.values(), key=lambda c: c["title"]),
        "mods": records,
    }
    path = os.path.join(DATA, "mods.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=1)

    with_src = sum(1 for r in records if r["source_links"])
    print(f"\nMods:            {len(records)}", file=sys.stderr)
    print(f"With source:     {with_src}", file=sys.stderr)
    print(f"Multi-source:    {sum(1 for r in records if len(r['source_links']) > 1)}",
          file=sys.stderr)
    print(f"Fika compatible: {sum(1 for r in records if r['fika'])}", file=sys.stderr)
    print(f"With deps:       {sum(1 for r in records if r['dependencies'])}",
          file=sys.stderr)
    print(f"Categories:      {len(categories)}", file=sys.stderr)

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
