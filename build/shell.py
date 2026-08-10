"""Every HTML file the archive publishes.

Three catalogue pages at the root, and one small page per record at the URL
that record has always had. All of them are the same shape: the masthead, the
footer, and a container that the script named in `<body data-page>` fills from
`data/`.

A record page is around 700 bytes. What makes it worth writing 3,000 of them
rather than serving one `m.html?id=N` shell for all of them is what those 700
bytes say: the mod's real title, its real description, and its teaser in a
`<noscript>`. That is the part a crawler, a link preview, a feed reader or a
browser with scripting off can see without executing anything -- and it is
per-URL, which one shared shell cannot be. The 45 KB of rendered detail that
used to sit behind it is fetched as JSON instead.

So the old URLs are not preserved by redirecting them somewhere; they are
simply still the pages. Nothing in the sitemap moved.
"""

import json
import os

import templates
from sanitize import to_text
from templates import e


def shell(title, description, page_id, body, scripts, *, depth=0, record_id=None):
    """Chrome, an empty container, and the script that fills it.

    `record_id` is what a detail page is *about*, carried on the body rather
    than in a query string -- the page is a real file at its own URL, so the id
    belongs to the document, not to how you arrived at it.
    """
    marker = f' data-id="{e(record_id)}"' if record_id is not None else ""
    return templates.page(title, body, depth=depth, description=description,
                          scripts=scripts).replace(
        "<body>", f'<body data-page="{e(page_id)}"{marker}>', 1)


# A shell's container is empty on arrival, so it says so. The message is
# replaced by content or by an error; it is never the resting state of a
# working page.
LOADING = """
<div id="page" class="pageroot" aria-busy="true">
  <p class="empty" id="page-status">Loading…</p>
</div>
<noscript>
  <p class="empty">This page is assembled in the browser and needs JavaScript.
  Every mod also has a plain listing — see <a href="all-mods.html">the full mod
  list</a>.</p>
</noscript>
"""


def render_index_shell():
    """The catalogue. Filters are built from data/facets.json, not baked in."""
    body = """
<form class="controls" onsubmit="return false">
  <input type="search" id="q" placeholder="Search mods, authors, dependencies…"
         autocomplete="off" spellcheck="false" aria-label="Search mods">
  <select id="category" aria-label="Category">
    <option value="">All categories</option>
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
      <div id="spt-groups"></div>
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
      <span id="count">Loading the catalogue…</span>
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
"""
    return shell("SPT Mod Archive",
                 "An archive of Single Player Tarkov mods from the SPT Forge, "
                 "including Fika compatibility, dependencies, and comments.",
                 "index", body, ("render.js", "index.js"))


def render_addons_shell():
    body = """
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
      <span id="count">Loading the addons…</span>
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
"""
    return shell("Addons · SPT Mod Archive",
                 "An archive of addons from the SPT Forge, each paired with the "
                 "mod it extends.",
                 "addons", body, ("render.js", "addons.js"))


def render_lists_shell():
    body = """
<p class="crumbs"><a href="index.html">← Back to the archive</a></p>
<div class="panel">
  <h2 id="lists-heading">Mod lists</h2>
  <p class="panel-note">Modpacks curated by Forge users: sets of mods someone
  ran together on a given SPT version. Open one to add the whole list to your
  collection.</p>
</div>
<div class="modlist" id="listgrid"></div>
<p class="empty" id="page-status">Loading…</p>
"""
    return shell("Mod lists · SPT Mod Archive",
                 "Curated SPT mod lists archived from the Forge.",
                 "lists", body, ("render.js", "lists.js"))


# --- one page per record -------------------------------------------------

DETAIL_SCRIPTS = {
    "mod": ("render.js", "tabs.js", "comments.js", "mod.js"),
    "addon": ("render.js", "tabs.js", "addon.js"),
    "list": ("render.js", "importlist.js", "list.js"),
    "user": ("render.js", "tabs.js", "user.js"),
}


def detail_page(kind, record_id, title, description, heading, teaser, back):
    """One record's page: what it is, in HTML, and where to get the rest.

    The `<noscript>` is not a courtesy notice -- it is the content. A reader
    with scripting off, a crawler that does not run it, and a link preview all
    get the mod's name and what it does, plus a route into the plain listing.
    That is the whole reason these are separate files.
    """
    body = f"""
<p class="crumbs"><a href="../{e(back[0])}">← {e(back[1])}</a></p>
<div id="page" class="pageroot" aria-busy="true">
  <h1>{e(heading)}</h1>
  {f'<p class="teaser">{e(teaser)}</p>' if teaser else ''}
  <p class="empty" id="page-status">Loading…</p>
</div>
<noscript>
  <p class="empty">The rest of this page — versions, dependencies, source
  repositories and archived comments — is assembled in the browser and needs
  JavaScript. Every mod is also listed plainly on
  <a href="../all-mods.html">the full mod list</a>.</p>
</noscript>
"""
    return shell(title, description, kind, body, DETAIL_SCRIPTS[kind],
                 depth=1, record_id=record_id)


def write_detail_pages(write, mods, addons, mod_lists, authors,
                       mod_href, url_for):
    """A page per mod, addon, list and author, at the URL it has always had."""
    written = 0

    for mod in mods:
        teaser = to_text(mod["teaser"] or mod["description_html"], 200)
        write(url_for["mod"](mod),
              detail_page("mod", mod["id"],
                          f"{mod['name']} · SPT Mod Archive", teaser,
                          mod["name"], teaser,
                          ("index.html", "Back to the archive")))
        written += 1

    for addon in addons:
        teaser = to_text(addon["teaser"] or addon["description_html"], 200)
        write(url_for["addon"](addon),
              detail_page("addon", addon["id"],
                          f"{addon['name']} · SPT Mod Archive", teaser,
                          addon["name"], teaser,
                          ("addons.html", "Back to the addons")))
        written += 1

    for entry in mod_lists:
        teaser = to_text(entry.get("description") or "", 200) or (
            f"{entry['mod_count']} mods curated on the SPT Forge.")
        write(url_for["list"](entry),
              detail_page("list", entry["id"],
                          f"{entry['title']} · SPT Mod Archive", teaser,
                          entry["title"], teaser,
                          ("lists.html", "All mod lists")))
        written += 1

    for author in authors:
        summary = f"{author['name']} on the SPT Mod Archive."
        write(url_for["user"](author),
              detail_page("user", author["id"],
                          f"{author['name']} · SPT Mod Archive", summary,
                          author["name"], "",
                          ("index.html", "Back to the archive")))
        written += 1

    return written
