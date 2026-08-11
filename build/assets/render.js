/* Shared markup, ported from build/templates.py.
 *
 * Every function here has a counterpart in that file and emits byte-comparable
 * HTML, because site.css is unchanged and matches on these class names. If you
 * change a class here, change it there -- the no-JS listings (all-mods.html,
 * all-addons.html) are still rendered in Python and share the stylesheet.
 *
 * Nothing in this file sanitizes anything. Strings that arrive as HTML --
 * descriptions, version notes, comment bodies -- were passed through
 * sanitize.clean_html() at build time and are inserted as-is. Everything else
 * is escaped on the way in by esc(). There is no third case; if you find
 * yourself wanting one, the value belongs in the sanitized set at build time.
 */
(function () {
  "use strict";

  /* How far this page sits from the site root, written into <html data-up>
   * by templates.page(). The catalogue is at the root and gets ""; a mod,
   * addon, list or author page is one directory deep and gets "../".
   *
   * Every path the JSON carries is relative to the root, never to the page
   * reading it -- because the same value is read from both depths and is
   * stored in localStorage by the collection, which outlives the page that
   * saved it. url() is where that becomes a working link, and it is the same
   * convention collection.js already uses. */
  var UP = document.documentElement.getAttribute("data-up") || "";

  var ABSOLUTE = /^([a-z][a-z0-9+.-]*:|\/\/|\/|#)/i;

  function url(path) {
    if (!path) return "";
    return ABSOLUTE.test(path) ? path : UP + path;
  }

  var AMP = /&/g, LT = /</g, GT = />/g, QUOT = /"/g, APOS = /'/g;

  function esc(value) {
    if (value === null || value === undefined) return "";
    return String(value)
      .replace(AMP, "&amp;").replace(LT, "&lt;").replace(GT, "&gt;")
      .replace(QUOT, "&quot;").replace(APOS, "&#x27;");
  }

  /* Python's f"{n:,}". toLocaleString would follow the reader's locale and
   * print 1.234 for a German browser, which reads as a version number in a
   * list full of them. */
  function num(value) {
    return String(value || 0).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  }

  function plural(n, word, suffix) {
    return num(n) + " " + word + (n === 1 ? "" : (suffix || "s"));
  }

  function badge(text, kind) {
    return '<span class="badge ' + esc(kind || "") + '">' + esc(text) + "</span>";
  }

  var DOWNLOAD_ICON =
    '<svg viewBox="0 0 16 16" width="22" height="22" aria-hidden="true"' +
    ' focusable="false" fill="none" stroke="currentColor" stroke-width="1.5"' +
    ' stroke-linecap="round" stroke-linejoin="round">' +
    '<path d="M8 2v7.5"/><path d="M4.75 6.5 8 9.75l3.25-3.25"/>' +
    '<path d="M3 12.75h10"/></svg>';

  /* A collection toggle, carrying its whole entry so collection.js never has
   * to look anything up. Inert until that script binds it. */
  function mark(entry, wide) {
    if (!entry) return "";
    var inner = wide
      ? '<span class="mark-label"><span class="lbl-state">Add to collection</span>' +
        '<span class="lbl-hover">Remove</span></span>'
      : '<span class="mark-plus">+</span>';
    return '<button type="button" class="mark' + (wide ? " mark-wide" : "") + '"' +
      (entry.parent ? ' data-parent="' + esc(entry.parent) + '"' : "") +
      ' data-mark data-id="' + esc(entry.id) + '"' +
      ' data-name="' + esc(entry.name) + '"' +
      ' data-href="' + esc(entry.href) + '"' +
      ' data-sources="' + esc((entry.sources || []).join(" ")) + '"' +
      (entry.deps && entry.deps.length
        ? ' data-deps="' + esc(JSON.stringify(entry.deps)) + '"' : "") +
      ' aria-pressed="false">' + inner + "</button>";
  }

  function thumb(src) {
    return src
      ? '<img class="depthumb" src="' + esc(url(src)) + '" alt="" loading="lazy">'
      : '<span class="depthumb"></span>';
  }

  /* The archive's standard card. Mods, addons, dependencies and list members
   * are all answers to "what am I about to install", so they all render as
   * this. A card with a `note` puts it beside the button; that is the addon
   * variant, and the only structural difference between them. */
  function card(item) {
    if (item.missing) {
      var name = item.url
        ? '<a href="' + esc(item.url) + '" target="_blank" rel="noopener noreferrer">' +
          esc(item.name) + "</a>"
        : esc(item.name);
      return '<li class="depcard"><span class="depthumb"></span>' +
        '<div class="depmain"><span class="depname">' + name + "</span>" +
        '<p class="teaser">' + esc(item.teaser) + "</p></div></li>";
    }
    var body =
      '<li class="depcard">' + thumb(item.thumb) +
      '<div class="depmain">' +
      '<a class="depname" href="' + esc(url(item.href)) + '">' + esc(item.name) + "</a>" +
      (item.teaser ? '<p class="teaser">' + esc(item.teaser) + "</p>" : "") +
      "</div>";
    if (item.note) {
      body += '<div class="depside">' + badge(item.note[0], item.note[1]) +
        mark(item.mark) + "</div>";
    } else {
      body += mark(item.mark);
    }
    return body + "</li>";
  }

  function cards(items) {
    if (!items || !items.length) return "";
    return '<ul class="deplist">' + items.map(card).join("") + "</ul>";
  }

  function facts(pairs) {
    return pairs.map(function (pair) {
      var slug = pair[0].toLowerCase().replace(/ /g, "-");
      return '<div class="fact fact-' + esc(slug) + '">' +
        '<div class="k">' + esc(pair[0]) + "</div>" +
        '<div class="v">' + esc(pair[1]) + "</div></div>";
    }).join("");
  }

  /* `[slug, label, count, content]` rows as a tab strip over panels. Shared by
   * mod, addon and author pages so tabs.js -- which finds the strip by id --
   * works on all three without knowing which it is on. */
  function sectionTabs(sections, empty) {
    sections = sections.filter(function (s) { return s[3]; });
    if (!sections.length) {
      return empty ? '<section class="panel"><p class="empty">' + esc(empty) +
        "</p></section>" : "";
    }
    var nav = sections.map(function (s) {
      return '<a class="tab" href="#' + esc(s[0]) + '">' + esc(s[1]) +
        (s[2] ? '<span class="tabcount">' + num(s[2]) + "</span>" : "") + "</a>";
    }).join("");
    var panels = sections.map(function (s) {
      return '<section class="panel tabpanel" id="' + esc(s[0]) + '">' +
        '<h2 class="panel-heading">' + esc(s[1]) + "</h2>" + s[3] + "</section>";
    }).join("");
    return '<div class="tabs" id="mod-tabs">' +
      '<nav class="tablist" aria-label="Mod details">' + nav + "</nav>" +
      panels + "</div>";
  }

  function sourceList(rows) {
    if (!rows || !rows.length) {
      return '<p class="empty">No source repository was listed.</p>';
    }
    return '<ul class="sourcelist">' + rows.map(function (row) {
      var note = row.note
        ? '<div class="sourcemeta"><span class="label' +
          (row.note_kind ? " " + esc(row.note_kind) : "") + '">' +
          esc(row.note) + "</span></div>"
        : "";
      return '<li class="sourcerow"><div class="sourcetop">' +
        '<a href="' + esc(row.url) + '" target="_blank" rel="noopener noreferrer">' +
        esc(row.name) + "</a>" +
        '<span class="host">' + esc(row.host) + "</span>" +
        (row.label ? '<span class="label">' + esc(row.label) + "</span>" : "") +
        "</div>" + note + "</li>";
    }).join("") + "</ul>";
  }

  function authorLinks(authors) {
    if (!authors || !authors.length) return "Unknown";
    return authors.map(function (a) {
      return a.href
        ? '<a href="' + esc(url(a.href)) + '">' + esc(a.name) + "</a>"
        : esc(a.name || "Unknown");
    }).join(", ");
  }

  /* The head block every detail page opens with. A record without a thumbnail
   * still gets the slot, so its title starts where every other title does. */
  function head(record, extra) {
    var image = record.thumb
      ? '<img src="' + esc(url(record.thumb)) + '" alt="" loading="lazy">'
      : '<div class="headthumb-empty" aria-hidden="true">' +
        esc(record.initial || "?") + "</div>";
    return '<div class="modhead">' + image +
      '<div class="modhead-main">' +
      '<div class="modhead-title"><h1>' + esc(record.name) + "</h1>" +
      mark(record.mark, true) + "</div>" +
      '<div class="bylinerow">' +
      '<div class="byline">by ' + authorLinks(record.authors) + "</div>" +
      '<div class="badges">' + (record.badges || []).map(function (b) {
        return badge(b[0], b[1]);
      }).join("") + "</div></div>" +
      (record.teaser ? '<p class="teaser">' + esc(record.teaser) + "</p>" : "") +
      (extra || "") +
      "</div></div>";
  }

  /* Details and Source side by side. The star count and the download sit in
   * the Source heading because both describe the repository the rows lead
   * with -- which emit.py already picked. */
  function splitcols(record) {
    var stars = record.stars
      ? '<a class="stars" href="' + esc(record.stars.url) + '" target="_blank"' +
        ' rel="noopener noreferrer" title="' + esc(num(record.stars.count)) +
        " stars on " + esc(record.stars.host) + '">★ ' + num(record.stars.count) + "</a>"
      : "";
    var download = record.download
      ? '<a class="sourcedl" href="' + esc(record.download.url) + '" target="_blank"' +
        ' rel="noopener noreferrer" title="' + esc(record.download.title) + '"' +
        ' aria-label="' + esc(record.download.title) + '">' + DOWNLOAD_ICON + "</a>"
      : "";
    /* Where this is listed now. A delisted record has no live page to offer,
     * so it says that instead of linking somewhere that 404s -- the archive
     * holding something the site no longer does is the whole point, not an
     * error to apologise for. */
    var forge = record.delisted
      ? '<p class="forgelink"><span class="label">No longer listed on ' +
        'sp-mod.com — kept from the original Forge archive</span></p>'
      : (record.forge_url
        ? '<p class="forgelink"><a href="' + esc(record.forge_url) + '" target="_blank"' +
          ' rel="noopener noreferrer">View on sp-mod.com</a></p>'
        : "");
    return '<div class="splitcols">' +
      '<section class="panel"><div class="factshead"><h2>Details</h2>' +
      (record.spt ? badge(record.spt, "spt") : "") + "</div>" +
      '<div class="facts">' + facts(record.facts) + "</div></section>" +
      '<section class="panel"><div class="sourcehead"><h2>Source</h2>' +
      stars + download + "</div>" +
      sourceList(record.sources) + forge + "</section></div>";
  }

  /* One version's release text, from each source that has one.
   *
   * The Forge's notes and the repository's are two accounts of the same
   * release that disagree often enough to be worth telling apart, so they get
   * a tab each. The switch is radio inputs and labels rather than script:
   * there are up to forty of these on a page and tabs.js drives a single strip
   * by id, so this has to work on its own. */
  function versionNotes(uid, forgeNotes, repoNotes, hostLabel) {
    if (!forgeNotes && !repoNotes) return "";
    function panel(kind, html) {
      return '<div class="vpanel p-' + kind + '"><div class="notes prose">' +
        html + "</div></div>";
    }
    if (!forgeNotes || !repoNotes) {
      var kind = forgeNotes ? "forge" : "repo";
      var label = forgeNotes ? "The Forge" : hostLabel;
      return '<div class="vsources one"><div class="vtabs">' +
        '<span class="vtab-static">' + esc(label) + "</span></div>" +
        panel(kind, forgeNotes || repoNotes) + "</div>";
    }
    var group = "v" + esc(uid);
    return '<div class="vsources">' +
      '<input class="vin vin-forge" type="radio" name="' + group + '" id="' + group + 'f" checked>' +
      '<input class="vin vin-repo" type="radio" name="' + group + '" id="' + group + 'r">' +
      '<div class="vtabs">' +
      '<label class="vtab lab-forge" for="' + group + 'f">The Forge</label>' +
      '<label class="vtab lab-repo" for="' + group + 'r">' + esc(hostLabel) + "</label>" +
      "</div><div class=\"vpanels\">" +
      panel("forge", forgeNotes) + panel("repo", repoNotes) +
      "</div></div>";
  }

  function versions(blocks, hidden) {
    if (!blocks || !blocks.length) return "";
    var out = blocks.map(function (v) {
      var download = v.download
        ? '<a class="vdl" href="' + esc(v.download) + '" target="_blank"' +
          ' rel="noopener noreferrer" title="Download ' + esc(v.version) +
          ' from the repository" aria-label="Download ' + esc(v.version) + '">' +
          DOWNLOAD_ICON + "</a>"
        : "";
      return '<div class="version"><div class="vhead">' +
        '<span class="num">' + esc(v.version) + "</span>" +
        (v.spt ? badge(v.spt, "spt") : "") +
        (v.fika ? badge(v.fika[0], v.fika[1]) : "") +
        '<span class="when">' + esc(v.date) + " · " + num(v.downloads) +
        " downloads</span>" + download + "</div>" +
        versionNotes(v.id, v.notes || "", v.repo_notes || "", v.repo_label || "Repository") +
        "</div>";
    }).join("");
    return '<div class="versions">' + out + "</div>" +
      (hidden ? '<p class="empty">' + num(hidden) +
        " older versions not shown.</p>" : "");
  }

  /* --- page plumbing ---------------------------------------------------- */

  function getJSON(path) {
    return fetch(url(path), { credentials: "omit" }).then(function (response) {
      if (!response.ok) throw new Error(path + " → HTTP " + response.status);
      return response.json();
    });
  }

  /* Which record this page is. Written into <body data-id> by the build, not
   * read from a query string: each detail page is a real file at its own URL,
   * so the id is a property of the document rather than of how you arrived. */
  function pageId() {
    return document.body.getAttribute("data-id") || "";
  }

  /* The page already carries its real title and description in the HTML, so
   * this is not what makes them correct -- it is what keeps them correct once
   * a record is rendered. Left here because the two must not drift. */
  function setTitle(name, description) {
    document.title = name + " · SPT Mod Archive";
    var meta = document.querySelector('meta[name="description"]');
    if (meta && description) meta.setAttribute("content", description);
  }

  function fail(message) {
    var status = document.getElementById("page-status");
    if (status) {
      status.textContent = message;
      status.classList.add("empty");
    }
    var root = document.getElementById("page");
    if (root) root.removeAttribute("aria-busy");
  }

  /* Load a record, render it, and say something useful when it is not there.
   * A bad `?id=` is a normal way to arrive here -- an old bookmark, a typo, a
   * mod that was in the archive and no longer is -- so it gets a sentence
   * rather than a blank page. */
  function detailPage(path, render, missing) {
    var id = pageId();
    var root = document.getElementById("page");
    if (!id) return fail(missing);
    getJSON(path + encodeURIComponent(id) + ".json").then(function (record) {
      root.innerHTML = render(record);
      root.removeAttribute("aria-busy");
      document.dispatchEvent(new CustomEvent("archive:rendered", {
        detail: { record: record }
      }));
    }).catch(function (error) {
      console.error(error);
      fail(missing);
    });
  }

  /* Only what the page controllers actually call. The rest -- mark(), facts(),
   * sourceList(), versionNotes(), thumb(), authorLinks() -- are the pieces
   * head(), splitcols() and card() are built from, and stay private so there
   * is one way to draw each thing rather than two. */
  window.R = {
    esc: esc, num: num, plural: plural, badge: badge, card: card, cards: cards,
    sectionTabs: sectionTabs, head: head, splitcols: splitcols,
    versions: versions, url: url,
    getJSON: getJSON, setTitle: setTitle, fail: fail, detailPage: detailPage
  };
})();
