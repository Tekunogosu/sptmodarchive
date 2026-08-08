#!/usr/bin/env python3
"""Render the archive into site/.

    python3 build/build.py              # full build
    python3 build/build.py --limit 30   # quick build while iterating

Inputs, all optional except the first:

    data/mods.json        scraped mod records
    data/comments/*.json  one archived comment thread set per mod
    community/*.json      mods contributed by pull request after the shutdown

Output is a plain static site: an index carrying the whole catalogue inline,
one page per mod, and a no-JavaScript fallback list. Nothing fetches anything
at runtime, so it works from file://, from GitHub Pages, or from a USB stick
long after every service involved has gone away.
"""

import argparse
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import community                                      # noqa: E402
import templates                                      # noqa: E402
from sanitize import to_text                          # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
SITE = os.path.join(HERE, "site")
ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


# --- loading -------------------------------------------------------------

def load_mods():
    path = os.path.join(DATA, "mods.json")
    if not os.path.exists(path):
        sys.exit("data/mods.json not found — run scrape/scrape_mods.py first")
    with open(path) as f:
        return json.load(f)


def load_repos():
    """Repository health, keyed by source URL. Absent until repo_status runs."""
    path = os.path.join(DATA, "repos.json")
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f).get("repos", {})


def load_images():
    """URL -> local filename, for images mirrored off the Forge.

    Absent until fetch_images.py runs, in which case pages simply keep
    pointing at the original URLs -- correct today, broken after shutdown.
    """
    path = os.path.join(DATA, "images.json")
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f).get("images", {})


def load_comments():
    """Archived threads, keyed by mod id. Missing files simply mean not scraped."""
    directory = os.path.join(DATA, "comments")
    if not os.path.isdir(directory):
        return {}
    threads = {}
    for name in os.listdir(directory):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(directory, name)) as f:
                data = json.load(f)
            if data.get("comments"):
                threads[data["mod_id"]] = data
        except (json.JSONDecodeError, KeyError):
            print(f"  skipping unreadable {name}", file=sys.stderr)
    return threads


def href_for(mod):
    slug = "".join(c if (c.isalnum() or c in "-_") else "-"
                   for c in (mod.get("slug") or "mod")).strip("-").lower()
    if mod["origin"] == "community":
        return f"c-{slug}.html"
    return f"{mod['id']}-{slug or 'mod'}.html"


# --- the client-side index ----------------------------------------------

def search_blob(mod):
    """One lowercase haystack per mod, so filtering is a substring test.

    Everything a person might type goes in: names, authors, the teaser, the
    category, the mod's GUID, and the names of its dependencies -- searching
    "CommonLib" should find the mods that need it, not just CommonLib itself.
    """
    parts = [mod["name"], mod["teaser"], mod.get("guid") or ""]
    parts += [a["name"] for a in mod["authors"]]
    parts += [d["name"] for d in mod.get("all_dependencies") or []]
    if mod.get("category"):
        parts.append(mod["category"]["title"])
    parts += mod["all_spt_constraints"]
    parts += [link["url"] for link in mod["source_links"]]
    return " ".join(p for p in parts if p).lower()


def index_entry(mod, comment_count, images=None):
    category = mod.get("category") or {}
    lines = sorted({templates.spt_line(c) for c in mod["all_spt_constraints"]}
                   - {""})
    return {
        "name": mod["name"],
        "href": "mod/" + href_for(mod),
        "authors": ", ".join(a["name"] for a in mod["authors"]) or "Unknown",
        "teaser": to_text(mod["teaser"], 180),
        # The index lives at the site root, so no "../" prefix here.
        "thumbnail": templates.local_image(mod["thumbnail"], images or {}),
        "category": category.get("slug", ""),
        "category_title": category.get("title", ""),
        "fika": bool(mod["fika"]),
        "downloads": mod["downloads"],
        "updated": mod["updated_at"][:10],
        "published": mod["published_at"][:10],
        "spt_lines": lines,
        "spt_latest": mod["spt_constraint"],
        "dep_count": len(mod.get("all_dependencies") or []),
        "comments": comment_count,
        "sources": len(mod["source_links"]),
        "source_urls": [link["url"] for link in mod["source_links"]],
        "origin": mod["origin"],
        "search": search_blob(mod),
    }


