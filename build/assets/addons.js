/* The addon catalogue: search, sort, and render tiles as you scroll.
 *
 * A trimmed sibling of index.js rather than a share of it. The two pages look
 * alike, but an addon has no SPT constraint, no category, no Fika status and
 * no repository -- so none of that page's filter machinery, saved facets or
 * share-link state has anything to act on here. Copying the ~150 lines that
 * do apply keeps both files readable; generalising index.js to serve two
 * shapes of record would not.
 */
(function () {
  "use strict";

  var node = document.getElementById("addon-index");
  if (!node) return;
  var ADDONS = JSON.parse(node.textContent);

  var BATCH = 60;

  var DOWNLOAD_ICON =
    '<svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true"' +
    ' fill="currentColor"><path d="M8 1v8.5M8 9.5 4.5 6M8 9.5 11.5 6"' +
    ' stroke="currentColor" stroke-width="1.5" fill="none"' +
    ' stroke-linecap="round" stroke-linejoin="round"/>' +
    '<path d="M2 12.5h12" stroke="currentColor" stroke-width="1.5"' +
    ' stroke-linecap="round"/></svg>';

  var els = {
    search: document.getElementById("q"),
    show: document.getElementById("show"),
    sort: document.getElementById("sort"),
    reset: document.getElementById("reset-filters"),
    list: document.getElementById("addonlist"),
    count: document.getElementById("count"),
    sentinel: document.getElementById("sentinel"),
    scroller: document.getElementById("listscroll")
  };

  var visible = [];
  var rendered = 0;

  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // --- filtering -------------------------------------------------------

  function matchesSearch(addon, terms) {
    for (var i = 0; i < terms.length; i++) {
      if (addon.search.indexOf(terms[i]) === -1) return false;
    }
    return true;
  }

  function applyFilter() {
    var terms = els.search.value.toLowerCase().split(/\s+/).filter(Boolean);
    var show = els.show.value;

    visible = ADDONS.filter(function (addon) {
      if (show === "detached" && !addon.detached) return false;
      return matchesSearch(addon, terms);
    });

    sortVisible(els.sort.value);
    els.count.textContent = "Showing " + visible.length.toLocaleString() +
      (visible.length === 1 ? " addon" : " addons");
    resetList();
  }

  var SORTS = {
    downloads: function (a, b) { return b.downloads - a.downloads; },
    updated: function (a, b) { return cmpText(b.updated, a.updated); },
    published: function (a, b) { return cmpText(b.published, a.published); },
    name: function (a, b) {
      return cmpText(a.name.toLowerCase(), b.name.toLowerCase());
    },
    parent: function (a, b) {
      return cmpText((a.parent_name || "~").toLowerCase(),
                     (b.parent_name || "~").toLowerCase()) ||
        cmpText(a.name.toLowerCase(), b.name.toLowerCase());
    }
  };

  function cmpText(a, b) { return a < b ? -1 : a > b ? 1 : 0; }

  function sortVisible(key) {
    visible.sort(SORTS[key] || SORTS.downloads);
  }

  // --- rendering -------------------------------------------------------

  function badges(addon) {
    var out = "";
    if (addon.mod_constraint) {
      out += '<span class="badge spt">for ' + esc(addon.mod_constraint) +
        "</span>";
    }
    out += '<span class="badge cat">Addon</span>';
    if (addon.detached) {
      out += '<span class="badge bad">Detached ✗</span>';
    }
    if (addon.versions) {
      out += '<span class="badge">' + addon.versions + " version" +
        (addon.versions > 1 ? "s" : "") + "</span>";
    }
    return out;
  }

  // Same rule as the mod index: the author's page, not a search.
  function authorLinks(addon) {
    var links = addon.author_links || [];
    if (!links.length) return esc(addon.authors);
    return links.map(function (author) {
      return '<a class="authorlink" href="user/' + esc(author[2]) +
        '" title="Everything by this author">' + esc(author[1]) + "</a>";
    }).join(", ");
  }

  function markButton(addon) {
    // "a"-prefixed id, and the parent mod so the drawer files it underneath.
    return '<button type="button" class="mark mark-wide" data-mark' +
      ' data-id="a' + esc(addon.id) + '"' +
      ' data-name="' + esc(addon.name) + '"' +
      ' data-href="' + esc(addon.href) + '"' +
      (addon.parent_id ? ' data-parent="' + esc(addon.parent_id) + '"' : "") +
      ' data-sources="' + esc((addon.source_urls || []).join(" ")) + '"' +
      ' aria-pressed="false">' +
      '<span class="mark-label">' +
      '<span class="lbl-state">Add to collection</span>' +
      '<span class="lbl-hover">Remove</span></span></button>';
  }

  function row(addon) {
    var thumb = addon.thumbnail
      ? '<img class="thumb" src="' + esc(addon.thumbnail) +
        '" alt="" loading="lazy">'
      : '<div class="thumb"></div>';

    // The parent mod is the addon's most useful second link: an addon is
    // meaningless without knowing what it extends.
    var parent = addon.parent_href
      ? '<a class="stars" href="' + esc(addon.parent_href) +
        '" title="The mod this addon extends">for ' + esc(addon.parent_name) +
        "</a>"
      : '<span class="stars muted">parent mod not archived</span>';

    return '<article class="mod">' +
      thumb +
      '<div class="modmain"><h2 class="title"><a href="' + esc(addon.href) +
        '">' + esc(addon.name) + "</a></h2>" +
      '<div class="byline">' + authorLinks(addon) + "</div>" +
      (addon.teaser ? '<p class="teaser">' + esc(addon.teaser) + "</p>" : "") +
      "</div>" +
      '<div class="stats"><div class="statnums">' +
      '<span class="dlcount" title="' + esc(addon.downloads.toLocaleString()) +
      ' downloads"><b>' + addon.downloads.toLocaleString() + "</b>" +
      DOWNLOAD_ICON + "</span>" +
      (addon.updated ? "<span>updated " + esc(addon.updated) + "</span>" : "") +
      "</div></div>" +
      '<div class="modfoot">' + parent +
      '<span class="footdivider" aria-hidden="true"></span>' +
      '<div class="badges">' + badges(addon) + "</div>" +
      markButton(addon) + "</div></article>";
  }

  function resetList() {
    els.list.innerHTML = "";
    rendered = 0;
    renderMore();
  }

  function renderMore() {
    if (rendered >= visible.length) return;
    var slice = visible.slice(rendered, rendered + BATCH);
    var html = "";
    for (var i = 0; i < slice.length; i++) html += row(slice[i]);
    els.list.insertAdjacentHTML("beforeend", html);
    rendered += slice.length;
    // Freshly inserted toggles start unmarked; ask the collection to apply
    // the real state, exactly as the mod index does.
    if (window.Collection) window.Collection.syncButtons();
  }

  if (window.IntersectionObserver && els.sentinel) {
    new IntersectionObserver(function (entries) {
      if (entries[0].isIntersecting) renderMore();
    }, { root: els.scroller, rootMargin: "400px" }).observe(els.sentinel);
  } else {
    // Without an observer every tile renders at once, which is slower to
    // paint but never leaves part of the catalogue unreachable.
    BATCH = ADDONS.length;
  }

  // --- URL state -------------------------------------------------------

  function writeUrlState() {
    var params = new URLSearchParams();
    if (els.search.value) params.set("q", els.search.value);
    if (els.show.value) params.set("show", els.show.value);
    if (els.sort.value !== "downloads") params.set("sort", els.sort.value);
    var qs = params.toString();
    history.replaceState(null, "", qs ? "?" + qs : location.pathname);
  }

  function restoreFilters() {
    var params = new URLSearchParams(location.search);
    if (params.get("q")) els.search.value = params.get("q");
    if (params.get("show")) els.show.value = params.get("show");
    if (params.get("sort")) els.sort.value = params.get("sort");
  }

  function onChange() {
    applyFilter();
    writeUrlState();
  }

  els.search.addEventListener("input", onChange);
  els.show.addEventListener("change", onChange);
  els.sort.addEventListener("change", onChange);
  els.reset.addEventListener("click", function () {
    els.search.value = "";
    els.show.value = "";
    els.sort.value = "downloads";
    onChange();
  });

  restoreFilters();
  applyFilter();
})();
