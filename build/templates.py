"""HTML rendering for the archive.

Every page is assembled here and written to disk by build.py. The split is
deliberate: build.py decides *what* is on a page, this module decides how it
looks, and neither needs to know how the data was fetched.

Two rules hold throughout:

  - Anything derived from Forge data is escaped with `e()`, or passed through
    sanitize.clean_html() when it is meant to be markup. There is no third
    option, because every string here was written by somebody else.
  - Pages render completely without JavaScript. The scripts add filtering,
    sorting, and search; they are never what makes content visible.
"""

import json
import re
from html import escape

from sanitize import clean_html, to_text


def e(value):
    return escape(str(value if value is not None else ""), quote=True)


def plural(n, word, suffix="s"):
    return f"{n:,} {word}{'' if n == 1 else suffix}"


def mod_href(mod):
    """Stable, readable, and safe as a filename."""
    slug = "".join(c if (c.isalnum() or c in "-_") else "-"
                   for c in (mod.get("slug") or "mod")).strip("-").lower()
    return f"{mod['id']}-{slug or 'mod'}.html"


def spt_line(constraint):
    """The SPT minor line a constraint belongs to, e.g. "~4.0.1" -> "4.0"."""
    digits = constraint.lstrip("^~>=< ")
    parts = [p for p in digits.split(".") if p and p[0].isdigit()]
    return ".".join(parts[:2]) if len(parts) >= 2 else (parts[0] if parts else "")


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
    <h1><a href="{up}index.html">SPT Mod Archive</a></h1>
    <p class="tagline">A community archive of the SPT Forge mod listings.</p>
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


def mark_button(mod_id, name, href, sources, label=False, deps=()):
    """A collection toggle. Carries the whole entry so no lookup is needed.

    The button is inert until collection.js binds it, which is why it renders
    as a plain <button> rather than something that looks interactive on a page
    where scripting failed.
    """
    inner = ('<span class="mark-label">Add to collection</span>' if label
             else "+")
    # Dependencies travel with the button so they can be added alongside the
    # mod without any lookup -- a mod page has no access to the catalogue.
    dep_attr = (f' data-deps="{e(json.dumps(list(deps), separators=(",", ":")))}"'
                if deps else "")
    return (f'<button type="button" class="mark{" mark-wide" if label else ""}" '
            f'data-mark data-id="{e(mod_id)}" data-name="{e(name)}" '
            f'data-href="{e(href)}" data-sources="{e(" ".join(sources))}"'
            f'{dep_attr} aria-pressed="false">{inner}</button>')


def badge(text, kind=""):
    return f'<span class="badge {kind}">{e(text)}</span>'


# --- index ---------------------------------------------------------------

def option_list(options, placeholder):
    out = [f'<option value="">{e(placeholder)}</option>']
    out += [f'<option value="{e(value)}">{e(label)}</option>'
            for value, label in options]
    return "\n      ".join(out)


def render_index(index_json, categories, spt_lines, stats):
    """The catalogue page. The mod data ships inline so it works offline."""
    category_options = option_list(
        [(c["slug"], f'{c["title"]} ({c["count"]})') for c in categories],
        "All categories")
    spt_options = option_list(
        [(line, f"SPT {line} ({count})") for line, count in spt_lines],
        "Any SPT version")

    body = f"""
<form class="controls" onsubmit="return false">
  <input type="search" id="q" placeholder="Search mods, authors, dependencies…"
         autocomplete="off" spellcheck="false" aria-label="Search mods">
  <select id="category" aria-label="Category">
      {category_options}
  </select>
  <select id="spt" aria-label="SPT version">
      {spt_options}
  </select>
  <select id="fika" aria-label="Fika compatibility">
    <option value="">Fika: any</option>
    <option value="yes">Fika compatible</option>
    <option value="no">Not Fika compatible</option>
  </select>
  <select id="show" aria-label="Show">
    <option value="">All mods</option>
    <option value="deps">Has dependencies</option>
    <option value="comments">Has comments</option>
    <option value="nosource">No source link</option>
    <option value="collection">In my collection</option>
  </select>
  <select id="sort" aria-label="Sort by">
    <option value="downloads">Most downloaded</option>
    <option value="updated">Recently updated</option>
    <option value="published">Newest</option>
    <option value="name">Name A–Z</option>
    <option value="comments">Most comments</option>
    <option value="stars">Most stars</option>
    <option value="fika">Fika first</option>
    <option value="collection">Collection first</option>
  </select>
</form>

<div class="resultbar">
  <span id="count">{stats['mod_count']:,} mods</span>
  <button type="button" class="linkbtn" id="copy-sources">Copy source URLs</button>
</div>

<div class="listscroll" id="listscroll">
  <div class="modlist" id="modlist"></div>
  <div id="sentinel"></div>
</div>

<noscript>
  <p class="empty">Searching and filtering need JavaScript, but every mod has its
  own page — see <a href="all-mods.html">the full mod list</a>.</p>
</noscript>

<script id="mod-index" type="application/json">{index_json}</script>
"""
    return page("SPT Mod Archive", body, depth=0, scripts=("index.js",),
                description=(f"An archive of {stats['mod_count']:,} Single Player "
                             "Tarkov mods from the SPT Forge, including Fika "
                             "compatibility, dependencies, and comments."))


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


