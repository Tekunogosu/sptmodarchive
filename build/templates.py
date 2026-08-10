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
import urllib.parse
from html import escape

from archive_links import localize_links
from sanitize import clean_html, to_text


ARCHIVE_TOTAL = 0
ARCHIVE_ADDON_TOTAL = 0


def set_archive_totals(mods, addons=0):
    """Recorded once per build so every page can show them."""
    global ARCHIVE_TOTAL, ARCHIVE_ADDON_TOTAL
    ARCHIVE_TOTAL = mods
    ARCHIVE_ADDON_TOTAL = addons


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


def badge(text, kind=""):
    return f'<span class="badge {kind}">{e(text)}</span>'


# --- index ---------------------------------------------------------------

def option_list(options, placeholder):
    out = [f'<option value="">{e(placeholder)}</option>']
    out += [f'<option value="{e(value)}">{e(label)}</option>'
            for value, label in options]
    return "\n      ".join(out)


def render_index(index_json, categories, spt_facets, stats, addon_lookup="[]"):
    """The catalogue page. The mod data ships inline so it works offline."""
    category_options = option_list(
        [(c["slug"], f'{c["title"]} ({c["count"]})') for c in categories],
        "All categories")
    spt_groups = "".join(
        f"""<details class="sptgroup"{' open' if major == '4' else ''}>
      <summary><label class="anymajor"><input type="checkbox" name="sptmajor"
        value="{e(major)}"> Any {e(major)}.x</label>
        <span class="tabcount">{total:,}</span></summary>
      <div class="sptversions">{"".join(
          f'<label><input type="checkbox" name="sptv" value="{e(v)}">'
          f'<span>{e(v)}</span><span class="n">{n:,}</span></label>'
          for v, n in versions)}</div>
    </details>"""
        for major, total, versions in spt_facets)

    body = f"""
<form class="controls" onsubmit="return false">
  <input type="search" id="q" placeholder="Search mods, authors, dependencies…"
         autocomplete="off" spellcheck="false" aria-label="Search mods">
  <select id="category" aria-label="Category">
      {category_options}
  </select>
  <div class="sptfilter" id="sptfilter">
    <button type="button" id="spt-summary" class="sptsummary"
            aria-expanded="false" aria-controls="spt-panel">Any SPT version</button>
    <div class="sptpanel" id="spt-panel" hidden>
      <div class="sptactions">
        <button type="button" class="linkbtn" data-spt="all">All</button>
        <button type="button" class="linkbtn" data-spt="none">None</button>
        <button type="button" class="linkbtn" data-spt="4">Only 4.x</button>
      </div>
      {spt_groups}
    </div>
  </div>
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
  <span class="countgroup">
    <span class="counts">
      <span id="count">Showing {stats['mod_count']:,} mods</span>
      <span id="fika-count" class="subcount"></span>
    </span>
    <a class="switchbtn" href="addons.html">Addons</a>
  </span>
  <span class="resultactions">
    <button type="button" class="linkbtn" id="reset-filters">Reset filters</button>
    <button type="button" class="linkbtn" id="copy-sources">Copy source URLs</button>
  </span>
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
<!-- Names and links for addons, so a shared collection containing them can be
     rebuilt here. Share links always land on the index, and this is the only
     page that would otherwise have no idea what addon 42 is. -->
<script id="addon-lookup" type="application/json">{addon_lookup}</script>
"""
    return page("SPT Mod Archive", body, depth=0, scripts=("index.js",),
                description=(f"An archive of {stats['mod_count']:,} Single Player "
                             "Tarkov mods from the SPT Forge, including Fika "
                             "compatibility, dependencies, and comments."))


# --- addons --------------------------------------------------------------

# --- authors -------------------------------------------------------------

def author_slug(author):
    return ("".join(c if (c.isalnum() or c in "-_") else "-"
                    for c in (author.get("name") or "user"))
            .strip("-").lower() or "user")


def author_href(author):
    return f"{author['id']}-{author_slug(author)}.html"


def author_link(author, up="../"):
    """An author's name, linked to their page here rather than to a search.

    Clicking a name used to pre-fill the index's search box, which quietly
    collided with whatever filters the reader already had set -- an author
    with only 3.x mods returned nothing at all under the default 4.x filter,
    and looked like a broken link. A page of their own cannot be filtered out
    from under them.
    """
    if not author.get("id"):
        return e(author.get("name") or "Unknown")
    return (f'<a href="{up}user/{e(author_href(author))}">'
            f'{e(author["name"])}</a>')


