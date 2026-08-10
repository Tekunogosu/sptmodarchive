"""Emit the archive as JSON for the browser to render.

This is the half of the build that used to be `templates.render_mod` and its
neighbours writing 3,000 HTML files. It writes data instead, and `assets/*.js`
turns that data into the same pages.

The split between here and the browser is deliberate, and it is not "structure
in Python, layout in JS" by accident:

  - Anything *decided* is decided here. Which repository a mod's download comes
    from, which release shipped version 1.4.2, whether a mod counts as Fika
    compatible, what order source links go in -- all of that is archive
    knowledge, it needs `repos.json` to answer, and it is already written and
    tested in `templates.py`. The browser receives conclusions, not evidence.

  - Anything *sanitized* is sanitized here. Mod descriptions, version notes and
    comment bodies are third-party HTML from the Forge. `clean_html()` runs
    over them once at build time and the result ships as a ready string. There
    is no client-side sanitizer, because a second implementation of one is a
    second chance to get it wrong on 1,800 mods of someone else's markup.

  - Only *layout* happens in the browser: heads, facts grids, badges, cards,
    tabs. Those are the parts that were costing 82 MB to say 1,830 times.

Paths need care, and the rule has one exception. Structured paths -- hrefs,
thumbnails -- are emitted relative to the *site root*, because the catalogue at
the root and a mod page one directory down both read them, and because the
collection writes them to localStorage where they outlive the page that saved
them; `url()` in assets/render.js prefixes them at render time. Prose is the
exception: it is injected as HTML, never stored, and only ever shown on a
detail page, so its "../" is baked in here. See UP below.
"""

import json
import os
import re

import templates
from sanitize import clean_html, to_text
from archive_links import localize_links


# Livewire wraps every comment body in these, twice per body. They are inert,
# they are 46 bytes each, and there are 180,000 of them.
_LIVEWIRE_RE = re.compile(r"<!--\[if (?:BLOCK|ENDBLOCK)\]><!\[endif\]-->")
_WS_RE = re.compile(r"\s+")