# --- mod page ------------------------------------------------------------

def repo_note(status):
    """A one-line health summary for a repository, when we have checked it.

    This is the part of the archive that stays useful *after* the Forge is
    gone: whether the code a listing points at is still there and still moving.
    """
    if not status:
        return ""

    NOTES = {
        "not_found": "repo not found",
        "host_gone": "this host no longer exists",
        "not_a_repo": "file host, not a code repository",
    }
    note = NOTES.get(status.get("status"))
    if note:
        return f'<span class="label warn">{e(note)}</span>'

    bits = []
    commit = status.get("commit") or {}
    if commit.get("date"):
        bits.append(f'last commit {fmt_date(commit["date"])}')
    release = status.get("release") or {}
    if release.get("tag"):
        bits.append(f'latest release {release["tag"]}')
    if status.get("stars"):
        bits.append(f'{status["stars"]:,}★')
    if status.get("archived"):
        bits.append("archived by its author")

    return f'<span class="label">{e(" · ".join(bits))}</span>' if bits else ""


def render_source_links(links, repos):
    if not links:
        return '<p class="empty">No source repository was listed for this mod.</p>'
    items = []
    for link in links:
        label = (f'<span class="label">{e(link["label"])}</span>'
                 if link.get("label") else "")
        items.append(
            f'<li>{label}<a href="{e(link["url"])}" target="_blank" '
            f'rel="noopener noreferrer">{e(link["url"])}</a>'
            f'{repo_note(repos.get(link["url"]))}</li>')
    return f'<ul class="linklist">{"".join(items)}</ul>'


def render_dependencies(deps, known_ids):
    """Dependencies, linked to their own archive page when we have one."""
    if not deps:
        return ""
    items = []
    for dep in deps:
        name = e(dep["name"] or f"Mod {dep['id']}")
        if dep["id"] in known_ids:
            target = known_ids[dep["id"]]
            items.append(f'<li><a href="{e(target)}">{name}</a></li>')
        elif dep.get("url"):
            items.append(f'<li><a href="{e(dep["url"])}" target="_blank" '
                         f'rel="noopener noreferrer">{name}</a> '
                         f'<span class="label">not archived</span></li>')
        else:
            items.append(f"<li>{name}</li>")
    return f"""
<section class="panel">
  <h2>Requires</h2>
  <ul class="linklist">{"".join(items)}</ul>
</section>"""


FIKA_LABEL = {
    "compatible": ("Fika compatible", "fika"),
    "incompatible": ("Not Fika compatible", "warn"),
    "partial": ("Partial Fika support", "warn"),
    "unknown": ("Fika support unknown", ""),
}


