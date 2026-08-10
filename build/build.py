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
import archive_links                                  # noqa: E402
import community                                      # noqa: E402
import templates                                      # noqa: E402
from sanitize import to_text                          # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
SITE = os.path.join(HERE, "site")
ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

# Absolute URLs are required in a sitemap, and a static build has no way to
# know where it will be served from -- so this is the one place the deployment
# URL is written down. Override with --base-url when hosting elsewhere.
BASE_URL = "https://tekunogosu.github.io/sptmodarchive"


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


def load_lists():
    """Archived Forge mod lists. Absent until scrape_lists.py runs."""
    path = os.path.join(DATA, "lists.json")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        try:
            return json.load(f).get("lists", [])
        except json.JSONDecodeError:
            return []


def load_addons():
    """Archived Forge addons. Absent until scrape_addons.py runs."""
    path = os.path.join(DATA, "addons.json")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        try:
            return json.load(f).get("addons", [])
        except json.JSONDecodeError:
            return []


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


def addon_index_entry(addon, parent, images):
    """One addon as the catalogue page reads it, mirroring index_entry()."""
    return {
        "id": addon["id"],
        "name": addon["name"],
        "href": "addon/" + templates.addon_href(addon),
        "authors": ", ".join(a["name"] for a in addon["authors"]) or "Unknown",
        "author_links": [[a["id"], a["name"], templates.author_href(a)]
                         for a in addon["authors"] if a.get("id")],
        "teaser": to_text(addon["teaser"]),
        "thumbnail": templates.local_image(addon["thumbnail"], images or {}),
        "downloads": addon["downloads"],
        "updated": (addon["versions"][0]["published_at"][:10]
                    if addon["versions"] else addon["updated_at"][:10]),
        "published": addon["published_at"][:10],
        "version": addon["latest_version"],
        "mod_constraint": addon["mod_constraint"],
        "versions": len(addon["versions"]),
        "detached": addon["detached"],
        "parent_name": parent["name"] if parent else "",
        "parent_href": parent["href"] if parent else "",
        "parent_id": addon["mod_id"] if parent else "",
        "source_urls": [l["url"] for l in addon["source_links"]],
        "search": " ".join(filter(None, [
            addon["name"], addon["teaser"],
            " ".join(a["name"] for a in addon["authors"]),
            parent["name"] if parent else ""])).lower(),
    }


def collect_authors(mods, addons, mod_lists, images):
    """Everyone who published something, with what they published.

    Keyed by Forge user id, which is the only stable identifier -- names are
    displayed but are neither unique nor fixed. A person reachable only as a
    list owner still gets a page, because a curated list is authorship too.
    """
    authors = {}

    def slot(person):
        if not person.get("id"):
            return None            # nothing to key or link on
        entry = authors.setdefault(person["id"], {
            "id": person["id"], "name": person.get("name") or "Unknown",
            "avatar": person.get("avatar") or "",
            # The Forge 404s on a bare /user/{id} and needs a slug after it --
            # but any slug will do, since it redirects to the real one. So
            # this reuses the archive's own slug rather than trying to
            # reproduce the Forge's, which differs for about 8% of names
            # (underscores become hyphens, dots vanish, and display names
            # carrying a moderator title are not slugged with it).
            "forge_url": (f"https://forge.sp-tarkov.com/user/{person['id']}"
                          f"/{templates.author_slug(person)}"),
            "mods": [], "addons": [], "lists": [],
        })
        # First non-empty avatar wins: the same person carries one per record
        # and some are blank.
        if not entry["avatar"] and person.get("avatar"):
            entry["avatar"] = person["avatar"]
        return entry

    for mod in mods:
        for person in mod["authors"]:
            entry = slot(person)
            if entry is not None:
                entry["mods"].append({
                    "name": mod["name"], "href": "mod/" + href_for(mod),
                    "mark_id": mod["id"],
                    "thumb": templates.local_image(mod["thumbnail"], images),
                    "teaser": to_text(mod["teaser"]),
                    "downloads": mod["downloads"],
                    "sources": [l["url"] for l in mod["source_links"]]})

    for addon in addons:
        for person in addon["authors"]:
            entry = slot(person)
            if entry is not None:
                entry["addons"].append({
                    "name": addon["name"],
                    "href": "addon/" + templates.addon_href(addon),
                    "mark_id": f"a{addon['id']}",
                    "parent": addon["mod_id"],
                    "thumb": templates.local_image(addon["thumbnail"], images),
                    "teaser": to_text(addon["teaser"]),
                    "downloads": addon["downloads"],
                    "sources": [l["url"] for l in addon["source_links"]]})

    for entry in mod_lists:
        person = entry.get("owner") or {}
        slot_entry = slot(person)
        if slot_entry is not None:
            slot_entry["lists"].append({
                "title": entry["title"], "href": templates.list_href(entry),
                "mod_count": entry["mod_count"],
                "spt_version": entry.get("spt_version", "")})

    for entry in authors.values():
        entry["mods"].sort(key=lambda m: -m["downloads"])
        entry["addons"].sort(key=lambda a: -a["downloads"])
    return authors


