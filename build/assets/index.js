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
  var BATCH = 60;

  var els = {
    search: document.getElementById("q"),
    category: document.getElementById("category"),
    spt: document.getElementById("spt"),
    show: document.getElementById("show"),
    sort: document.getElementById("sort"),
    list: document.getElementById("modlist"),
    count: document.getElementById("count"),
    copy: document.getElementById("copy-sources"),
    sentinel: document.getElementById("sentinel")
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
      show: els.show.value
    };
  }

  function applyFilter() {
    var f = currentFilter();

    visible = MODS.filter(function (mod) {
      if (f.category && mod.category !== f.category) return false;
      if (f.spt && mod.spt_lines.indexOf(f.spt) === -1) return false;
      if (f.show === "fika" && !mod.fika) return false;
      if (f.show === "nofika" && mod.fika) return false;
      if (f.show === "deps" && !mod.dep_count) return false;
      if (f.show === "comments" && !mod.comments) return false;
      if (f.show === "nosource" && mod.sources) return false;
      return matchesSearch(mod, f.terms);
    });

    sortVisible(els.sort.value);
    resetList();
    updateCount();
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
    }
  };

  function cmpText(a, b) { return a < b ? -1 : a > b ? 1 : 0; }

  function sortVisible(key) {
    visible.sort(SORTS[key] || SORTS.downloads);
  }

  // --- rendering -------------------------------------------------------

  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function badges(mod) {
    var out = "";
    if (mod.fika) out += '<span class="badge fika">Fika ✓</span>';
    if (mod.category_title) {
      out += '<span class="badge cat">' + esc(mod.category_title) + "</span>";
    }
    if (mod.spt_latest) {
      out += '<span class="badge spt">SPT ' + esc(mod.spt_latest) + "</span>";
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

  function row(mod) {
    var thumb = mod.thumbnail
      ? '<img class="thumb" src="' + esc(mod.thumbnail) + '" alt="" loading="lazy">'
      : '<div class="thumb"></div>';

    return '<article class="mod">' +
      thumb +
      '<div><h2 class="title"><a href="' + esc(mod.href) + '">' +
        esc(mod.name) + "</a></h2>" +
      '<div class="byline">' + esc(mod.authors) + "</div>" +
      (mod.teaser ? '<p class="teaser">' + esc(mod.teaser) + "</p>" : "") +
      '<div class="badges">' + badges(mod) + "</div></div>" +
      '<div class="stats"><b>' + mod.downloads.toLocaleString() + "</b>downloads" +
      (mod.comments ? "<br>" + mod.comments + " comments" : "") +
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
    if (params.get("show")) els.show.value = params.get("show");
    if (params.get("sort")) els.sort.value = params.get("sort");
  }

  function writeUrlState() {
    var params = new URLSearchParams();
    if (els.search.value) params.set("q", els.search.value);
    if (els.category.value) params.set("category", els.category.value);
    if (els.spt.value) params.set("spt", els.spt.value);
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
  [els.category, els.spt, els.show, els.sort].forEach(function (el) {
    el.addEventListener("change", onChange);
  });
  els.copy.addEventListener("click", copySources);

  if (window.IntersectionObserver) {
    new IntersectionObserver(function (entries) {
      if (entries[0].isIntersecting) renderMore();
    }, { rootMargin: "600px" }).observe(els.sentinel);
  } else {
    window.addEventListener("scroll", function () {
      if (window.innerHeight + window.scrollY >=
          document.body.offsetHeight - 600) renderMore();
    });
  }

  readUrlState();
  applyFilter();
})();