def write_json(path, payload):
    """One JSON file, minified. Nothing here is meant to be read by a human."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"), ensure_ascii=False)
    return os.path.getsize(path)


# Every file this module writes under data/mod, data/addon, data/list,
# data/user and data/comment is read by exactly one kind of page, and all four
# of those sit one directory deep. So the "../" that prose needs is knowable
# here and is baked in.
#
# Structured paths are *not* treated this way -- they stay relative to the site
# root and get prefixed at render time by url() in assets/render.js -- because
# the same href is also read by the catalogue at the root, and is written into
# localStorage by the collection, where it outlives the page that saved it.
# Prose is neither: it is injected as HTML and never stored.
UP = "../"


def prose(html, images):
    """Third-party HTML, made safe and pointed at the archive's own copies.

    Three passes, and all three matter: clean_html() drops anything not on the
    allowlist, localize_images() repoints <img> at the mirrored copy, and
    localize_links() turns Forge and Hub URLs into links to the pages here --
    which is what stops a mod description saying "install BigBrain first" from
    becoming a dead end the day the Forge goes.
    """
    return localize_links(templates.localize_images(clean_html(html or ""),
                                                    images or {}, UP), UP)


def card(entry):
    """The archive's standard "here is a thing you might install" card.

    Mods, addons, dependencies and list members all render as this, because
    they are all answers to the same question. Kept as one shape here so the
    browser has one renderer for it rather than four.
    """
    return {k: v for k, v in {
        "name": entry.get("name") or "",
        "href": entry.get("href") or "",
        "thumb": entry.get("thumb") or "",
        "teaser": entry.get("teaser") or "",
        "mark": entry.get("mark"),
        "note": entry.get("note"),
    }.items() if v}


def mark(mark_id, name, href, sources, deps=(), parent=None):
    """What a collection button needs to add something without a lookup."""
    out = {"id": mark_id, "name": name, "href": href,
           "sources": list(sources or ())}
    if deps:
        out["deps"] = list(deps)
    if parent:
        out["parent"] = parent
    return out


# --- mods ----------------------------------------------------------------

def mod_detail(mod, repos, images, lookup, addons, comment_count, href):
    """Everything a mod page shows, with every question already answered."""
    category = mod.get("category") or {}
    releases = templates.release_index(mod, repos)

    badges = [list(templates.FIKA_LABEL[templates.fika_state(mod)])]
    if category.get("title"):
        badges.append([category["title"], "cat"])
    if mod["origin"] == "community":
        badges.append(["Community submission", "community"])
    for key, label in (("contains_ads", "Contains ads"),
                       ("contains_ai_content", "Contains AI content"),
                       ("cheat_notice", "Cheat notice"),
                       ("profile_binding_notice", "Binds to profile")):
        if mod["flags"].get(key):
            badges.append([label, "warn"])

    # The download, the star count and the leading source row all describe the
    # same repository -- the first one that resolves. Picked once, here, so
    # they cannot drift apart in three separate renderers.
    asset_url, asset_name = templates.latest_download(mod["source_links"], repos)
    download_url = asset_url or templates.releases_url(mod["source_links"], repos)
    primary = next((r for r in ((repos or {}).get(l["url"]) or {}
                                for l in mod["source_links"])
                    if r.get("status") == "ok"), {})

    detail = {
        "id": mod["id"],
        "name": mod["name"],
        "href": href,
        "teaser": mod["teaser"] or "",
        "description": prose(mod["description_html"], images),
        "thumb": templates.local_image(mod["thumbnail"], images) if mod["thumbnail"] else "",
        "initial": (mod["name"] or "?")[:1].upper(),
        "authors": [{"id": a["id"], "name": a["name"],
                     "href": "user/" + templates.author_href(a)}
                    if a.get("id") else {"name": a.get("name") or "Unknown"}
                    for a in mod["authors"]],
        "badges": badges,
        "spt": (f"SPT {templates.spt_label(mod['spt_constraint'])}"
                if mod["spt_constraint"] else ""),
        "facts": [
            ["Downloads", f"{mod['downloads']:,}"],
            ["Latest version", mod["latest_version"] or "—"],
            ["Latest release", templates.fmt_date(templates.last_release(mod)) or "—"],
            ["Published", templates.fmt_date(mod["published_at"]) or "—"],
            ["License", mod["license"].get("name") or "—"],
            ["GUID", mod.get("guid") or "Not available"],
        ],
        "forge_url": mod["forge_url"] or "",
        "sources": source_rows(mod["source_links"], repos),
        "mark": mark(mod["id"], mod["name"], href,
                     [l["url"] for l in mod["source_links"]],
                     deps=[card_for_lookup(entry) for entry
                           in templates.dependency_entries(mod, lookup)]),
        "comments": comment_count,
    }

    if download_url:
        detail["download"] = {
            "url": download_url,
            "title": f"Download {asset_name}" if asset_name else "Downloads / releases",
        }
    if primary.get("stars"):
        detail["stars"] = {"url": primary["url"], "count": primary["stars"],
                           "host": templates.repo_host_label(primary["url"])}

    deps = dependency_cards(mod, lookup)
    if deps:
        detail["deps"] = deps
        detail["dep_count"] = len(mod["dependencies"])
    if addons:
        detail["addons"] = addon_cards(addons, mod["id"])
    versions = version_blocks(mod["versions"], releases, images)
    if versions:
        detail["versions"] = versions
        detail["version_count"] = len(mod["versions"])
        if len(mod["versions"]) > len(versions):
            detail["versions_hidden"] = len(mod["versions"]) - len(versions)
    return detail


def card_for_lookup(entry):
    """A catalogue lookup entry as the collection stores it."""
    return {"id": entry["id"], "name": entry["name"], "href": entry["href"],
            "thumb": entry.get("thumb", ""), "teaser": entry.get("teaser", ""),
            "sources": entry.get("sources") or []}


def source_rows(links, repos):
    """One row per repository: what it is, then how it is doing."""
    rows = []
    for link in links:
        status = repos.get(link["url"]) or {}
        row = {"url": link["url"],
               "name": templates.repo_name(link["url"], status),
               "host": templates.repo_host_label(link["url"])}
        if link.get("label"):
            row["label"] = link["label"]
        note, kind = repo_note(status)
        if note:
            row["note"] = note
            if kind:
                row["note_kind"] = kind
        rows.append(row)
    return rows


def repo_note(status):
    """`templates.repo_note` as text plus a class, rather than as markup."""
    if not status:
        return "", ""
    problems = {"not_found": "repo not found",
                "host_gone": "this host no longer exists",
                "not_a_repo": "file host, not a code repository"}
    problem = problems.get(status.get("status"))
    if problem:
        return problem, "warn"

    bits = []
    commit = status.get("commit") or {}
    if commit.get("date"):
        bits.append(f"last commit {templates.fmt_date(commit['date'])}")
    release = status.get("release") or {}
    if release.get("tag"):
        bits.append(f"latest release {release['tag']}")
    if status.get("archived"):
        bits.append("archived by its author")
    return " · ".join(bits), ""


def dependency_cards(mod, lookup):
    """A mod's dependencies as cards, including the ones we never archived."""
    cards = []
    for dep in mod["dependencies"]:
        entry = (lookup or {}).get(dep.get("id"))
        if entry:
            cards.append(card({
                "name": entry["name"], "href": entry["href"],
                "thumb": entry.get("thumb", ""), "teaser": entry.get("teaser", ""),
                "mark": mark(entry["id"], entry["name"], entry["href"],
                             entry.get("sources") or ()),
            }))
        else:
            cards.append({
                "name": dep.get("name") or f"Mod {dep.get('id')}",
                "url": dep.get("url") or "",
                "missing": True,
                "teaser": ("Not in the archive — this mod was never listed, or "
                           "was removed before it could be captured."),
            })
    return cards


