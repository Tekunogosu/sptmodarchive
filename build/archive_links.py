"""Point links that go to the Forge or the old Hub back into this archive.

Mod descriptions, version notes and comments are full of links to *other*
mods -- "install [BigBrain] first", "this conflicts with [SAIN]", years of
comments answering questions with a link. They point at three sites that are
all going away:

    https://sp-mod.com/mod/902/bigbrain                   the site today
    https://forge.sp-tarkov.com/mod/902/bigbrain          the Forge before it
    https://hub.sp-tarkov.com/files/file/1219-bigbrain/   the Hub before that
    https://forge.sp-tarkov.com/list/119138/spt-modlist   a curated list

Every one of them is a dead end on the day this archive starts to matter, even
though the page it wants is sitting right here. Where we hold the target, the
link is rewritten to its page in the archive; the fragment comes along, because
"see the versions tab" is most of why people linked deep in the first place.

Links we cannot resolve are left exactly as they were. A link to a dead site
still records where the thing used to live, which is more than a stripped one
does, and roughly one Hub link in five names a mod that never made it to the
Forge and so was never archived.

Not rewritten: `mods.sp-tarkov.com`, the site before the Hub. Its file ids look
identical but belong to their own numbering, so mapping them would silently
send people to an unrelated mod. Fifteen links, all long dead.
"""

import re
from urllib.parse import urlsplit

from sanitize import OUTBOUND_ATTRS

# Set once per build by set_link_map(). Rendering reaches for it from three
# places nested well inside a mod page, so it is configured rather than
# threaded, the same way ARCHIVE_TOTAL is in templates.py.
LINKS = {}

# Both eras. sp-mod.com replaced forge.sp-tarkov.com and kept the same URL
# shapes *and the same mod ids*, so a link written against either one resolves
# to the same archived page -- which is why this is one set rather than a
# migration. (Verified: of the 1,830 mods present on both, every one kept its
# id.) The old host still appears in thousands of descriptions and comments.
FORGE_HOSTS = {"sp-mod.com", "forge.sp-tarkov.com"}
HUB_HOSTS = {"hub.sp-tarkov.com"}

# Where a Forge/Hub fragment lands on our page. Both sites had the same three
# sections we do, under two different names, and comment permalinks can only
# be honoured as far as the comments panel -- we do not id individual comments.
FRAGMENTS = {
    "overview": "description",
    "description": "description",
    "versions": "versions",
    "comments": "comments",
}


def build_map(mods, mod_lists, mod_href, list_href, addons=(), addon_href=None,
              authors=(), author_href=None):
    """Every archived page, keyed by each URL that used to lead to it.

    Each `*_href` returns a target relative to the site root, complete -- not a
    filename this function then guesses a directory for. build.py passes the
    same functions it links with everywhere else, because a rewritten link that
    disagrees with the real one by a character is a 404, and only worse than
    the dead Forge link it replaced.

    A mod is reachable by two ids -- the Forge's, and, for anything predating
    the migration, the Hub id it carried before. Both are recorded, because old
    comments overwhelmingly use the Hub one.
    """
    links = {}
    for mod in mods:
        href = mod_href(mod)
        links[("mod", str(mod["id"]))] = href
        if mod.get("hub_id"):
            links[("hub", str(mod["hub_id"]))] = href
    for entry in mod_lists:
        links[("list", str(entry["id"]))] = list_href(entry)
    for addon in addons:
        links[("addon", str(addon["id"]))] = addon_href(addon)
    # Only authors get a /user/ page, so a link to a commenter who published
    # nothing stays pointed at the Forge -- there is nothing here to show.
    #
    # Archive-only authors are keyed "27632-arch", but every /user/ link ever
    # written in a description or a comment says plain "27632" -- those were
    # all authored on the Forge, whose ids these are. So the bare number is
    # registered as an alias.
    #
    # Live authors are recorded second and therefore win the alias, which is
    # the right way round: sp-mod.com issued their id, so a link carrying it
    # was written against sp-mod.com and means them. The collision is possible
    # rather than common -- the new site's ids start low and the Forge's run to
    # six figures -- and the alternative is leaving thousands of old links dead
    # to protect against it.
    aliases, primary = {}, {}
    for author in authors:
        key = str(author["id"])
        primary[key] = author_href(author)
        stem = key[:-len("-arch")] if key.endswith("-arch") else key
        if stem != key:
            aliases.setdefault(stem, author_href(author))
    for stem, href in aliases.items():
        links.setdefault(("user", stem), href)
    for key, href in primary.items():
        links[("user", key)] = href
    return links