def render_versions(versions, limit=40):
    if not versions:
        return ""
    blocks = []
    for version in versions[:limit]:
        notes = clean_html(version["description"])
        fika_text, fika_kind = FIKA_LABEL.get(version["fika"],
                                              FIKA_LABEL["unknown"])
        blocks.append(f"""
  <div class="version">
    <div class="vhead">
      <span class="num">{e(version['version'] or '—')}</span>
      {badge('SPT ' + version['spt_constraint'], 'spt') if version['spt_constraint'] else ''}
      {badge(fika_text, fika_kind)}
      <span class="when">{e(fmt_date(version['published_at']))} ·
        {version['downloads']:,} downloads</span>
    </div>
    {f'<div class="notes prose">{notes}</div>' if notes else ''}
  </div>""")

    more = (f'<p class="empty">{len(versions) - limit} older versions not shown.</p>'
            if len(versions) > limit else "")
    return f"""
    <div class="versions">{"".join(blocks)}</div>
    {more}"""


def render_comment(comment, replies, images=None):
    body = localize_images(clean_html(comment["body_html"]), images or {}, "../")
    reply_html = "".join(render_comment(reply, [], images) for reply in replies)
    likes = (f'<span class="likes">{plural(comment["likes"], "like")}</span>'
             if comment["likes"] else "")

    return f"""
    <article class="comment">
      <div class="chead">
        <span class="who">{e(comment['author'] or 'Unknown')}</span>
        <time class="when" datetime="{e(comment['created_at'])}">
          {e(fmt_date(comment['created_at']))}</time>
        {likes}
      </div>
      <div class="cbody prose">{body}</div>
    </article>
    {f'<div class="replies">{reply_html}</div>' if reply_html else ''}"""


def render_comments(comment_data, images=None):
    """The collapsible comment section: closed by default, sorted, searchable."""
    images = images or {}
    comments = (comment_data or {}).get("comments") or []
    if not comments:
        return ""

    by_parent = {}
    for comment in comments:
        by_parent.setdefault(comment["parent_id"], []).append(comment)

    top_level = by_parent.get(None, [])
    threads = []
    for comment in sorted(top_level, key=lambda c: c["created_at"], reverse=True):
        replies = sorted(by_parent.get(comment["id"], []),
                         key=lambda c: c["created_at"])
        # Sorting and searching operate on whole threads, so the metadata a
        # thread is ordered by lives on its wrapper rather than being
        # recomputed in the browser.
        stamp = to_epoch(comment["created_at"])
        threads.append(f"""
  <div class="thread-item" data-time="{stamp}" data-likes="{comment['likes']}"
       data-replies="{len(replies)}">
{render_comment(comment, replies, images)}
  </div>""")

    return f"""
    <p class="panel-note">{len(comments):,} comments across
      {plural(len(top_level), 'thread')}, archived from the Forge.</p>
    <div class="comment-controls">
      <input type="search" id="comment-search" placeholder="Search comments…"
             autocomplete="off" aria-label="Search comments">
      <select id="comment-sort" aria-label="Sort comments">
        <option value="newest">Newest first</option>
        <option value="oldest">Oldest first</option>
        <option value="likes">Most liked</option>
        <option value="replies">Most replies</option>
      </select>
    </div>
    <p class="empty" id="comment-status"></p>
    <div class="thread" id="comment-thread">
{"".join(threads)}
    </div>"""


def dependency_entries(mod, lookup):
    """Collection entries for a mod's dependencies, where we archived them."""
    entries, seen = [], set()
    for dep in mod.get("all_dependencies") or []:
        entry = (lookup or {}).get(dep.get("id"))
        if entry and entry["id"] not in seen:
            seen.add(entry["id"])
            entries.append(entry)
    return entries


def render_tabs(mod, description, comment_data, images):
    """Description / Versions / Comments as tabs, or as stacked sections.

    Which of those you get depends on whether tabs.js runs. The markup is the
    same either way: a nav of in-page anchors followed by the panels. Without
    the script the anchors are jump links and every panel is visible, which is
    exactly the page this replaced. A tab whose content does not exist -- a mod
    with no description, or one whose comments have not been scraped yet -- is
    simply not emitted.
    """
    comments = (comment_data or {}).get("comments") or []
    versions = mod["versions"]

    sections = []
    if description:
        sections.append(("description", "Description", None,
                         f'<div class="prose">{description}</div>'))
    if versions:
        sections.append(("versions", "Versions", len(versions),
                         render_versions(versions)))
    if comments:
        sections.append(("comments", "Comments", len(comments),
                         render_comments(comment_data, images)))

    if not sections:
        return ('<section class="panel"><p class="empty">No description, '
                'versions, or comments were archived for this mod.</p></section>')

    def tab_link(slug, label, count):
        badge_html = f'<span class="tabcount">{count:,}</span>' if count else ""
        return f'<a class="tab" href="#{slug}">{e(label)}{badge_html}</a>'

    nav = "".join(tab_link(slug, label, count)
                  for slug, label, count, _ in sections)

    panels = "".join(
        f'<section class="panel tabpanel" id="{slug}">'
        f'<h2 class="panel-heading">{e(label)}</h2>{content}</section>'
        for slug, label, _, content in sections)

    return f"""
<div class="tabs" id="mod-tabs">
  <nav class="tablist" aria-label="Mod details">{nav}</nav>
{panels}
</div>"""