def href_for(mod):
    slug = "".join(c if (c.isalnum() or c in "-_") else "-"
                   for c in (mod.get("slug") or "mod")).strip("-").lower()
    if mod["origin"] == "community":
        return f"c-{slug}.html"
    return f"{mod['id']}-{slug or 'mod'}.html"


# --- the client-side index ----------------------------------------------

def search_blob(mod, repos=None):
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
    for link in mod["source_links"]:
        parts.append(link["url"])
        record = (repos or {}).get(link["url"]) or {}
        if record.get("full_name"):
            parts.append(record["full_name"])
    return " ".join(p for p in parts if p).lower()


def best_repo(mod, repos):
    """The mod's newest live repository, and its star count.

    The tile shows one repository, and the star count is also a link, so the
    number and the destination have to describe the same place. Picking the
    most-starred one made the number flattering and the link wrong: on 51 tiles
    it pointed at an original that had been collecting stars for years while
    the fork beside it was the one still shipping. SAIN was the worst of them,
    offering 146 stars on a repository that had been superseded.

    source_links arrives newest-first from sources_by_recency(), so the first
    one that resolves is the repository still being worked on -- and the same
    one the download button goes to.
    """
    for link in mod["source_links"]:
        record = repos.get(link["url"]) or {}
        if record.get("status") == "ok":
            return link["url"], record.get("stars", 0)
    return "", 0


def index_entry(mod, comment_count, images=None, repos=None):
    category = mod.get("category") or {}
    repo_url, stars = best_repo(mod, repos or {})
    versions = sorted({templates.spt_label(c) for c in mod["all_spt_constraints"]}
                      - {""})
    return {
        "id": mod["id"],
        "name": mod["name"],
        "href": "mod/" + href_for(mod),
        "authors": ", ".join(a["name"] for a in mod["authors"]) or "Unknown",
        # id and name per author, so a tile can link to the author's page
        # rather than pre-filling a search that other filters can empty out.
        "author_links": [[a["id"], a["name"], templates.author_href(a)]
                         for a in mod["authors"] if a.get("id")],
        "teaser": to_text(mod["teaser"]),
        # The index lives at the site root, so no "../" prefix here.
        "thumbnail": templates.local_image(mod["thumbnail"], images or {}),
        "category": category.get("slug", ""),
        "category_title": category.get("title", ""),
        "fika": bool(mod["fika"]),
        "downloads": mod["downloads"],
        "updated": templates.last_release(mod)[:10],
        "published": mod["published_at"][:10],
        "spt": versions,
        "spt_latest": templates.spt_label(mod["spt_constraint"]),
        "version": mod["latest_version"],
        "dep_count": len(mod["dependencies"]),
        "comments": comment_count,
        "sources": len(mod["source_links"]),
        "source_urls": [link["url"] for link in mod["source_links"]],
        "origin": mod["origin"],
        "stars": stars,
        "repo_url": repo_url,
        "repo_host": (repo_url.split("/")[2] if repo_url.startswith("http") else ""),
        "deps": [d["id"] for d in mod["dependencies"] if d.get("id")],
        "search": search_blob(mod, repos or {}),
    }


def facets(mods):
    """Filter options: categories, and SPT versions grouped by major line."""
    categories, versions = {}, {}
    for mod in mods:
        category = mod.get("category") or {}
        if category.get("slug"):
            entry = categories.setdefault(
                category["slug"],
                {"slug": category["slug"], "title": category["title"], "count": 0})
            entry["count"] += 1
        # Count distinct *mods*, not constraint strings. A mod can declare
        # several constraints that normalise to the same version, and several
        # versions within one major -- summing occurrences double-counts it.
        for label in {templates.spt_label(c) for c in mod["all_spt_constraints"]}:
            if label:
                versions.setdefault(label, set()).add(mod["id"])

    def key(version):
        return [int(p) if p.isdigit() else 0 for p in version.split(".")]

    majors = {}
    for version, mod_ids in versions.items():
        majors.setdefault(version.split(".")[0], []).append((version, mod_ids))

    spt_facets = []
    for major in sorted(majors, key=lambda m: -key(m)[0]):
        rows = sorted(majors[major], key=lambda vc: key(vc[0]), reverse=True)
        distinct = set().union(*(ids for _, ids in rows))
        spt_facets.append((major, len(distinct),
                           [(v, len(ids)) for v, ids in rows]))

    return sorted(categories.values(), key=lambda c: -c["count"]), spt_facets