def set_link_map(mods, mod_lists, mod_href, list_href,
                 addons=(), addon_href=None, authors=(), author_href=None):
    global LINKS
    LINKS = build_map(mods, mod_lists, mod_href, list_href, addons, addon_href,
                      authors, author_href)


def _key(url):
    """Which archived page a URL is asking for, or None if it isn't ours.

    Download URLs resolve to the mod's page rather than being left alone: the
    file behind them dies with whichever site served it, and the page carries the repository
    the mod actually lives in, which is the closest thing to the download that
    will still exist.
    """
    # A bare "forge.sp-tarkov.com/mod/902/x" parses as a path unless it is told
    # the first segment is a host; a rooted "/mod/902/x" genuinely has none.
    rooted = url.startswith("/") or "//" in url
    parts = urlsplit(url if rooted else "//" + url, scheme="https")
    host = parts.netloc.lower().split("@")[-1].split(":")[0]
    host = host[4:] if host.startswith("www.") else host
    segments = [s for s in parts.path.split("/") if s]

    # A scheme-less, host-less "/mod/1298/name" can only have meant the Forge
    # or its successor: the Hub kept its mods under /files/. Either way the id
    # is the same, so naming one of them here is enough.
    if not host and segments and segments[0] == "mod":
        host = "forge.sp-tarkov.com"

    if host in FORGE_HOSTS:
        # /mod/{id}/{slug}, /mod/download/{id}/{slug}/{version}, /list/{id}/…,
        # /user/{id}/{slug}, and the same two shapes for /addon/.
        if segments[:1] in (["mod"], ["list"], ["addon"], ["user"]):
            rest = segments[2:] if segments[1:2] == ["download"] else segments[1:]
            if rest and rest[0].isdigit():
                return (segments[0], rest[0])
    elif host in HUB_HOSTS:
        # /files/file/{id}-{slug}, /files/download/{id}-{slug}
        if segments[:1] == ["files"] and segments[1:2] in (["file"], ["download"]):
            file_id = segments[2].split("-")[0] if len(segments) > 2 else ""
            if file_id.isdigit():
                return ("hub", file_id)
    return None


def local_href(url, up=""):
    """This archive's URL for a Forge/Hub link, or None if we can't place it."""
    key = _key(url)
    href = LINKS.get(key) if key else None
    if not href:
        return None

    fragment = urlsplit(url).fragment
    if fragment.startswith("comments-comment"):
        fragment = "comments"
    anchor = FRAGMENTS.get(fragment.lower(), "")
    return f"{up}{href}" + (f"#{anchor}" if anchor else "")


_A_TAG_RE = re.compile(r"<a\s[^>]*>")
_HREF_RE = re.compile(r'href="([^"]*)"')


def localize_links(html, up=""):
    """Rewrite every link in a sanitised fragment that we can bring home.

    `up` is the climb from the page being rendered back to the site root, so
    mod pages pass "../". Links that land inside the archive lose the
    new-tab-and-nofollow treatment sanitize.py gives outbound ones: staying in
    the tab is what every other link on the page does, and telling search
    engines not to follow our own pages would strand them.
    """
    if not LINKS or "<a" not in html:
        return html

    def relink(match):
        tag = match.group(0)
        href = _HREF_RE.search(tag)
        if not href:
            return tag
        local = local_href(href.group(1), up)
        if not local:
            return tag
        return (tag[:href.start(1)] + local + tag[href.end(1):]
                ).replace(OUTBOUND_ATTRS, "")

    return _A_TAG_RE.sub(relink, html)