def addon_cards(addons, parent_id):
    """A mod's addons, laid out exactly like its dependencies."""
    cards = []
    for addon in addons:
        note = (["Detached ✗", "bad"] if addon.get("detached")
                else ([f"for {addon['mod_constraint']}", "spt"]
                      if addon.get("mod_constraint") else None))
        cards.append(card({
            "name": addon["name"], "href": addon["href"],
            "thumb": addon.get("thumb", ""), "teaser": addon.get("teaser", ""),
            "note": note,
            "mark": mark(addon["mark_id"], addon["name"], addon["href"],
                         addon.get("sources") or (), parent=parent_id),
        }))
    return cards


def version_blocks(versions, releases, images, limit=40):
    """A mod's releases, each already matched to the tag that shipped it.

    The Forge's own notes and the repository's are two accounts of the same
    release, so both travel and the browser gives them a tab each. Matching
    them is `release_index`'s job and has already happened by the time we get
    here -- `releases` is keyed by the numeric core of a version string.
    """
    blocks = []
    for version in versions[:limit]:
        release = releases.get(templates.version_key(version["version"])) or {}
        fika_text, fika_kind = templates.FIKA_LABEL.get(
            version["fika"], templates.FIKA_LABEL["unknown"])
        block = {
            "id": str(version.get("id") or version["version"] or ""),
            "version": version["version"] or "—",
            "date": templates.fmt_date(version["published_at"]),
            "downloads": version["downloads"],
            "fika": [fika_text, fika_kind],
        }
        if version["spt_constraint"]:
            block["spt"] = "SPT " + templates.spt_label(version["spt_constraint"])
        forge_notes = prose(version["description"], images)
        if forge_notes:
            block["notes"] = forge_notes
        repo_notes = clean_html(release.get("notes", ""))
        if repo_notes:
            block["repo_notes"] = repo_notes
            block["repo_label"] = release.get("host_label") or "Repository"
        if release.get("url"):
            block["download"] = release["url"]
        blocks.append(block)
    return blocks


# --- addons --------------------------------------------------------------

def addon_detail(addon, parent, repos, images, href):
    """One addon: what it is, what it extends, and every release.

    Simpler than a mod on purpose -- an addon has no repository health, no
    dependencies and no comments, because the Forge never gave it any.
    """
    badges = []
    if addon["mod_constraint"]:
        badges.append([f"for mod {addon['mod_constraint']}", "spt"])
    badges.append(["Addon", "cat"])
    if addon["detached"]:
        badges.append(["Detached from parent ✗", "bad"])
    for key, label in (("contains_ads", "Contains ads"),
                       ("contains_ai_content", "Contains AI content")):
        if addon["flags"].get(key):
            badges.append([label, "warn"])

    detail = {
        "id": addon["id"],
        "name": addon["name"],
        "href": href,
        "teaser": addon["teaser"] or "",
        "description": prose(addon["description_html"], images),
        "thumb": templates.local_image(addon["thumbnail"], images) if addon["thumbnail"] else "",
        "initial": (addon["name"] or "?")[:1].upper(),
        "authors": [{"id": a["id"], "name": a["name"],
                     "href": "user/" + templates.author_href(a)}
                    if a.get("id") else {"name": a.get("name") or "Unknown"}
                    for a in addon["authors"]],
        "badges": badges,
        "spt": (f"for mod {addon['mod_constraint']}"
                if addon["mod_constraint"] else ""),
        "facts": [
            ["Downloads", f"{addon['downloads']:,}"],
            ["Latest version", addon["latest_version"] or "—"],
            ["Latest release", (templates.fmt_date(addon["versions"][0]["published_at"])
                                if addon["versions"] else "—")],
            ["Published", templates.fmt_date(addon["published_at"]) or "—"],
            ["License", addon["license"].get("name") or "—"],
        ],
        "forge_url": addon["forge_url"] or "",
        "sources": source_rows(addon["source_links"], repos),
        "mark": mark(f"a{addon['id']}", addon["name"], href,
                     [l["url"] for l in addon["source_links"]],
                     parent=addon["mod_id"] if parent else None),
        "parent": ({"name": parent["name"], "href": parent["href"]}
                   if parent else None),
    }

    blocks = []
    for version in addon["versions"][:40]:
        block = {"version": version["version"] or "—",
                 "date": templates.fmt_date(version["published_at"]),
                 "downloads": version["downloads"]}
        if version["mod_constraint"]:
            block["spt"] = f"for mod {version['mod_constraint']}"
        notes = prose(version["description"], images)
        if notes:
            block["notes"] = notes
        blocks.append(block)
    if blocks:
        detail["versions"] = blocks
        detail["version_count"] = len(addon["versions"])
        if len(addon["versions"]) > len(blocks):
            detail["versions_hidden"] = len(addon["versions"]) - len(blocks)
    return detail