# --- crawler files -------------------------------------------------------

def write_sitemap_and_robots(base_url, pages):
    """A sitemap of every page, and a robots.txt pointing crawlers at it.

    `pages` is (path relative to site root, last-modified date or ""). Only
    real pages are listed -- assets and images are reachable from them and add
    nothing to a crawler's picture of the archive.
    """
    base = base_url.rstrip("/")
    today = time.strftime("%Y-%m-%d")

    entries = []
    for path, lastmod in pages:
        loc = f"{base}/{path}".replace("&", "&amp;")
        stamp = (lastmod or today)[:10]
        # The index changes with every scrape; a mod page only when that mod
        # does, which is what makes crawling the archive cheap to repeat.
        priority = "1.0" if path == "index.html" else "0.6"
        entries.append(
            f"  <url><loc>{loc}</loc><lastmod>{stamp}</lastmod>"
            f"<priority>{priority}</priority></url>")

    write(os.path.join(SITE, "sitemap.xml"),
          '<?xml version="1.0" encoding="UTF-8"?>\n'
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
          + "\n".join(entries) + "\n</urlset>\n")

    write(os.path.join(SITE, "robots.txt"),
          "# SPT Mod Archive — everything here is public and crawlable.\n"
          "User-agent: *\n"
          "Allow: /\n\n"
          f"Sitemap: {base}/sitemap.xml\n")
    return len(entries)


# --- writing -------------------------------------------------------------

