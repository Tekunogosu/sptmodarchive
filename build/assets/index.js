/* Index page: filter, sort, and render the mod list.
 *
 * The whole catalogue is embedded in the page as JSON, so everything here is
 * synchronous and works from file:// with no server and no network. The only
 * concession to size is that rows are rendered in batches as you scroll --
 * building ~1,800 rows plus thumbnails up front is what makes a page like
 * this feel slow.
 */
(function () {
  "use strict";

  var MODS = JSON.parse(document.getElementById("mod-index").textContent);
  // The importer in collection.js needs this to turn shared ids into names.
  window.MOD_INDEX = MODS;

  var BY_ID = {};
  MODS.forEach(function (mod) { BY_ID[mod.id] = mod; });

  // A simple branch mark, drawn here rather than pulled from anywhere: it
  // reads as "source repository" and suits GitLab and Codeberg links too.
  var REPO_ICON =
    '<svg class="repo-icon" viewBox="0 0 16 16" width="11" height="11"' +
    ' aria-hidden="true" focusable="false">' +
    '<circle cx="4" cy="3.2" r="1.7"/><circle cx="4" cy="12.8" r="1.7"/>' +
    '<circle cx="12" cy="5.6" r="1.7"/>' +
    '<path d="M4 4.9v6" stroke="currentColor" stroke-width="1.4" fill="none"/>' +
    '<path d="M12 7.3c0 2.5-2.4 3.2-5.2 3.5" stroke="currentColor"' +
    ' stroke-width="1.4" fill="none"/></svg>';

  function hostName(host) {
    if (host.indexOf("github") !== -1) return "GitHub";
    if (host.indexOf("gitlab") !== -1) return "GitLab";
    if (host.indexOf("codeberg") !== -1) return "Codeberg";
    return host || "the source repository";
  }
  var BATCH = 60;

  var els = {
    search: document.getElementById("q"),
    category: document.getElementById("category"),
    spt: document.getElementById("spt"),
    fika: document.getElementById("fika"),
    show: document.getElementById("show"),
    sort: document.getElementById("sort"),
    list: document.getElementById("modlist"),
    count: document.getElementById("count"),
    copy: document.getElementById("copy-sources"),
    sentinel: document.getElementById("sentinel"),
    scroller: document.getElementById("listscroll")
  };

  var visible = [];      // current filtered+sorted set
  var rendered = 0;

  // --- filtering -------------------------------------------------------

  function matchesSearch(mod, terms) {
    if (!terms.length) return true;
    var hay = mod.search;
    for (var i = 0; i < terms.length; i++) {
      if (hay.indexOf(terms[i]) === -1) return false;
    }
    return true;
  }

  function currentFilter() {
    return {
      terms: els.search.value.toLowerCase().split(/\s+/).filter(Boolean),
      category: els.category.value,
      spt: els.spt.value,
      fika: els.fika.value,
      show: els.show.value
    };
  }

  function applyFilter() {
    var f = currentFilter();

    visible = MODS.filter(function (mod) {
      if (f.category && mod.category !== f.category) return false;
      if (f.spt && mod.spt_lines.indexOf(f.spt) === -1) return false;
      if (f.fika === "yes" && !mod.fika) return false;
      if (f.fika === "no" && mod.fika) return false;
      if (f.show === "deps" && !mod.dep_count) return false;
      if (f.show === "comments" && !mod.comments) return false;
      if (f.show === "nosource" && mod.sources) return false;
      if (f.show === "collection" && !inCollection(mod)) return false;
      return matchesSearch(mod, f.terms);
    });

    sortVisible(els.sort.value);
    resetList();
    updateCount();
    if (els.scroller) els.scroller.scrollTop = 0;
  }

  // --- sorting ---------------------------------------------------------

  var SORTS = {
    downloads: function (a, b) { return b.downloads - a.downloads; },
    updated: function (a, b) { return cmpText(b.updated, a.updated); },
    published: function (a, b) { return cmpText(b.published, a.published); },
    name: function (a, b) { return cmpText(a.name.toLowerCase(), b.name.toLowerCase()); },
    comments: function (a, b) { return b.comments - a.comments; },
    // Fika-compatible mods first, most downloaded within each group, so the
    // sort answers "what can I actually run in co-op" rather than shuffling.
    fika: function (a, b) {
      if (a.fika !== b.fika) return a.fika ? -1 : 1;
      return b.downloads - a.downloads;
    },
    stars: function (a, b) { return b.stars - a.stars || b.downloads - a.downloads; },
    collection: function (a, b) {
      var x = inCollection(a), y = inCollection(b);
      if (x !== y) return x ? -1 : 1;
      return b.downloads - a.downloads;
    }
  };

  function cmpText(a, b) { return a < b ? -1 : a > b ? 1 : 0; }

  function inCollection(mod) {
    return window.Collection ? window.Collection.has(mod.id) : false;
  }

  function sortVisible(key) {
    visible.sort(SORTS[key] || SORTS.downloads);
  }

  // --- rendering -------------------------------------------------------

  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  // Badges double as filter shortcuts: clicking one narrows the list to it.
  function tagBadge(control, value, kind, text) {
    if (!value) return '<span class="badge ' + kind + '">' + esc(text) + "</span>";
    return '<button type="button" class="badge ' + kind + ' tagfilter"' +
      ' data-control="' + esc(control) + '" data-value="' + esc(value) + '"' +
      ' title="Filter by this">' + esc(text) + "</button>";
  }

  function badges(mod) {
    var out = "";
    if (mod.fika) {
      out += tagBadge("fika", "yes", "fika", "Fika ✓");
    }
    if (mod.category_title) {
      out += tagBadge("category", mod.category, "cat", mod.category_title);
    }
    if (mod.spt_latest) {
      var line = mod.spt_lines[mod.spt_lines.length - 1] || "";
      out += tagBadge("spt", line, "spt", "SPT " + mod.spt_latest);
    }
    if (mod.dep_count) {
      out += '<span class="badge">' + mod.dep_count + " dep" +
        (mod.dep_count > 1 ? "s" : "") + "</span>";
    }
    if (mod.origin === "community") {
      out += '<span class="badge community">Community</span>';
    }
    if (!mod.sources) out += '<span class="badge warn">No source</span>';
    return out;
  }

  function depsAttr(mod) {
    var deps = (mod.deps || []).map(function (id) {
      var dep = BY_ID[id];
      return dep && { id: dep.id, name: dep.name, href: dep.href,
                      sources: dep.source_urls || [] };
    }).filter(Boolean);
    return deps.length ? ' data-deps="' + esc(JSON.stringify(deps)) + '"' : "";
  }

  function row(mod) {
    var thumb = mod.thumbnail
      ? '<img class="thumb" src="' + esc(mod.thumbnail) + '" alt="" loading="lazy">'
      : '<div class="thumb"></div>';

    // Labelled rather than a bare "+": on a tile full of numbers, an unlabelled
    // icon reads as decoration and nobody discovers what it does.
    var mark = '<button type="button" class="mark mark-wide" data-mark' +
      ' data-id="' + esc(mod.id) + '"' +
      ' data-name="' + esc(mod.name) + '"' +
      ' data-href="' + esc(mod.href) + '"' +
      ' data-sources="' + esc((mod.source_urls || []).join(" ")) + '"' +
      depsAttr(mod) +
      ' aria-pressed="false">' +
      '<span class="mark-label">Add to collection</span></button>';

    var count = (mod.stars || 0).toLocaleString();
    var stars = mod.repo_url
      ? '<a class="stars" href="' + esc(mod.repo_url) + '" target="_blank"' +
        ' rel="noopener noreferrer" title="' + count +
        " stars — view on " + esc(hostName(mod.repo_host || "")) + '">' +
        REPO_ICON + "★ " + count + "</a>"
      : '<span class="stars muted">' + REPO_ICON + "★ " + count + "</span>";

    return '<article class="mod">' +
      thumb +
      '<div class="modmain"><h2 class="title"><a href="' + esc(mod.href) + '">' +
        esc(mod.name) + "</a></h2>" +
      '<div class="byline">' + esc(mod.authors) + "</div>" +
      (mod.teaser ? '<p class="teaser">' + esc(mod.teaser) + "</p>" : "") +
      '<div class="badges">' + badges(mod) + "</div></div>" +
      '<div class="stats">' +
      '<div class="statnums"><b>' + mod.downloads.toLocaleString() + "</b>downloads" +
      (mod.comments ? "<br>" + mod.comments + " comments" : "") + "</div>" +
      mark + stars +
      "</div></article>";
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
    if (window.Collection) window.Collection.syncButtons();
  }

  function updateCount() {
    var n = visible.length;
    var fika = 0;
    for (var i = 0; i < visible.length; i++) if (visible[i].fika) fika++;
    els.count.textContent = n.toLocaleString() + " of " +
      MODS.length.toLocaleString() + " mods · " + fika.toLocaleString() +
      " Fika-compatible";
  }

  // --- copy source URLs ------------------------------------------------

  function copySources() {
    var urls = [];
    for (var i = 0; i < visible.length; i++) {
      if (visible[i].source_urls) {
        urls = urls.concat(visible[i].source_urls);
      }
    }
    var text = urls.join("\n");
    var done = function () {
      els.copy.textContent = urls.length + " URLs copied";
      setTimeout(function () { els.copy.textContent = "Copy source URLs"; }, 2000);
    };

    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(done, fallbackCopy.bind(null, text, done));
    } else {
      fallbackCopy(text, done);
    }
  }

  function fallbackCopy(text, done) {
    // file:// and plain http have no clipboard API, which is exactly where
    // an offline archive gets used.
    var area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    try { document.execCommand("copy"); done(); } catch (e) { /* nothing to do */ }
    document.body.removeChild(area);
  }

  // --- URL state -------------------------------------------------------

  function readUrlState() {
    var params = new URLSearchParams(location.search);
    if (params.get("q")) els.search.value = params.get("q");
    if (params.get("category")) els.category.value = params.get("category");
    if (params.get("spt")) els.spt.value = params.get("spt");
    if (params.get("fika")) els.fika.value = params.get("fika");
    if (params.get("show")) els.show.value = params.get("show");
    if (params.get("sort")) els.sort.value = params.get("sort");
  }

  function writeUrlState() {
    var params = new URLSearchParams();
    if (els.search.value) params.set("q", els.search.value);
    if (els.category.value) params.set("category", els.category.value);
    if (els.spt.value) params.set("spt", els.spt.value);
    if (els.fika.value) params.set("fika", els.fika.value);
    if (els.show.value) params.set("show", els.show.value);
    if (els.sort.value !== "downloads") params.set("sort", els.sort.value);
    var qs = params.toString();
    history.replaceState(null, "", qs ? "?" + qs : location.pathname);
  }

  // --- wiring ----------------------------------------------------------

  function onChange() {
    applyFilter();
    writeUrlState();
  }

  var debounce;
  els.search.addEventListener("input", function () {
    clearTimeout(debounce);
    debounce = setTimeout(onChange, 120);
  });
  [els.category, els.spt, els.fika, els.show, els.sort].forEach(function (el) {
    el.addEventListener("change", onChange);
  });
  els.copy.addEventListener("click", copySources);

  els.list.addEventListener("click", function (event) {
    var tag = event.target.closest(".tagfilter");
    if (!tag) return;
    var control = els[tag.getAttribute("data-control")];
    if (!control) return;
    control.value = tag.getAttribute("data-value");
    onChange();

  });

  if (window.IntersectionObserver) {
    new IntersectionObserver(function (entries) {
      if (entries[0].isIntersecting) renderMore();
    }, { root: els.scroller, rootMargin: "600px" }).observe(els.sentinel);
  } else {
    els.scroller.addEventListener("scroll", function () {
      if (els.scroller.scrollTop + els.scroller.clientHeight >=
          els.scroller.scrollHeight - 600) renderMore();
    });
  }

  if (window.Collection) {
    window.Collection.onChange(function () {
      // Re-filter only when membership is what the list is showing;
      // otherwise just let the button states update in place.
      if (els.show.value === "collection" || els.sort.value === "collection") {
        applyFilter();
      }
    });
  }

  readUrlState();
  applyFilter();
})();