def facets(mods):
    """Category and SPT-line filter options, with counts, ordered usefully."""
    categories, lines = {}, {}
    for mod in mods:
        category = mod.get("category") or {}
        if category.get("slug"):
            entry = categories.setdefault(
                category["slug"],
                {"slug": category["slug"], "title": category["title"], "count": 0})
            entry["count"] += 1
        for constraint in mod["all_spt_constraints"]:
            line = templates.spt_line(constraint)
            if line:
                lines[line] = lines.get(line, 0) + 1

    def version_key(line):
        return [int(p) if p.isdigit() else 0 for p in line.split(".")]

    return (sorted(categories.values(), key=lambda c: -c["count"]),
            sorted(lines.items(), key=lambda kv: version_key(kv[0]), reverse=True))


# --- writing -------------------------------------------------------------

def write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def build(limit=None):
    started = time.time()
    archive = load_mods()
    mods = archive["mods"]

    contributed, errors = community.load_all(
        os.path.join(HERE, "community"),
        on_error=lambda path, msg: print(
            f"  invalid submission {os.path.basename(path)}: {msg}",
            file=sys.stderr))
    if contributed:
        print(f"  {len(contributed)} community submission(s)", file=sys.stderr)

    mods = mods + contributed
    # Newest-looking first is a poor default for an archive; downloads is what
    # people actually rank mods by, and the page can re-sort from there.
    mods.sort(key=lambda m: -m["downloads"])
    if limit:
        mods = mods[:limit]

    threads = load_comments()
    repos = load_repos()
    images = load_images()
    if images:
        print(f"  {len(images)} mirrored images", file=sys.stderr)
    if repos:
        print(f"  {len(repos)} repositories checked", file=sys.stderr)
    print(f"  {len(threads)} mods have archived comments", file=sys.stderr)

    # Dependency links resolve to archive pages where the target was archived,
    # and fall back to the (soon dead) Forge URL where it was not.
    known_ids = {mod["id"]: href_for(mod) for mod in mods}

    os.makedirs(os.path.join(SITE, "mod"), exist_ok=True)
    for mod in mods:
        page = templates.render_mod(mod, threads.get(mod["id"]), known_ids,
                                    repos, images)
        write(os.path.join(SITE, "mod", href_for(mod)), page)

    entries = [index_entry(mod, len(threads.get(mod["id"], {}).get("comments", [])),
                           images)
               for mod in mods]
    categories, spt_lines = facets(mods)

    index_json = json.dumps(entries, separators=(",", ":"), ensure_ascii=False)
    stats = {"mod_count": len(mods), "generated_at": archive.get("generated_at", "")}

    write(os.path.join(SITE, "index.html"),
          templates.render_index(index_json, categories, spt_lines, stats))
    write(os.path.join(SITE, "all-mods.html"), templates.render_all_mods(entries))

    assets_out = os.path.join(SITE, "assets")
    os.makedirs(assets_out, exist_ok=True)
    for name in os.listdir(ASSETS):
        shutil.copy2(os.path.join(ASSETS, name), os.path.join(assets_out, name))

    # Mirrored images live in data/ (the archive) and are copied into the
    # generated site, which is what actually gets published.
    if images:
        img_out = os.path.join(assets_out, "img")
        os.makedirs(img_out, exist_ok=True)
        source_dir = os.path.join(DATA, "images")
        copied = 0
        for name in set(images.values()):
            src = os.path.join(source_dir, name)
            dst = os.path.join(img_out, name)
            if os.path.exists(src) and not os.path.exists(dst):
                shutil.copy2(src, dst)
                copied += 1
        print(f"  copied {copied} image(s) into site/assets/img", file=sys.stderr)

    total_comments = sum(len(t["comments"]) for t in threads.values())
    size = os.path.getsize(os.path.join(SITE, "index.html")) / 1e6

    print(f"\nMods:         {len(mods):,} ({len(contributed)} community)",
          file=sys.stderr)
    print(f"Fika:         {sum(1 for m in mods if m['fika']):,}", file=sys.stderr)
    print(f"Categories:   {len(categories)}", file=sys.stderr)
    print(f"Comments:     {total_comments:,}", file=sys.stderr)
    print(f"index.html:   {size:.1f} MB", file=sys.stderr)
    print(f"\nBuilt site/ in {time.time() - started:.1f}s", file=sys.stderr)
    return 1 if errors else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, help="only build the top N mods")
    args = ap.parse_args()
    return build(args.limit)


if __name__ == "__main__":
    sys.exit(main())