# --- authors and lists ---------------------------------------------------

def author_detail(author, images):
    """Everything the archive holds by one person."""
    def person_card(item):
        return card({
            "name": item["name"], "href": item["href"],
            "thumb": item.get("thumb", ""), "teaser": item.get("teaser", ""),
            "mark": mark(item["mark_id"], item["name"], item["href"],
                         item.get("sources") or (), parent=item.get("parent")),
        })

    downloads = sum(m.get("downloads") or 0 for m in author["mods"])
    return {
        "id": author["id"],
        "name": author["name"],
        "avatar": (templates.local_image(author["avatar"], images)
                   if author.get("avatar") else ""),
        "forge_url": author["forge_url"],
        "downloads": downloads,
        "mods": [person_card(m) for m in author["mods"]],
        "addons": [person_card(a) for a in author["addons"]],
        "lists": [{"title": entry["title"], "href": entry["href"],
                   "mod_count": entry["mod_count"],
                   "spt": entry.get("spt_version", "")}
                  for entry in author["lists"]],
    }


def list_detail(entry, lookup):
    """One archived list: its mods, resolved against the archive."""
    cards, missing = [], 0
    for mod_id in entry["mod_ids"]:
        mod = (lookup or {}).get(mod_id)
        if not mod:
            missing += 1
            continue
        cards.append(card({
            "name": mod["name"], "href": mod["href"],
            "thumb": mod.get("thumb", ""), "teaser": mod.get("teaser", ""),
            "mark": mark(mod["id"], mod["name"], mod["href"],
                         mod.get("sources") or ()),
        }))
    owner = entry.get("owner") or {}
    return {
        "id": entry["id"],
        "title": entry["title"],
        "spt": entry.get("spt_version", ""),
        "owner": ({"id": owner["id"], "name": owner.get("name") or "unknown",
                   "href": "user/" + templates.author_href(owner)}
                  if owner.get("id")
                  else {"name": owner.get("name") or "unknown"}),
        "forge_url": entry.get("forge_url", ""),
        "missing": missing,
        "mods": cards,
    }


# --- comments ------------------------------------------------------------

def comment_thread(data, images=None):
    """One mod's comments, threaded here rather than in the browser.

    Three things come out on the way, and none of them are content:

      - `author_url` is `/user/{author_id}/{slug of author}`, which is 5.3 MB
        across the archive to say something both remaining fields already say.
      - Livewire's `<!--[if BLOCK]>` wrappers, which are 8.9 MB of nothing.
      - `parent_id`, which has done its job once the replies are nested.
    """
    by_parent = {}
    for comment in data.get("comments") or []:
        by_parent.setdefault(comment["parent_id"], []).append(comment)

    def clean(comment, replies):
        body = _WS_RE.sub(" ", _LIVEWIRE_RE.sub("", comment.get("body_html") or "")).strip()
        # prose(), not clean_html() alone: years of comments answer questions
        # with a link to another mod, and those are the links most worth
        # bringing home -- they are also the ones most often written against
        # the Hub, which died before the Forge did.
        out = {"who": comment["author"] or "Unknown",
               "at": comment["created_at"],
               "body": prose(body, images)}
        if comment.get("author_id"):
            out["uid"] = comment["author_id"]
        if comment.get("likes"):
            out["likes"] = comment["likes"]
        if replies:
            out["replies"] = [clean(r, []) for r in replies]
        return out

    top = sorted(by_parent.get(None, []),
                 key=lambda c: c["created_at"], reverse=True)
    threads = []
    for comment in top:
        replies = sorted(by_parent.get(comment["id"], []),
                         key=lambda c: c["created_at"])
        thread = clean(comment, replies)
        # Sorting happens in the browser, so what it sorts by travels with the
        # thread rather than being recomputed from 180,000 date strings.
        thread["t"] = templates.to_epoch(comment["created_at"])
        thread["n"] = len(replies)
        threads.append(thread)

    return {"count": len(data.get("comments") or []),
            "threads": len(top),
            "items": threads}