def author_links(authors, up="../"):
    return ", ".join(author_link(a, up) for a in authors) or "Unknown"


def render_author(author, images=None, lookup=None):
    """Everything the archive holds by one person.

    Mods, addons and curated lists as tabs, in the same card the rest of the
    site uses for "here is a thing you might install". The tab strip is the
    point of the structure: the Forge profile also carries a wall and an
    activity feed, and those become two more entries in this list without the
    page changing shape.
    """
    images = images or {}
    avatar = (f'<img src="{e(local_image(author["avatar"], images, "../"))}" '
              f'alt="" loading="lazy">' if author.get("avatar") else "")

    sections = []
    if author["mods"]:
        sections.append(("mods", "Mods", len(author["mods"]),
                         render_cards(author["mods"])))
    if author["addons"]:
        sections.append(("addons", "Addons", len(author["addons"]),
                         render_cards(author["addons"])))
    if author["lists"]:
        rows = "".join(
            f'<li class="depcard"><span class="depthumb"></span>'
            f'<div class="depmain"><a class="depname" '
            f'href="../list/{e(entry["href"])}">{e(entry["title"])}</a>'
            f'<p class="teaser">{entry["mod_count"]} mods'
            f'{" · SPT " + e(entry["spt_version"]) if entry["spt_version"] else ""}'
            f'</p></div></li>' for entry in author["lists"])
        sections.append(("lists", "Mod lists", len(author["lists"]),
                         f'<ul class="deplist">{rows}</ul>'))

    counts = []
    if author["mods"]:
        counts.append(plural(len(author["mods"]), "mod"))
    if author["addons"]:
        counts.append(plural(len(author["addons"]), "addon"))
    if author["lists"]:
        counts.append(plural(len(author["lists"]), "mod list"))
    downloads = sum(m.get("downloads") or 0 for m in author["mods"])

    facts = [("Downloads", f"{downloads:,}")] if downloads else []

    body = f"""
<p class="crumbs"><a href="../index.html">← Back to the archive</a></p>

<div class="modhead">
  {avatar}
  <div class="modhead-main">
    <div class="modhead-title">
      <h1>{e(author['name'])}</h1>
    </div>
    <div class="bylinerow">
      <div class="byline">{e(" · ".join(counts)) or "Nothing archived"}</div>
      <div class="badges">{badge("Author", "cat")}</div>
    </div>
    {f'<p class="teaser">{e(f"{downloads:,}")} downloads across their mods</p>'
     if downloads else ''}
  </div>
</div>

{render_section_tabs(sections,
                     "Nothing by this author is archived yet.")}

<section class="panel">
  <h2>Profile</h2>
  <p class="forgelink"><a href="{e(author['forge_url'])}" target="_blank"
  rel="noopener noreferrer">Original Forge profile</a>
  <span class="label">offline after shutdown</span></p>
</section>
"""
    return page(f"{author['name']} · SPT Mod Archive", body, depth=1,
                scripts=("tabs.js",),
                description=(f"{author['name']} on the SPT Mod Archive: "
                             f"{', '.join(counts) or 'no archived work'}."))


def render_cards(items):
    """Mods or addons as the archive's standard card, each addable."""
    rows = []
    for item in items:
        thumb = (f'<img class="depthumb" src="../{e(item["thumb"])}" alt=""'
                 f' loading="lazy">' if item.get("thumb")
                 else '<span class="depthumb"></span>')
        teaser = (f'<p class="teaser">{e(item["teaser"])}</p>'
                  if item.get("teaser") else "")
        rows.append(f"""
    <li class="depcard">
      {thumb}
      <div class="depmain">
        <a class="depname" href="../{e(item['href'])}">{e(item['name'])}</a>
        {teaser}
      </div>
      {mark_button(item['mark_id'], item['name'], item['href'],
                   item.get('sources') or (), parent=item.get('parent'))}
    </li>""")
    return f'<ul class="deplist">{"".join(rows)}</ul>'


def facts_html(facts):
    """`(label, value)` pairs as the key/value grid both page types use.

    Each cell carries a class from its label, so a single fact can be styled
    without the grid needing to know what it holds -- the GUID is the reason
    that exists.
    """
    return "".join(
        f'<div class="fact fact-{e(label.lower().replace(" ", "-"))}">'
        f'<div class="k">{e(label)}</div>'
        f'<div class="v">{e(value)}</div></div>' for label, value in facts)


