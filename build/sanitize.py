"""Make Forge-authored HTML safe to re-host.

Mod descriptions and comment bodies arrive as rendered HTML written by other
people. The Forge sanitises them for its own pages, but we are republishing
that markup on a different origin, so we cannot inherit its guarantees --
anything it happened to allow would execute as ours.

An allowlist is the only defensible approach: unknown tags are dropped rather
than escaped-and-hoped-about, and every attribute must be named explicitly.
This is not a general-purpose sanitiser; it is deliberately narrow, and covers
the formatting that mod descriptions and comments actually use.
"""

import re
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlparse

ALLOWED_TAGS = {
    "p", "br", "hr", "div", "span", "blockquote", "pre", "code",
    "strong", "b", "em", "i", "u", "s", "del", "ins", "sub", "sup", "mark",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li", "dl", "dt", "dd",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption",
    "a", "img", "figure", "figcaption",
}

# Tags whose *content* is as dangerous as the tag, so it is dropped too.
DROP_CONTENT = {"script", "style", "iframe", "object", "embed", "template"}

VOID_TAGS = {"br", "hr", "img"}

ALLOWED_ATTRS = {
    "a": {"href", "title"},
    "img": {"src", "alt", "title", "width", "height"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan", "scope"},
}

SAFE_SCHEMES = {"http", "https", "mailto", ""}

# Stamped on every link. Named because archive_links.py strips it back off the
# links it redirects into the archive, which are not outbound at all.
OUTBOUND_ATTRS = ' target="_blank" rel="noopener noreferrer nofollow"'


def safe_url(value):
    """Reject anything that could execute, including `javascript:` in disguise."""
    cleaned = value.strip().replace("\x00", "")
    # Control characters are stripped because `java\tscript:` is a real bypass.
    cleaned = "".join(c for c in cleaned if ord(c) >= 0x20)
    try:
        scheme = urlparse(cleaned).scheme.lower()
    except ValueError:
        return None
    return cleaned if scheme in SAFE_SCHEMES else None


class Sanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.open_tags = []
        self.suppress_depth = 0

    # --- tags ------------------------------------------------------------

    def handle_starttag(self, tag, attrs):
        if self.suppress_depth:
            if tag in DROP_CONTENT:
                self.suppress_depth += 1
            return
        if tag in DROP_CONTENT:
            self.suppress_depth = 1
            return
        if tag not in ALLOWED_TAGS:
            return

        rendered = self._attrs(tag, attrs)
        if tag in VOID_TAGS:
            self.out.append(f"<{tag}{rendered}>")
        else:
            self.out.append(f"<{tag}{rendered}>")
            self.open_tags.append(tag)

    def handle_startendtag(self, tag, attrs):
        if self.suppress_depth or tag in DROP_CONTENT or tag not in ALLOWED_TAGS:
            return
        self.out.append(f"<{tag}{self._attrs(tag, attrs)}>")

    def handle_endtag(self, tag):
        if self.suppress_depth:
            if tag in DROP_CONTENT:
                self.suppress_depth -= 1
            return
        if tag not in ALLOWED_TAGS or tag in VOID_TAGS:
            return
        # Close only if it is genuinely open, so stray end tags cannot
        # unbalance the surrounding page.
        if tag in self.open_tags:
            while self.open_tags:
                open_tag = self.open_tags.pop()
                self.out.append(f"</{open_tag}>")
                if open_tag == tag:
                    break

    def _attrs(self, tag, attrs):
        allowed = ALLOWED_ATTRS.get(tag, set())
        parts = []
        for name, value in attrs:
            name = name.lower()
            # Event handlers are excluded by the allowlist, but be explicit:
            # nothing starting with `on` is ever emitted.
            if name not in allowed or name.startswith("on") or value is None:
                continue
            if name in ("href", "src"):
                value = safe_url(value)
                if value is None:
                    continue
            parts.append(f' {name}="{escape(value, quote=True)}"')

        if tag == "a":
            # Outbound links from an archive should not leak referrers or
            # hand the opener window to the destination.
            parts.append(OUTBOUND_ATTRS)
        if tag == "img":
            parts.append(' loading="lazy"')
        return "".join(parts)

    # --- text ------------------------------------------------------------

    def handle_data(self, data):
        if not self.suppress_depth:
            self.out.append(escape(data, quote=False))

    def handle_comment(self, data):
        pass    # Livewire leaves conditional-comment markers everywhere

    def close_all(self):
        while self.open_tags:
            self.out.append(f"</{self.open_tags.pop()}>")


_YOUTUBE_RE = re.compile(
    r'<div[^>]*class="youtube-lite"[^>]*data-video-id="([A-Za-z0-9_-]{6,20})"[^>]*>'
    r'.*?</div>', re.S)


def preprocess_forge(raw):
    """Rewrite Forge-specific embeds into something that survives sanitising.

    The Forge renders videos as a bare <div> carrying the video id in a data
    attribute, with the player attached by its own JavaScript. Stripped by the
    allowlist that would leave an empty div, silently losing a link somebody
    posted -- so it becomes an ordinary link with its thumbnail instead.
    """
    def to_link(match):
        video_id = match.group(1)
        return (f'<a href="https://www.youtube.com/watch?v={video_id}">'
                f'<img src="https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" '
                f'alt="YouTube video"></a>')

    return _YOUTUBE_RE.sub(to_link, raw)


def clean_html(raw):
    """Sanitised HTML, safe to embed in a page we serve."""
    if not raw:
        return ""
    raw = preprocess_forge(raw)
    parser = Sanitizer()
    parser.feed(raw)
    parser.close()
    parser.close_all()
    return "".join(parser.out).strip()


def to_text(raw, limit=None):
    """Plain text, for search indexes and meta descriptions."""
    if not raw:
        return ""
    parser = Sanitizer()
    parser.feed(raw)
    parser.close()
    text = " ".join("".join(
        part for part in parser.out if not part.startswith("<")).split())
    from html import unescape
    text = unescape(text)
    return text[:limit].rstrip() + "…" if limit and len(text) > limit else text
