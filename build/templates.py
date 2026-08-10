"""What the archive knows, and the little HTML still rendered in Python.

This used to render every page. It now renders two -- `all-mods.html` and
`all-addons.html`, the plain listings that have to work with scripting off --
plus the masthead and footer wrapped around every shell. The rest of the markup
moved to `assets/render.js`, which reproduces it in the browser.

What stayed here is the part that was never really about markup: the archive's
own judgements. Which of a mod's repositories is the live one, which git tag
shipped version 1.4.2, what "Fika compatible" resolves to when the mod flag and
the version flag disagree, how a constraint like "~4.0 <4.1.0" is spelled on a
badge. All of it needs `repos.json` to answer, all of it was already correct,
and `emit.py` calls it so the browser receives conclusions rather than
evidence. A second implementation in JavaScript would be a second set of
answers to the same questions.

One rule still holds throughout: anything derived from Forge data is escaped
with `e()`, or passed through `sanitize.clean_html()` when it is meant to be
markup. There is no third option, because every string here was written by
somebody else.
"""

import json
import re
import urllib.parse
from html import escape


ARCHIVE_TOTAL = 0
ARCHIVE_ADDON_TOTAL = 0


def set_archive_totals(mods, addons=0):
    """Recorded once per build so every page can show them."""
    global ARCHIVE_TOTAL, ARCHIVE_ADDON_TOTAL
    ARCHIVE_TOTAL = mods
    ARCHIVE_ADDON_TOTAL = addons


def e(value):
    return escape(str(value if value is not None else ""), quote=True)


def spt_line(constraint):
    """The SPT minor line a constraint targets, e.g. "~4.0 <4.1.0" -> "4.0".

    Constraints are ranges, not versions: "~4.0 <4.1.0", ">=3.8.0 <3.9". Only
    the first version in the string names the line the mod is built for, so it
    is matched directly. Splitting on "." instead lets the upper bound bleed
    into the label and produces nonsense like "4.0 <4".
    """
    match = re.search(r"(\d+)(?:\.(\d+))?", constraint or "")
    if not match:
        return ""
    major, minor = match.group(1), match.group(2)
    return f"{major}.{minor}" if minor is not None else major


def last_release(mod):
    """When the mod itself last changed, i.e. its newest version's date.

    Not `updated_at`: that is the Forge's row-modified timestamp, and bulk
    database migrations set it on thousands of mods at once. 83% of the
    archive shares just three such days, so displaying or sorting by it says
    more about the Forge's maintenance schedule than about the mod.
    """
    dates = [v["published_at"] for v in mod.get("versions") or []
             if v.get("published_at")]
    return max(dates) if dates else (mod.get("published_at") or "")


def spt_label(constraint):
    """A constraint as something readable on a badge.

    Exact-looking constraints keep their precision ("~4.0.0" -> "4.0.0"), while
    ranges collapse to the line they target ("~4.0 <4.1.0" -> "4.0"). Printing
    the raw range instead truncates to things like "4.0 <4", which reads as a
    typo rather than as an upper bound.
    """
    text = (constraint or "").strip()
    if not text:
        return ""
    if " " not in text and "<" not in text and ">" not in text:
        text = text.lstrip("^~= ")
    else:
        text = spt_line(text)
    # Real data contains "4.1.", "4.1.*" and a bare "*"; normalise so the
    # filter does not offer three spellings of the same version.
    text = re.sub(r"\.[x*]$", "", text.strip())
    return text.rstrip(".*").strip()


def fmt_date(stamp):
    return stamp[:10] if stamp else ""


_IMG_SRC_RE = re.compile(r'(<img[^>]+src=")([^"]+)(")')


def local_image(url, images, up=""):
    """Rewrite a Forge image URL to its mirrored copy, if we have one.

    Falls back to the original URL when the image was never mirrored, which
    keeps third-party screenshots working while Forge-hosted ones stop
    depending on a site that is going away.
    """
    name = images.get(url)
    return f"{up}assets/img/{name}" if name else url