def render_mod(mod, comment_data, known_ids, repos, images=None,
               href="", lookup=None):
    """One mod's page: everything the archive holds about it."""
    authors = ", ".join(a["name"] for a in mod["authors"]) or "Unknown"
    images = images or {}
    # Mod pages sit one directory deep, so mirrored images are ../assets/img/.
    description = localize_images(clean_html(mod["description_html"]),
                                  images, "../")
    category = mod.get("category") or {}

    flags = []
    if mod["fika"]:
        flags.append(badge("Fika compatible ✓", "fika"))
    else:
        flags.append(badge("Fika: not marked compatible", ""))
    if category.get("title"):
        flags.append(badge(category["title"], "cat"))
    if mod["spt_constraint"]:
        flags.append(badge(f"SPT {mod['spt_constraint']}", "spt"))
    if mod["origin"] == "community":
        flags.append(badge("Community submission", "community"))
    for key, label in (("contains_ads", "Contains ads"),
                       ("contains_ai_content", "Contains AI content"),
                       ("cheat_notice", "Cheat notice"),
                       ("profile_binding_notice", "Binds to profile")):
        if mod["flags"].get(key):
            flags.append(badge(label, "warn"))

    thumb = (f'<img src="{e(local_image(mod["thumbnail"], images, "../"))}" '
             f'alt="" loading="lazy">' if mod["thumbnail"] else "")

    facts = [
        ("Downloads", f"{mod['downloads']:,}"),
        ("Latest version", mod["latest_version"] or "—"),
        ("SPT", mod["spt_constraint"] or "—"),
        ("Updated", fmt_date(mod["updated_at"]) or "—"),
        ("Published", fmt_date(mod["published_at"]) or "—"),
        ("License", (mod["license"].get("name") or "—")),
    ]
    fact_html = "".join(
        f'<div class="fact"><div class="k">{e(k)}</div>'
        f'<div class="v">{e(v)}</div></div>' for k, v in facts)

    forge_link = (f'<p><a href="{e(mod["forge_url"])}" target="_blank" '
                  f'rel="noopener noreferrer">Original Forge page</a> '
                  f'<span class="label">offline once the Forge shuts down</span></p>'
                  if mod["forge_url"] else "")

    body = f"""
<p class="crumbs"><a href="../index.html">← Back to the archive</a></p>

<div class="modhead">
  {thumb}
  <div class="modhead-main">
    <div class="modhead-title">
      <h1>{e(mod['name'])}</h1>
      {mark_button(mod['id'], mod['name'], href,
                   [l['url'] for l in mod['source_links']], label=True,
                   deps=dependency_entries(mod, lookup))}
    </div>
    <div class="byline">by {e(authors)}</div>
    <div class="badges">{"".join(flags)}</div>
    {f'<p class="teaser">{e(mod["teaser"])}</p>' if mod["teaser"] else ''}
  </div>
</div>

<section class="panel"><div class="facts">{fact_html}</div></section>

<section class="panel">
  <h2>Source</h2>
  {render_source_links(mod['source_links'], repos)}
  {forge_link}
</section>

{render_dependencies(mod.get('all_dependencies') or mod['dependencies'], known_ids)}

{render_tabs(mod, description, comment_data, images)}
"""
    return page(f"{mod['name']} · SPT Mod Archive", body, depth=1,
                scripts=("tabs.js", "comments.js"),
                description=to_text(mod["teaser"] or mod["description_html"], 160))