def addon_href(addon):
    slug = "".join(c if (c.isalnum() or c in "-_") else "-"
                   for c in (addon.get("slug") or "addon")).strip("-").lower()
    return f"{addon['id']}-{slug or 'addon'}.html"


def render_addons_index(addons_json, stats):
    """The addon catalogue, built like the mod one but with less to filter on.

    An addon has no SPT constraint, no category and no Fika status -- it
    targets one release of one mod, and that is its whole compatibility story.
    So this page carries search, sort and the detached filter rather than the
    mod index's panel of facets, and shares its markup, stylesheet and tile
    layout so the two read as the same catalogue.
    """
    body = f"""
<form class="controls controls-narrow" onsubmit="return false">
  <input type="search" id="q" placeholder="Search addons, authors, parent mods…"
         autocomplete="off" spellcheck="false" aria-label="Search addons">
  <select id="show" aria-label="Show">
    <option value="">All addons</option>
    <option value="detached">Detached from parent</option>
  </select>
  <select id="sort" aria-label="Sort by">
    <option value="downloads">Most downloaded</option>
    <option value="updated">Recently updated</option>
    <option value="published">Newest</option>
    <option value="name">Name A–Z</option>
    <option value="parent">Parent mod A–Z</option>
  </select>
</form>

<div class="resultbar">
  <span class="countgroup">
    <span class="counts">
      <span id="count">Showing {stats['addon_count']:,} addons</span>
    </span>
    <a class="switchbtn" href="index.html">Mods</a>
  </span>
  <span class="resultactions">
    <button type="button" class="linkbtn" id="reset-filters">Reset filters</button>
  </span>
</div>

<div class="listscroll" id="listscroll">
  <div class="modlist" id="addonlist"></div>
  <div id="sentinel"></div>
</div>

<noscript>
  <p class="empty">Searching and sorting need JavaScript, but every addon has
  its own page — see <a href="all-addons.html">the full addon list</a>.</p>
</noscript>

<script id="addon-index" type="application/json">{addons_json}</script>
"""
    return page("Addons · SPT Mod Archive", body, depth=0,
                scripts=("addons.js",),
                description=(f"An archive of {stats['addon_count']:,} addons "
                             "from the SPT Forge, each paired with the mod it "
                             "extends."))


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