def localize_images(html, images, up=""):
    """Point every <img> in a fragment at its mirrored copy where one exists."""
    if not images or "<img" not in html:
        return html
    return _IMG_SRC_RE.sub(
        lambda m: m.group(1) + local_image(m.group(2), images, up) + m.group(3),
        html)


def to_epoch(stamp):
    """Sortable numeric timestamp for the client-side comment sort.

    Emitted as a number because the browser reads it with Number(); an ISO
    string would silently sort as 0 and leave threads in arbitrary order.
    """
    if not stamp:
        return 0
    try:
        from datetime import datetime
        return int(datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return 0


# --- shared chrome -------------------------------------------------------

def page(title, body, *, depth=0, description="", scripts=()):
    """Full document. `depth` is how many directories deep the page sits."""
    up = "../" * depth

    # Every page carries the collection UI, so the flyout follows you around
    # the site. ids.js is the id universe the share-link encoder needs.
    all_scripts = ("ids.js", "collection.js") + tuple(scripts)
    script_tags = "\n".join(
        f'  <script src="{up}assets/{e(s)}" defer></script>' for s in all_scripts)

    return f"""<!doctype html>
<html lang="en" data-up="{up}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{e(title)}</title>
  <meta name="description" content="{e(description)}">
  <meta name="color-scheme" content="dark light">
  <link rel="stylesheet" href="{up}assets/site.css">
{script_tags}
</head>
<body>
<header class="masthead">
  <div class="wrap">
    <div class="masthead-row">
      <div>
        <h1><a href="{up}index.html">SPT Mod Archive</a></h1>
        <p class="tagline">A community archive of the SPT Forge mod listings.</p>
      </div>
      <div class="masthead-side">
        <span class="archived"><strong>{ARCHIVE_TOTAL:,}</strong> mods, <strong>{ARCHIVE_ADDON_TOTAL:,}</strong> addons archived</span>
        <span class="masthead-actions">
          <a class="textlink" href="{up}lists.html">Mod lists</a>
          <button type="button" id="collection-open" class="collection-open is-empty" aria-expanded="false" aria-controls="collection-drawer"><span>Collection</span><span id="collection-open-count" class="collection-count">0</span></button>
        </span>
      </div>
    </div>
  </div>
</header>
<main class="wrap">
{body}
</main>
<footer class="site wrap">
  <p>Archived from forge.sp-tarkov.com. Mod descriptions and comments remain the
  work of their authors. This archive is unofficial and not affiliated with the
  SPT team.</p>
</footer>
</body>
</html>
"""


def mark_button(mod_id, name, href, sources, label=False, deps=(), parent=None):
    """A collection toggle. Carries the whole entry so no lookup is needed.

    The button is inert until collection.js binds it, which is why it renders
    as a plain <button> rather than something that looks interactive on a page
    where scripting failed.
    """
    # Wrapped so the "+" can be swapped for the checkmark without the button
    # changing width -- the tick is drawn by CSS, the plus is simply hidden.
    # Both labels are always present: collection.js writes the resting one,
    # and CSS shows the other on hover, so what a click will do is stated in
    # words as well as by the × and the colour change.
    inner = ('<span class="mark-label">'
             '<span class="lbl-state">Add to collection</span>'
             '<span class="lbl-hover">Remove</span>'
             '</span>' if label
             else '<span class="mark-plus">+</span>')
    # Dependencies travel with the button so they can be added alongside the
    # mod without any lookup -- a mod page has no access to the catalogue.
    dep_attr = (f' data-deps="{e(json.dumps(list(deps), separators=(",", ":")))}"'
                if deps else "")
    # Addons pass the mod they extend, so the collection can file them under
    # it exactly as it files a mod's dependencies.
    parent_attr = f' data-parent="{e(parent)}"' if parent else ""
    return (f'<button type="button" class="mark{" mark-wide" if label else ""}"'
            f'{parent_attr} '
            f'data-mark data-id="{e(mod_id)}" data-name="{e(name)}" '
            f'data-href="{e(href)}" data-sources="{e(" ".join(sources))}"'
            f'{dep_attr} aria-pressed="false">{inner}</button>')


# --- names and filenames -------------------------------------------------

def author_slug(author):
    return ("".join(c if (c.isalnum() or c in "-_") else "-"
                    for c in (author.get("name") or "user"))
            .strip("-").lower() or "user")


def author_href(author):
    return f"{author['id']}-{author_slug(author)}.html"


def addon_href(addon):
    slug = "".join(c if (c.isalnum() or c in "-_") else "-"
                   for c in (addon.get("slug") or "addon")).strip("-").lower()
    return f"{addon['id']}-{slug or 'addon'}.html"


def list_href(entry):
    slug = "".join(c if (c.isalnum() or c in "-_") else "-"
                   for c in (entry.get("slug") or "list")).strip("-").lower()
    return f"{entry['id']}-{slug or 'list'}.html"

# --- the plain listings --------------------------------------------------

def render_all_addons(addons):
    """A plain list of every addon, so the archive works without JavaScript."""
    rows = "\n".join(
        f'<li><a href="{e(addon["href"])}">{e(addon["name"])}</a> '
        f'<span class="byline">{e(addon["authors"])}</span></li>'
        for addon in addons)
    body = f"""
<p class="crumbs"><a href="addons.html">← Back to the addons</a></p>
<div class="panel">
  <h2>All addons ({len(addons):,})</h2>
  <ul class="linklist">
{rows}
  </ul>
</div>
"""
    return page("All addons · SPT Mod Archive", body, depth=0,
                description="Every addon in the SPT Mod Archive, as a plain list.")


def render_all_mods(mods):
    """A plain list of every mod, so the archive works without JavaScript."""
    # `href` already carries the mod/ prefix, since the index links from the
    # site root too. Adding it again here is what broke these links once.
    rows = "\n".join(
        f'<li>{mark_button(mod["id"], mod["name"], mod["href"], mod["source_urls"], label=True)}'
        f'<a href="{e(mod["href"])}">{e(mod["name"])}</a> '
        f'<span class="byline">{e(mod["authors"])}</span></li>'
        for mod in mods)
    body = f"""
<p class="crumbs"><a href="index.html">← Back to the archive</a></p>
<div class="panel">
  <h2>All mods ({len(mods):,})</h2>
  <ul class="linklist">
{rows}
  </ul>
</div>
"""
    return page("All mods · SPT Mod Archive", body, depth=0,
                description="Every mod in the SPT Mod Archive, as a plain list.")


# --- repositories, releases, and what they resolve to --------------------

def repo_name(url, status):
    """"owner/repo" rather than a full URL: shorter and easier to scan."""
    if status and status.get("full_name"):
        return status["full_name"]
    parts = [p for p in url.split("//")[-1].split("/")[1:] if p]
    return "/".join(parts[:2]).removesuffix(".git") if len(parts) >= 2 else url


def repo_host_label(url):
    host = url.split("//")[-1].split("/")[0].lower().removeprefix("www.")
    return {"github.com": "GitHub", "gitlab.com": "GitLab",
            "codeberg.org": "Codeberg", "gitea.com": "Gitea"}.get(host, host)


def sources_by_recency(links, repos):
    """Source links newest-first, so the living repository leads.

    A mod that ships a client and a server half -- or that somebody picked up
    after the original author stopped -- lists several repositories, and the
    Forge lists them in the order they were added, which is usually the order
    they were abandoned in. Left that way the page leads with the dead one and
    so does the download link beside it: 54 of the 79 multi-repo mods in the
    archive named a stale repository first, several of them pointing at an
    original last touched two years before the fork that replaced it.

    Recency is the newer of the last commit and the latest release, because
    either is evidence of a maintainer. Repositories that did not resolve sort
    last: a dead link is still worth showing as a record of where a mod lived,
    but it should never be the first thing offered. Ties keep the Forge's own
    order, which is also what keeps a source_overrides.json correction ahead of
    the link it was written to replace.
    """
    def key(link):
        status = repos.get(link["url"]) or {}
        if status.get("status") != "ok":
            return (0, "")
        return (1, max((status.get("release") or {}).get("date") or "",
                       (status.get("commit") or {}).get("date") or ""))

    return sorted(links, key=key, reverse=True)


def dedupe_sources(links, repos):
    """Drop source links that render as a row identical to one already shown.

    The Forge lets an author list a repository several times over -- once at
    its root and once per branch or subfolder that matters to them. A source
    row shows only the repository and its label, so links that reduce to the
    same repository *and* carry the same label come out as the same row
    repeated: anOrangeDoggo's SAIN Presets listed its root plus two /tree/dev
    paths, all unlabelled, and printed three identical lines.

    Links whose labels differ are left alone even when the repository matches,
    because the label is what distinguishes them -- several mods keep a 3.11
    branch beside a 4.0 one, and both rows are worth having.

    Of a collapsed group the shallowest URL wins, which is the repository root
    wherever one was listed; the group stays where its first member sat, so a
    recency ordering applied beforehand survives.
    """
    def identity(link):
        url = link["url"]
        status = repos.get(url) or {}
        host = url.split("//")[-1].split("/")[0].lower().removeprefix("www.")
        repo = status.get("full_name") or repo_name(url, None)
        return (host, repo.casefold(), link.get("label", "").strip().casefold())

    groups = {}
    for link in links:
        groups.setdefault(identity(link), []).append(link)

    def depth(link):
        return len([p for p in link["url"].split("//")[-1].split("/") if p])

    return [min(group, key=depth) for group in groups.values()]


def releases_page(url):
    """A repository URL reduced to its host's releases page, or "".

    Source URLs often point into a repository rather than at it -- /tree/<ref>,
    a deep subpath, a trailing .git -- so this reduces to owner/repo first.
    """
    parts = [p for p in url.split("//")[-1].split("/")[1:] if p]
    if len(parts) < 2:
        return ""
    host = url.split("//")[-1].split("/")[0].lower().removeprefix("www.")
    base = "/".join(url.split("/")[:3] + [parts[0], parts[1].removesuffix(".git")])
    if host == "gitlab.com":
        return base + "/-/releases"
    if host in ("github.com", "codeberg.org", "gitea.com"):
        return base + "/releases"
    return ""


_VERSION_CORE_RE = re.compile(r"\d+(?:\.\d+)*")


def version_key(text):
    """The numeric core of a version string, for comparing across schemes.

    The Forge records "1.5.0" while the tag that shipped it might be "v1.5.0",
    "SPT-1.5.0" or "1.5.0-beta". Matching on the digits is what makes those
    the same release; anything stricter fails on most repositories, and
    anything looser starts matching unrelated versions to each other.
    """
    match = _VERSION_CORE_RE.search(text or "")
    return match.group(0) if match else ""


def release_page_url(record, tag):
    """A release's own page, built from the repository and the tag.

    Derived rather than stored: repo_status.py keeps only tags, because
    holding 20 URLs for each of 1,400 repositories would add megabytes to a
    file CI commits twelve times a day, and every host spells this the same
    way given the two pieces.
    """
    host = record.get("host", "")
    full_name = record.get("full_name", "")
    if not (host and full_name and tag):
        return ""
    quoted = urllib.parse.quote(tag, safe="")
    if host == "gitlab.com":
        return f"https://{host}/{full_name}/-/releases/{quoted}"
    return f"https://{host}/{full_name}/releases/tag/{quoted}"


def release_index(mod, repos=None):
    """Version number -> {url, notes} for the release that shipped it.

    Built across every repository the mod lists, newest-first, so a mod split
    over a client and a server repo resolves a version from whichever one
    tagged it. First match wins, which keeps the maintained fork ahead of the
    original it replaced.

    `notes` is the repository's own release text, and today only the latest
    release carries any -- repo_status.py stores one body per repository. That
    is the release a reader is most likely to be installing, and the Versions
    tab is where its text belongs: when the Forge listing is gone, that tab
    still answers "what changed in this version" from the repository instead.
    """
    index = {}
    for link in mod["source_links"]:
        record = (repos or {}).get(link["url"]) or {}
        if record.get("status") != "ok":
            continue
        latest = record.get("release") or {}
        for release in record.get("releases") or []:
            key = version_key(release.get("tag"))
            if not key or key in index:
                continue
            url = release_page_url(record, release["tag"])
            if not url:
                continue
            is_latest = release["tag"] == latest.get("tag")
            index[key] = {"url": url,
                          "host_label": repo_host_label(record["url"]),
                          "notes": latest.get("html", "") if is_latest else ""}
    return index


def latest_download(links, repos=None):
    """The newest release's actual file, when the host names one.

    A releases page is a landing spot; this is the download itself. Only the
    latest release carries assets in repos.json, which is the one a reader
    installing today wants -- older versions still resolve to their release
    page, where their files are.
    """
    for link in links:
        record = (repos or {}).get(link.get("url", "")) or {}
        assets = ((record.get("release") or {}).get("assets")) or []
        # A release often ships a source zip alongside the built mod; the
        # named asset is the one an author uploaded on purpose.
        for asset in assets:
            if asset.get("url"):
                return asset["url"], asset.get("name", "")
    return "", ""


def releases_url(links, repos=None):
    """Where the download button goes.

    `links` arrives newest-first from sources_by_recency(), so the first one we
    can name is almost always the answer. The exception is a repository that
    has never cut a release: its releases page is an empty shelf, so it is
    passed over while another link has one. That splits from the displayed
    order for exactly one mod in the archive today, and in that mod it is the
    difference between a download and a blank page.
    """
    repos = repos or {}
    fallback = ""
    for link in links:
        url = link.get("url", "")
        page = releases_page(url)
        if not page:
            continue
        fallback = fallback or page
        if ((repos.get(url) or {}).get("release") or {}).get("tag"):
            return page
    return fallback


FIKA_LABEL = {
    "compatible": ("Fika compatible ✓", "fika"),
    "incompatible": ("Fika not supported ✗", "bad"),
    "partial": ("Partial Fika support", "warn"),
    "unknown": ("Fika support unknown", ""),
}


def fika_state(mod):
    """One of FIKA_LABEL's keys for the mod as a whole.

    Two fields disagree about what "Fika" means. The mod carries a plain
    boolean the author ticked once, which cannot say "no" -- only "yes" or
    "nothing said" -- while each version carries a real three-state answer.
    Neither alone is enough: the boolean cannot express the 25 mods declared
    incompatible, and the latest version says nothing for the 21 mods whose
    author ticked the box but never marked a version.

    So the latest version wins wherever it is explicit, and the mod's flag
    fills the silence. One mod, LootNET, is flagged compatible while its
    latest version declares otherwise; the version is newer and more specific,
    and a wrong "yes" here costs more than a wrong "unknown".
    """
    if mod.get("fika_latest") in ("compatible", "incompatible", "partial"):
        return mod["fika_latest"]
    return "compatible" if mod["fika"] else "unknown"


def dependency_entries(mod, lookup):
    """Collection entries for a mod's dependencies, where we archived them."""
    entries, seen = [], set()
    for dep in mod["dependencies"]:
        entry = (lookup or {}).get(dep.get("id"))
        if entry and entry["id"] not in seen:
            seen.add(entry["id"])
            entries.append(entry)
    return entries