def write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def build(limit=None, base_url=BASE_URL):
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

    addons = load_addons()
    templates.set_archive_totals(len(mods), len(addons))

    threads = load_comments()
    repos = load_repos()
    images = load_images()
    mod_lists = load_lists()
    if images:
        print(f"  {len(images)} mirrored images", file=sys.stderr)
    if repos:
        print(f"  {len(repos)} repositories checked", file=sys.stderr)
    print(f"  {len(threads)} mods have archived comments", file=sys.stderr)

    # Source links are rendered on the mod page, reduced to a download link
    # beside it, copied into the index tiles and carried into the collection
    # drawer. Ordering them once here rather than at each use is what keeps
    # those four agreeing with each other -- newest repository first.
    for mod in mods:
        mod["source_links"] = templates.dedupe_sources(
            templates.sources_by_recency(mod["source_links"], repos), repos)

    # Addons keep the Forge's own order -- they rarely list more than one
    # repository -- but they inherit the same habit of listing one repository
    # several times, so they get the same collapse.
    for addon in addons:
        addon["source_links"] = templates.dedupe_sources(addon["source_links"],
                                                         repos)

    # Built before the link map, which needs to know who has a page here.
    authors = collect_authors(mods, addons, mod_lists, images)

    # Dependency links resolve to archive pages where the target was archived,
    # and fall back to the (soon dead) Forge URL where it was not.
    # Links written by mod authors and commenters point at the Forge and at
    # the Hub before it. Wherever they name something we archived, they are
    # rewritten to point here instead -- see build/archive_links.py.
    archive_links.set_link_map(mods, mod_lists, href_for, templates.list_href,
                               addons, templates.addon_href,
                               authors.values(), templates.author_href)

    # Addons hang off their parent mod, so they are grouped by it once and
    # handed to whichever page needs them. Ordered by downloads, like
    # everything else the archive lists.
    addons_by_mod = {}
    for addon in sorted(addons, key=lambda a: -a["downloads"]):
        addons_by_mod.setdefault(str(addon["mod_id"]), []).append(addon)

    known_ids = {mod["id"]: href_for(mod) for mod in mods}
    lookup = {mod["id"]: {"id": mod["id"], "name": mod["name"],
                          "href": "mod/" + href_for(mod),
                          # Root-relative; pages one level deep prefix "../".
                          "thumb": templates.local_image(mod["thumbnail"], images),
                          "teaser": mod["teaser"],
                          "sources": [l["url"] for l in mod["source_links"]]}
              for mod in mods}

    sitemap_pages = []

    os.makedirs(os.path.join(SITE, "mod"), exist_ok=True)
    for mod in mods:
        mod_addons = [
            {"name": a["name"], "href": "addon/" + templates.addon_href(a),
             # Prefixed so the collection cannot confuse addon 102 with mod
             # 102 -- the two are separate id sequences that overlap.
             "mark_id": f"a{a['id']}",
             "thumb": templates.local_image(a["thumbnail"], images),
             "teaser": to_text(a["teaser"]), "detached": a["detached"],
             "mod_constraint": a["mod_constraint"],
             "sources": [l["url"] for l in a["source_links"]]}
            for a in addons_by_mod.get(str(mod["id"]), [])]
        page = templates.render_mod(mod, threads.get(mod["id"]), known_ids,
                                    repos, images,
                                    href="mod/" + href_for(mod),
                                    lookup=lookup, addons=mod_addons)
        write(os.path.join(SITE, "mod", href_for(mod)), page)
        sitemap_pages.append(("mod/" + href_for(mod),
                              templates.last_release(mod)))

    os.makedirs(os.path.join(SITE, "user"), exist_ok=True)
    for author in authors.values():
        href = templates.author_href(author)
        write(os.path.join(SITE, "user", href),
              templates.render_author(author, images))
        sitemap_pages.append(("user/" + href, ""))
    print(f"  {len(authors)} author pages", file=sys.stderr)

    entries = [index_entry(mod, len(threads.get(mod["id"], {}).get("comments", [])),
                           images, repos)
               for mod in mods]
    categories, spt_lines = facets(mods)

    index_json = json.dumps(entries, separators=(",", ":"), ensure_ascii=False)
    stats = {"mod_count": len(mods), "generated_at": archive.get("generated_at", "")}

    # Just enough to name an addon and link to it: the index resolves shared
    # collections, and a share link may carry addons.
    addon_lookup = json.dumps(
        [{"id": a["id"], "name": a["name"],
          "href": "addon/" + templates.addon_href(a), "parent": a["mod_id"]}
         for a in addons], separators=(",", ":"), ensure_ascii=False)

    write(os.path.join(SITE, "index.html"),
          templates.render_index(index_json, categories, spt_lines, stats,
                                 addon_lookup))
    write(os.path.join(SITE, "all-mods.html"), templates.render_all_mods(entries))

    # Addons: a second catalogue with its own page per addon. Each one names
    # the mod it extends, so it is rendered with that mod resolved against the
    # archive -- and left saying so plainly when the parent was never listed.
    if addons:
        os.makedirs(os.path.join(SITE, "addon"), exist_ok=True)
        addon_entries = []
        for addon in sorted(addons, key=lambda a: -a["downloads"]):
            parent = lookup.get(addon["mod_id"])
            href = templates.addon_href(addon)
            write(os.path.join(SITE, "addon", href),
                  templates.render_addon(addon, parent, images, repos))
            sitemap_pages.append(("addon/" + href, addon["updated_at"][:10]))
            addon_entries.append(addon_index_entry(addon, parent, images))

        addons_json = json.dumps(addon_entries, separators=(",", ":"),
                                 ensure_ascii=False)
        write(os.path.join(SITE, "addons.html"),
              templates.render_addons_index(addons_json,
                                            {"addon_count": len(addons)}))
        write(os.path.join(SITE, "all-addons.html"),
              templates.render_all_addons(addon_entries))
        print(f"  {len(addons)} addons across "
              f"{len({str(a['mod_id']) for a in addons})} mods", file=sys.stderr)

    # Mod lists: curated modpacks, each rendered with its mods resolved
    # against the archive so every entry is a working link.
    if mod_lists:
        for entry in mod_lists:
            write(os.path.join(SITE, "list", templates.list_href(entry)),
                  templates.render_list(entry, lookup))
            sitemap_pages.append(("list/" + templates.list_href(entry),
                                  entry.get("updated_at", "")))
        write(os.path.join(SITE, "lists.html"), templates.render_lists(mod_lists))
        print(f"  {len(mod_lists)} mod lists", file=sys.stderr)

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

    # Share links encode ids; the bitset and complement schemes need to know
    # every id that exists. Emitted as its own cached file so mod pages carry
    # it without embedding the whole catalogue.
    numeric_ids = sorted(m["id"] for m in mods if isinstance(m["id"], int))
    write(os.path.join(assets_out, "ids.js"),
          "window.ARCHIVE_IDS=" + json.dumps(numeric_ids, separators=(",", ":"))
          + ";\n")

    sitemap_pages = ([("index.html", ""), ("all-mods.html", "")]
                     + ([("lists.html", "")] if mod_lists else [])
                     + ([("addons.html", ""), ("all-addons.html", "")]
                        if addons else [])
                     + sitemap_pages)
    listed = write_sitemap_and_robots(base_url, sitemap_pages)
    print(f"  sitemap: {listed} pages", file=sys.stderr)

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
    ap.add_argument("--base-url", default=BASE_URL,
                    help="absolute URL the site is served from")
    args = ap.parse_args()
    return build(args.limit, args.base_url)


if __name__ == "__main__":
    sys.exit(main())