def render_addon_versions(versions, limit=40):
    """An addon's releases. The constraint names a mod version, not an SPT one."""
    if not versions:
        return ""
    blocks = []
    for version in versions[:limit]:
        constraint = (badge(f"for mod {version['mod_constraint']}", "spt")
                      if version["mod_constraint"] else "")
        notes = localize_links(clean_html(version["description"]), "../")
        blocks.append(f"""
  <div class="version">
    <div class="vhead">
      <span class="num">{e(version['version'] or '—')}</span>
      {constraint}
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


def render_addon(addon, parent, images=None, repos=None):
    """One addon's page: what it is, what it extends, and every release.

    Deliberately simpler than a mod page. An addon has no repository, no
    dependencies and no comments -- the Forge never gave it any -- so the
    page is its description, its versions, and a way back to its parent mod.
    """
    images = images or {}
    authors = author_links(addon["authors"])
    description = localize_links(
        localize_images(clean_html(addon["description_html"]), images, "../"),
        "../")

    # Compatibility first, same order the mod pages and tiles use: for an
    # addon the parent-version constraint is what the SPT badge is for a mod.
    flags = []
    if addon["mod_constraint"]:
        flags.append(badge(f"for mod {addon['mod_constraint']}", "spt"))
    flags.append(badge("Addon", "cat"))
    # "Detached" is the Forge's own word for an addon whose parent mod is gone.
    # It is the one state that makes an addon unusable, so it is flagged red.
    if addon["detached"]:
        flags.append(badge("Detached from parent ✗", "bad"))
    for key, label in (("contains_ads", "Contains ads"),
                       ("contains_ai_content", "Contains AI content")):
        if addon["flags"].get(key):
            flags.append(badge(label, "warn"))

    thumb = (f'<img src="{e(local_image(addon["thumbnail"], images, "../"))}" '
             f'alt="" loading="lazy">' if addon["thumbnail"]
             else f'<div class="headthumb-empty" aria-hidden="true">'
                  f'{e((addon["name"] or "?")[:1].upper())}</div>')

    if parent:
        parent_html = (
            f'<p class="addonparent">Extends '
            f'<a href="../{e(parent["href"])}">{e(parent["name"])}</a></p>')
    else:
        parent_html = ('<p class="addonparent">The mod this addon extends is '
                       'not in the archive.</p>')

    facts = [
        ("Downloads", f"{addon['downloads']:,}"),
        ("Latest version", addon["latest_version"] or "—"),
        ("Latest release", fmt_date(addon["versions"][0]["published_at"])
         if addon["versions"] else "—"),
        ("Published", fmt_date(addon["published_at"]) or "—"),
        ("License", addon["license"].get("name") or "—"),
    ]
    fact_html = facts_html(facts)

    sections = []
    if description:
        sections.append(("description", "Description", None,
                         f'<div class="prose">{description}</div>'))
    if addon["versions"]:
        sections.append(("versions", "Versions", len(addon["versions"]),
                         render_addon_versions(addon["versions"])))

    body = f"""
<p class="crumbs"><a href="../addons.html">← Back to the addons</a></p>

<div class="modhead">
  {thumb}
  <div class="modhead-main">
    <div class="modhead-title">
      <h1>{e(addon['name'])}</h1>
      {mark_button(f"a{addon['id']}", addon['name'],
                   "addon/" + addon_href(addon),
                   [l["url"] for l in addon["source_links"]], label=True,
                   parent=addon['mod_id'] if parent else None)}
    </div>
    <div class="bylinerow">
      <div class="byline">by {authors}</div>
      <div class="badges">{"".join(flags)}</div>
    </div>
    {f'<p class="teaser">{e(addon["teaser"])}</p>' if addon["teaser"] else ''}
    {parent_html}
  </div>
</div>

<div class="splitcols">
  <section class="panel">
    <div class="factshead">
      <h2>Details</h2>
      {badge(f"for mod {addon['mod_constraint']}", "spt") if addon['mod_constraint'] else ''}
    </div>
    <div class="facts">{fact_html}</div>
  </section>
  <section class="panel">
    <h2>Source</h2>
    {render_source_links(addon['source_links'], repos or {})}
    <p class="forgelink"><a href="{e(addon['forge_url'])}" target="_blank"
    rel="noopener noreferrer">Original Forge page</a>
    <span class="label">offline after shutdown</span></p>
  </section>
</div>

{render_section_tabs(sections)}
"""
    return page(f"{addon['name']} · SPT Mod Archive", body, depth=1,
                scripts=("tabs.js",),
                description=to_text(addon["teaser"]
                                    or addon["description_html"], 160))


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


# --- mod lists -----------------------------------------------------------

def list_href(entry):
    slug = "".join(c if (c.isalnum() or c in "-_") else "-"
                   for c in (entry.get("slug") or "list")).strip("-").lower()
    return f"{entry['id']}-{slug or 'list'}.html"


def render_lists(lists):
    """Index of every archived mod list."""
    rows = []
    for entry in lists:
        spt = (badge(f"SPT {entry['spt_version']}", "spt")
               if entry["spt_version"] else "")
        rows.append(f"""
  <article class="listcard">
    <div>
      <h2 class="title"><a href="list/{e(list_href(entry))}">{e(entry['title'])}</a></h2>
      <div class="byline">by {e(entry['owner']['name'] or 'unknown')}</div>
      <div class="badges">{spt}
        {badge(plural(entry['mod_count'], 'mod'))}</div>
    </div>
    <div class="stats"><div class="statnums">
      <b>{entry['mod_count']}</b>mods</div></div>
  </article>""")

    body = f"""
<p class="crumbs"><a href="index.html">← Back to the archive</a></p>
<div class="panel">
  <h2>Mod lists ({len(lists)})</h2>
  <p class="panel-note">Modpacks curated by Forge users: sets of mods someone
  ran together on a given SPT version. Open one to add the whole list to your
  collection.</p>
</div>
<div class="modlist">{"".join(rows)}</div>
"""
    return page("Mod lists · SPT Mod Archive", body, depth=0,
                description=f"{len(lists)} curated SPT mod lists archived from "
                            "the Forge.")


def render_list(entry, lookup):
    """One archived list: its mods, linked, and importable as a collection."""
    rows, missing = [], 0
    for mod_id in entry["mod_ids"]:
        mod = (lookup or {}).get(mod_id)
        if not mod:
            missing += 1
            continue
        # Same card as a mod's dependencies and addons. A list is the third
        # place the archive says "here is a set of mods to install", and there
        # is no reason for it to look like a different kind of thing.
        thumb = (f'<img class="depthumb" src="../{e(mod["thumb"])}" alt=""'
                 f' loading="lazy">' if mod.get("thumb") else
                 '<span class="depthumb"></span>')
        teaser = (f'<p class="teaser">{e(mod["teaser"])}</p>'
                  if mod.get("teaser") else "")
        rows.append(f"""
  <li class="depcard">
    {thumb}
    <div class="depmain">
      <a class="depname" href="../{e(mod['href'])}">{e(mod['name'])}</a>
      {teaser}
    </div>
    {mark_button(mod['id'], mod['name'], mod['href'], mod['sources'])}
  </li>""")

    note = (f'<p class="panel-note">{missing} mod(s) in this list are no longer '
            f'in the archive.</p>' if missing else "")
    spt = (badge(f"SPT {entry['spt_version']}", "spt")
           if entry["spt_version"] else "")

    body = f"""
<p class="crumbs"><a href="../lists.html">← All mod lists</a></p>

<div class="modhead">
  <div class="modhead-main">
    <div class="modhead-title">
      <h1>{e(entry['title'])}</h1>
      <button type="button" class="mark mark-wide" id="import-list">
        <span class="mark-label">Add all to collection</span></button>
    </div>
    <div class="byline">by {author_link(entry['owner'])}</div>
    <div class="badges">{spt}{badge(plural(len(rows), 'mod'))}</div>
  </div>
</div>

<section class="panel">
  <h2>Mods in this list</h2>
  {note}
  <ul class="deplist listmods">{"".join(rows)}</ul>
</section>

<section class="panel">
  <h2>Source</h2>
  <p><a href="{e(entry['forge_url'])}" target="_blank" rel="noopener noreferrer">
  Original list on the Forge</a>
  <span class="label">offline once the Forge shuts down</span></p>
</section>
"""
    return page(f"{entry['title']} · SPT Mod Archive", body, depth=1,
                scripts=("importlist.js",),
                description=to_text(entry["description"], 160))


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
    # Stars are not here: they head the panel beside the download, next to the
    # repository that download comes from. Keeping a count in both places
    # invites them to describe different repositories on a multi-repo mod.
    if status.get("archived"):
        bits.append("archived by its author")

    return f'<span class="label">{e(" · ".join(bits))}</span>' if bits else ""


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


DOWNLOAD_ICON = (
    '<svg viewBox="0 0 16 16" width="22" height="22" aria-hidden="true"'
    ' focusable="false" fill="none" stroke="currentColor" stroke-width="1.5"'
    ' stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M8 2v7.5"/><path d="M4.75 6.5 8 9.75l3.25-3.25"/>'
    '<path d="M3 12.75h10"/></svg>')


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


def render_source_links(links, repos):
    """One row per repository: what it is, then how it is doing."""
    if not links:
        return '<p class="empty">No source repository was listed.</p>'

    rows = []
    for link in links:
        status = repos.get(link["url"]) or {}
        tag = (f'<span class="label">{e(link["label"])}</span>'
               if link.get("label") else "")
        note = repo_note(status)
        rows.append(f"""
    <li class="sourcerow">
      <div class="sourcetop">
        <a href="{e(link['url'])}" target="_blank" rel="noopener noreferrer">
          {e(repo_name(link['url'], status))}</a>
        <span class="host">{e(repo_host_label(link['url']))}</span>
        {tag}
      </div>
      {f'<div class="sourcemeta">{note}</div>' if note else ''}
    </li>""")
    return f'<ul class="sourcelist">{"".join(rows)}</ul>'


def render_facts_and_source(mod, repos, facts_html):
    """Key numbers and repositories side by side, to halve the page height."""
    releases = releases_url(mod["source_links"], repos)
    # The download goes to the actual file where the host names one, and to
    # the releases page otherwise. Both beat the Forge's own download, which
    # stops existing on shutdown day.
    asset_url, asset_name = latest_download(mod["source_links"], repos)
    download_url = asset_url or releases
    download_title = (f"Download {asset_name}" if asset_name
                      else "Downloads / releases")

    # The star count sits beside the download because both describe the same
    # repository -- the first one that resolves, which is the one the download
    # comes from and the one the page leads with.
    primary = next((r for r in ((repos or {}).get(l["url"]) or {}
                                for l in mod["source_links"])
                    if r.get("status") == "ok"), {})
    stars = (f'<a class="stars" href="{e(primary["url"])}" target="_blank"'
             f' rel="noopener noreferrer"'
             f' title="{primary["stars"]:,} stars on {e(repo_host_label(primary["url"]))}">'
             f'★ {primary["stars"]:,}</a>' if primary.get("stars") else "")
    # "Which SPT does this run on" is the first question asked of any mod, so
    # it heads the panel at the far edge rather than queuing with the tags.
    spt = (badge(f"SPT {spt_label(mod['spt_constraint'])}", "spt")
           if mod["spt_constraint"] else "")
    forge_link = (f'<p class="forgelink"><a href="{e(mod["forge_url"])}" '
                  f'target="_blank" rel="noopener noreferrer">Original Forge '
                  f'page</a> <span class="label">offline after shutdown</span></p>'
                  if mod["forge_url"] else "")
    return f"""
<div class="splitcols">
  <section class="panel">
    <div class="factshead">
      <h2>Details</h2>
      {spt}
    </div>
    <div class="facts">{facts_html}</div>
  </section>
  <section class="panel">
    <div class="sourcehead">
      <h2>Source</h2>
      {stars}
      {f'<a class="sourcedl" href="{e(download_url)}" target="_blank" '
       f'rel="noopener noreferrer" title="{e(download_title)}" '
       f'aria-label="{e(download_title)}">{DOWNLOAD_ICON}</a>'
       if download_url else ''}
    </div>
    {render_source_links(mod['source_links'], repos)}
    {forge_link}
  </section>
</div>"""


def render_dependencies(mod, lookup):
    """A mod's dependencies as cards: what they are, not just their names.

    Anything the archive holds gets its thumbnail, teaser and a collection
    button, so the tab answers "what am I about to install" without a detour
    through each mod's own page. Dependencies we never archived still get a
    row, pointing at the Forge while it lasts.
    """
    # The latest version's dependencies, not the union across all versions:
    # this answers "what do I need to install today", and a mod that dropped a
    # dependency years ago should not still demand it.
    deps = mod["dependencies"]
    if not deps:
        return ""

    rows = []
    for dep in deps:
        entry = (lookup or {}).get(dep.get("id"))
        if entry:
            thumb = (f'<img class="depthumb" src="../{e(entry["thumb"])}" alt=""'
                     f' loading="lazy">' if entry.get("thumb")
                     else '<span class="depthumb"></span>')
            teaser = (f'<p class="teaser">{e(entry["teaser"])}</p>'
                      if entry.get("teaser") else "")
            rows.append(f"""
    <li class="depcard">
      {thumb}
      <div class="depmain">
        <a class="depname" href="../{e(entry['href'])}">{e(entry['name'])}</a>
        {teaser}
      </div>
      {mark_button(entry['id'], entry['name'], entry['href'], entry['sources'])}
    </li>""")
        else:
            name = e(dep.get("name") or f"Mod {dep.get('id')}")
            link = (f'<a href="{e(dep["url"])}" target="_blank" '
                    f'rel="noopener noreferrer">{name}</a>' if dep.get("url")
                    else name)
            rows.append(f"""
    <li class="depcard">
      <span class="depthumb"></span>
      <div class="depmain">
        <span class="depname">{link}</span>
        <p class="teaser">Not in the archive — this mod was never listed, or
        was removed before it could be captured.</p>
      </div>
    </li>""")

    return f'<ul class="deplist">{"".join(rows)}</ul>'


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


def version_notes(uid, forge_notes, repo_notes, host_label):
    """One version's release text, from each source that has one.

    Two accounts of the same release, written for different audiences and
    disagreeing often enough to be worth telling apart -- so they get a tab
    each rather than being stacked. Only the sources that exist are offered:
    a mod with no repository text shows the Forge's alone, and once the Forge
    is gone its tab simply stops being emitted, leaving the repository's.

    The switch is radio inputs and labels, not script. There is one of these
    per version -- forty on a long page -- and tabs.js drives a single strip
    by id, so this has to work on its own. `uid` namespaces the radio group so
    that switching one version does not switch every other version with it.
    """
    if not (forge_notes or repo_notes):
        return ""

    def panel(kind, html):
        return f'<div class="vpanel p-{kind}"><div class="notes prose">{html}</div></div>'

    if not (forge_notes and repo_notes):
        # A single source needs no switch, but does need saying which it is,
        # because the two are not interchangeable.
        kind, html = ("forge", forge_notes) if forge_notes else ("repo", repo_notes)
        label = "The Forge" if kind == "forge" else host_label
        return (f'<div class="vsources one">'
                f'<div class="vtabs"><span class="vtab-static">{e(label)}</span></div>'
                f'{panel(kind, html)}</div>')

    group = f"v{e(uid)}"
    return f"""
    <div class="vsources">
      <input class="vin vin-forge" type="radio" name="{group}" id="{group}f" checked>
      <input class="vin vin-repo" type="radio" name="{group}" id="{group}r">
      <div class="vtabs">
        <label class="vtab lab-forge" for="{group}f">The Forge</label>
        <label class="vtab lab-repo" for="{group}r">{e(host_label)}</label>
      </div>
      <div class="vpanels">
        {panel("forge", forge_notes)}
        {panel("repo", repo_notes)}
      </div>
    </div>"""


def render_versions(versions, limit=40, releases=None):
    """A mod's version history, each linked to the release that shipped it.

    The Forge's own download for a version dies with the site, so where a
    repository tagged the same version number the block links there instead --
    which is the version's actual file, and outlives the listing.
    """
    if not versions:
        return ""
    releases = releases or {}
    blocks = []
    for version in versions[:limit]:
        notes = localize_links(clean_html(version["description"]), "../")
        fika_text, fika_kind = FIKA_LABEL.get(version["fika"],
                                              FIKA_LABEL["unknown"])
        release = releases.get(version_key(version["version"])) or {}
        download = (
            f'<a class="vdl" href="{e(release["url"])}" target="_blank"'
            f' rel="noopener noreferrer"'
            f' title="Download {e(version["version"])} from the repository"'
            f' aria-label="Download {e(version["version"])}">{DOWNLOAD_ICON}</a>'
            if release.get("url") else "")

        repo_notes = clean_html(release.get("notes", ""))
        body = version_notes(version.get("id") or version["version"],
                             notes, repo_notes,
                             release.get("host_label") or "Repository")
        blocks.append(f"""
  <div class="version">
    <div class="vhead">
      <span class="num">{e(version['version'] or '—')}</span>
      {badge('SPT ' + spt_label(version['spt_constraint']), 'spt') if version['spt_constraint'] else ''}
      {badge(fika_text, fika_kind)}
      <span class="when">{e(fmt_date(version['published_at']))} ·
        {version['downloads']:,} downloads</span>
      {download}
    </div>
    {body}
  </div>""")

    more = (f'<p class="empty">{len(versions) - limit} older versions not shown.</p>'
            if len(versions) > limit else "")
    return f"""
    <div class="versions">{"".join(blocks)}</div>
    {more}"""


def render_comment(comment, replies, images=None):
    body = localize_links(
        localize_images(clean_html(comment["body_html"]), images or {}, "../"),
        "../")
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
    for dep in mod["dependencies"]:
        entry = (lookup or {}).get(dep.get("id"))
        if entry and entry["id"] not in seen:
            seen.add(entry["id"])
            entries.append(entry)
    return entries


def render_addon_cards(addons, parent_id=None):
    """A mod's addons as cards, laid out exactly like its dependencies.

    Same shape as render_dependencies deliberately: both answer "what else do
    I install alongside this", and giving them one look means a reader learns
    the card once. Each is addable on its own, and files itself under the mod
    it extends in the collection drawer.
    """
    if not addons:
        return ""

    rows = []
    for addon in addons:
        thumb = (f'<img class="depthumb" src="../{e(addon["thumb"])}" alt=""'
                 f' loading="lazy">' if addon.get("thumb")
                 else '<span class="depthumb"></span>')
        teaser = (f'<p class="teaser">{e(addon["teaser"])}</p>'
                  if addon.get("teaser") else "")
        note = (badge("Detached ✗", "bad") if addon.get("detached")
                else (badge(f"for {addon['mod_constraint']}", "spt")
                      if addon.get("mod_constraint") else ""))
        rows.append(f"""
    <li class="depcard">
      {thumb}
      <div class="depmain">
        <a class="depname" href="../{e(addon['href'])}">{e(addon['name'])}</a>
        {teaser}
      </div>
      <div class="depside">
        {note}
        {mark_button(addon['mark_id'], addon['name'], addon['href'],
                     addon.get('sources') or (), parent=parent_id)}
      </div>
    </li>""")
    return f'<ul class="deplist">{"".join(rows)}</ul>'


def render_tabs(mod, description, comment_data, images, lookup=None,
                addons=(), releases=None):
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
    # Directly after Description: an addon is something you install *for this
    # mod*, so it belongs beside the mod's own text rather than behind its
    # version history.
    if addons:
        sections.append(("addons", "Addons", len(addons),
                         render_addon_cards(addons, mod["id"])))
    dependencies = render_dependencies(mod, lookup)
    if dependencies:
        sections.append(("dependencies", "Dependencies",
                         len(mod["dependencies"]), dependencies))
    if versions:
        sections.append(("versions", "Versions", len(versions),
                         render_versions(versions, releases=releases)))
    if comments:
        sections.append(("comments", "Comments", len(comments),
                         render_comments(comment_data, images)))

    if not sections:
        return ('<section class="panel"><p class="empty">No description, '
                'versions, or comments were archived for this mod.</p></section>')
    return render_section_tabs(sections)


def render_section_tabs(sections, empty=""):
    """`(slug, label, count, content)` rows as a tab strip over panels.

    Shared by mod and addon pages so both get the same markup, and so tabs.js
    -- which finds the strip by id and the panels by class -- keeps working on
    both without knowing which kind of page it is on.
    """
    if not sections:
        return (f'<section class="panel"><p class="empty">{e(empty)}</p></section>'
                if empty else "")

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
               href="", lookup=None, addons=()):
    """One mod's page: everything the archive holds about it."""
    authors = author_links(mod["authors"])
    images = images or {}
    # Mod pages sit one directory deep, so mirrored images are ../assets/img/.
    description = localize_links(
        localize_images(clean_html(mod["description_html"]), images, "../"),
        "../")
    category = mod.get("category") or {}

    flags = []
    flags.append(badge(*FIKA_LABEL[fika_state(mod)]))
    if category.get("title"):
        flags.append(badge(category["title"], "cat"))
    # The SPT version is not here with the other tags: it heads the Details
    # panel, where the facts it belongs with are.
    if mod["origin"] == "community":
        flags.append(badge("Community submission", "community"))
    for key, label in (("contains_ads", "Contains ads"),
                       ("contains_ai_content", "Contains AI content"),
                       ("cheat_notice", "Cheat notice"),
                       ("profile_binding_notice", "Binds to profile")):
        if mod["flags"].get(key):
            flags.append(badge(label, "warn"))

    # A mod with no thumbnail still gets the block, so its title starts in the
    # same place as every other mod's. The Forge fills this slot with the SPT
    # logo, which this archive will not do -- it states plainly that it is
    # unaffiliated, and 129 pages of someone else's branding would say
    # otherwise. The mod's own initial reads as deliberate instead of broken.
    thumb = (f'<img src="{e(local_image(mod["thumbnail"], images, "../"))}" '
             f'alt="" loading="lazy">' if mod["thumbnail"]
             else f'<div class="headthumb-empty" aria-hidden="true">'
                  f'{e((mod["name"] or "?")[:1].upper())}</div>')

    # No SPT row: the version heads the panel these facts sit in, and stating
    # it twice inside one panel reads as two different facts at a glance.
    facts = [
        ("Downloads", f"{mod['downloads']:,}"),
        ("Latest version", mod["latest_version"] or "—"),
        ("Latest release", fmt_date(last_release(mod)) or "—"),
        ("Published", fmt_date(mod["published_at"]) or "—"),
        ("License", (mod["license"].get("name") or "—")),
        # The mod's own identifier, which is what a config file, a load-order
        # error or another mod's dependency list actually names it by -- so it
        # is the one fact here you might need to copy verbatim. The Forge
        # itself shows "Not Available" for the 1,086 mods that declare none.
        ("GUID", mod.get("guid") or "Not available"),
    ]
    fact_html = facts_html(facts)

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
    <div class="bylinerow">
      <div class="byline">by {authors}</div>
      <div class="badges">{"".join(flags)}</div>
    </div>
    {f'<p class="teaser">{e(mod["teaser"])}</p>' if mod["teaser"] else ''}
  </div>
</div>

{render_facts_and_source(mod, repos, fact_html)}

{render_tabs(mod, description, comment_data, images, lookup, addons,
             release_index(mod, repos))}
"""
    return page(f"{mod['name']} · SPT Mod Archive", body, depth=1,
                scripts=("tabs.js", "comments.js"),
                description=to_text(mod["teaser"] or mod["description_html"], 160))
