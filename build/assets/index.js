/* Index page: filter, sort, and render the mod list.
 *
 * The catalogue arrives as data/index.json -- about 1.6 MB, and the reason
 * index.html is 8 KB rather than the 1.7 MB it used to be. Everything after
 * that first fetch is synchronous, and rows are still rendered in batches as
 * you scroll, because building ~1,800 rows plus thumbnails up front is what
 * makes a page like this feel slow.
 *
 * The filter controls are built here too. They used to be baked into the HTML
 * by the build, which meant every category and SPT version was a reason to
 * re-render the page; now they come from data/facets.json alongside the
 * catalogue itself.
 */
(function () {
  "use strict";

  var MODS = [];
  var BY_ID = {};

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

  // Same glyph as the collection drawer's download link, so the shape means
  // the same thing wherever it appears. Sized to the download number it sits
  // beside (.dlcount b, 14px), so the pair reads as one figure.
  var DOWNLOAD_ICON =
    '<svg class="dlicon" viewBox="0 0 16 16" width="14" height="14"'
    + ' aria-hidden="true" focusable="false" fill="none" stroke="currentColor"'
    + ' stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
    + '<path d="M8 2v7.5"/><path d="M4.75 6.5 8 9.75l3.25-3.25"/>'
    + '<path d="M3 12.75h10"/></svg>';

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
    sptPanel: document.getElementById("spt-panel"),
    sptSummary: document.getElementById("spt-summary"),
    reset: document.getElementById("reset-filters"),
    fika: document.getElementById("fika"),
    show: document.getElementById("show"),
    sort: document.getElementById("sort"),
    list: document.getElementById("modlist"),
    count: document.getElementById("count"),
    fikaCount: document.getElementById("fika-count"),
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
      spt: checkedVersions(),
      fika: els.fika.value,
      show: els.show.value
    };
  }

  function applyFilter() {
    var f = currentFilter();

    visible = MODS.filter(function (mod) {
      if (f.category && mod.category !== f.category) return false;
      if (f.spt.length && !mod.spt.some(inSet(f.spt))) return false;
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

  function inSet(list) {
    var set = {};
    list.forEach(function (v) { set[v] = true; });
    return function (v) { return set[v] === true; };
  }

  // --- SPT version checkboxes ------------------------------------------

  var FILTER_KEY = "spt-archive-filters";

  function sptBoxes() {
    return Array.prototype.slice.call(
      els.sptPanel.querySelectorAll('input[name="sptv"]'));
  }

  function checkedVersions() {
    return sptBoxes().filter(function (b) { return b.checked; })
                     .map(function (b) { return b.value; });
  }

  function setVersions(list) {
    var wanted = inSet(list);
    sptBoxes().forEach(function (b) { b.checked = wanted(b.value); });
    updateSptSummary();
  }

  function majorBoxes() {
    return Array.prototype.slice.call(
      els.sptPanel.querySelectorAll('input[name="sptmajor"]'));
  }

  function boxesFor(major) {
    return sptBoxes().filter(function (b) {
      return b.value.split(".")[0] === major;
    });
  }

  /* The group headers are the friendly path: one click takes a whole
   * generation. They reflect their children rather than being a separate
   * filter, so "Any 4.x" is indeterminate when only some 4.x are picked. */
  function syncMajorBoxes() {
    majorBoxes().forEach(function (box) {
      var kids = boxesFor(box.value);
      var on = kids.filter(function (b) { return b.checked; }).length;
      box.checked = on === kids.length && kids.length > 0;
      box.indeterminate = on > 0 && on < kids.length;
    });
  }

  /* Default to the current generation: 4.x is what almost everyone is playing,
   * and showing every SPT version ever released buries it. */
  function defaultVersions() {
    return sptBoxes().filter(function (b) { return b.value.indexOf("4") === 0; })
                     .map(function (b) { return b.value; });
  }

  function updateSptSummary() {
    var picked = checkedVersions();
    var total = sptBoxes().length;
    var text;
    if (!picked.length || picked.length === total) {
      text = "Any SPT version";
    } else if (picked.length <= 3) {
      text = "SPT " + picked.join(", ");
    } else {
      var majors = {};
      picked.forEach(function (v) { majors[v.split(".")[0]] = true; });
      text = "SPT " + Object.keys(majors).sort().reverse().join(", ") +
        ".x (" + picked.length + ")";
    }
    els.sptSummary.textContent = text;
    syncMajorBoxes();
  }

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

  // Order is fixed and matches every other badge row in the archive: the two
  // questions that decide whether a mod is usable at all -- which SPT, and
  // whether it survives Fika -- come first, in that order, so the eye finds
  // them in the same place on every tile. Description and warnings follow.
  function badges(mod) {
    var out = "";
    if (mod.spt_latest) {
      out += tagBadge("spt", mod.spt_latest, "spt", "SPT " + mod.spt_latest);
    }
    if (mod.fika) {
      out += tagBadge("fika", "yes", "fika", "Fika ✓");
    }
    if (mod.category_title) {
      out += tagBadge("category", mod.category, "cat", mod.category_title);
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

  // Authors reuse the badge click handler: the search box already matches on
  // author name, so filtering by one is just a pre-filled search.
  /* Links to the author's own page, not a pre-filled search. Filling the
   * search box left every other filter standing, so clicking someone whose
   * work is all 3.x returned an empty list under the default 4.x filter and
   * read as a broken link. Authors the archive has no id for stay plain text
   * -- there is no page to send them to. */
  function authorLinks(mod) {
    var links = mod.author_links || [];
    if (!links.length) return esc(mod.authors);
    return links.map(function (author) {
      // author[2] is already the root-relative "user/<slug>.html" that
      // build.user_url() produced -- the same convention every other href on
      // this page follows. Prefixing "user/" here made it user/user/….
      return '<a class="authorlink" href="' + esc(author[2]) +
        '" title="Everything by this author">' + esc(author[1]) + "</a>";
    }).join(", ");
  }

  /* Version and release date, from the newest version's publish date. The
   * Forge's own "updated" field is a database timestamp -- bulk migrations set
   * it on thousands of mods at once -- so it is not what gets shown here. */
  function releaseLine(mod) {
    var bits = [];
    if (mod.version) bits.push("v" + esc(mod.version));
    if (mod.updated) bits.push(esc(mod.updated));
    return bits.length
      ? '<span class="release">' + bits.join(" · ") + "</span>"
      : "";
  }

  function row(mod) {
    // The initial stands in for a missing image, matching the mod page. An
    // empty square reads as an image that failed to load; a letter does not.
    var thumb = mod.thumbnail
      ? '<img class="thumb" src="' + esc(mod.thumbnail) + '" alt="" loading="lazy">'
      : '<div class="thumb thumb-empty" aria-hidden="true">' +
        esc((mod.name || "?").charAt(0).toUpperCase()) + "</div>";

    // Labelled rather than a bare "+": on a tile full of numbers, an unlabelled
    // icon reads as decoration and nobody discovers what it does.
    var mark = '<button type="button" class="mark mark-wide" data-mark' +
      ' data-id="' + esc(mod.id) + '"' +
      ' data-name="' + esc(mod.name) + '"' +
      ' data-href="' + esc(mod.href) + '"' +
      ' data-sources="' + esc((mod.source_urls || []).join(" ")) + '"' +
      depsAttr(mod) +
      ' aria-pressed="false">' +
      '<span class="mark-label">' +
      '<span class="lbl-state">Add to collection</span>' +
      '<span class="lbl-hover">Remove</span></span></button>';

    var count = (mod.stars || 0).toLocaleString();
    var stars = mod.repo_url
      ? '<a class="stars" href="' + esc(mod.repo_url) + '" target="_blank"' +
        ' rel="noopener noreferrer" title="' + count +
        " stars — view on " + esc(hostName(mod.repo_host || "")) + '">' +
        REPO_ICON + "★ " + count + "</a>"
      : '<span class="stars muted">' + REPO_ICON + "★ " + count + "</span>";

    // The id is on the tile itself, not just on its collection button: coming
    // back from a mod page has to find the row again to mark it.
    return '<article class="mod" data-id="' + esc(mod.id) + '">' +
      thumb +
      '<div class="modmain"><h2 class="title"><a href="' + esc(mod.href) + '">' +
        esc(mod.name) + "</a></h2>" +
      '<div class="byline">' + authorLinks(mod) + "</div>" +
      (mod.teaser ? '<p class="teaser">' + esc(mod.teaser) + "</p>" : "") +
      "</div>" +
      '<div class="stats">' +
      '<div class="statnums">' +
      '<span class="dlcount" title="' + esc(mod.downloads.toLocaleString()) +
      ' downloads"><b>' + mod.downloads.toLocaleString() + "</b>" +
      DOWNLOAD_ICON + "</span>" +
      (mod.comments ? '<span>' + mod.comments + " comments</span>" : "") +
      releaseLine(mod) +
      "</div>" +
      "</div>" +
      '<div class="modfoot">' + stars +
      (stars ? '<span class="footdivider" aria-hidden="true"></span>' : "") +
      '<div class="badges">' + badges(mod) + "</div>" +
      mark + "</div></article>";
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
    var fika = 0;
    for (var i = 0; i < visible.length; i++) if (visible[i].fika) fika++;
    els.count.innerHTML = 'Showing <span class="num">' +
      visible.length.toLocaleString() + "</span> " +
      (visible.length === 1 ? "mod" : "mods");
    els.fikaCount.textContent = fika
      ? fika.toLocaleString() + " Fika compatible"
      : "";
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

  // --- where you were --------------------------------------------------

  /* Opening a mod and coming back should land you where you left, not at the
   * top of a list you had scrolled a thousand rows into. The filters already
   * survive the trip (localStorage, below); the position in the list did not.
   *
   * sessionStorage rather than localStorage because this is about one journey
   * out and back, not a preference: a tab opened tomorrow should start at the
   * top. The saved position carries the filter signature it was taken under,
   * so it is discarded the moment it would point somewhere else -- a different
   * search, sort or SPT set is a different list, and row 900 of it is not the
   * row you were looking at.
   *
   * `rendered` is saved alongside the offset because rows arrive in batches:
   * the scroll container is only as tall as what has been rendered, so the
   * batches have to be replayed before the offset means anything.
   */
  var RETURN_KEY = "spt-archive-return";

  /* The tile you left through, remembered so it can be marked on the way back.
   * Only the title link counts: an author link or a badge filter also leaves
   * the tile, but neither means "I went and read this one". */
  var opened = null;

  els.list.addEventListener("click", function (event) {
    var link = event.target.closest(".title a");
    var article = link && link.closest("article.mod");
    if (article) opened = article.getAttribute("data-id");
  });

  function filterSignature() {
    var f = currentFilter();
    return [f.terms.join(" "), f.category, f.spt.join(","), f.fika, f.show,
            els.sort.value].join("|");
  }

  function saveReturnPosition() {
    if (!els.scroller || (!els.scroller.scrollTop && !opened)) return;
    try {
      sessionStorage.setItem(RETURN_KEY, JSON.stringify({
        top: els.scroller.scrollTop,
        rendered: rendered,
        opened: opened,
        sig: filterSignature()
      }));
    } catch (e) { /* storage unavailable: you just land at the top */ }
  }

  function takeReturnPosition() {
    var saved;
    try {
      saved = JSON.parse(sessionStorage.getItem(RETURN_KEY) || "null");
      sessionStorage.removeItem(RETURN_KEY);
    } catch (e) { return null; }
    if (!saved || saved.sig !== filterSignature()) return null;
    return saved;
  }

  /* Read once on arrival and consumed there: a position that has been used is
   * spent, so scrolling back to the top and reloading does not drag you back
   * down again. */
  function restoreReturnPosition() {
    var saved = takeReturnPosition();
    if (!saved) return;
    while (rendered < saved.rendered && rendered < visible.length) renderMore();
    els.scroller.scrollTop = saved.top;
    // Thumbnails and badges settle a frame later, which can shorten the
    // container just after the offset is set. One correction is enough.
    requestAnimationFrame(function () { els.scroller.scrollTop = saved.top; });
    // Carried forward as well as drawn, so a second trip out that opens
    // nothing -- following the addons link, say -- still comes back to the
    // last mod actually read rather than to an unmarked list.
    opened = saved.opened || null;
    markOpened(opened);
  }

  /* The tile you last opened, marked where it sits. Deliberately quiet: this
   * is a place-keeper for the eye while you work down a list, not a status,
   * and it has to survive sitting next to badges that do mean something. */
  function markOpened(id) {
    if (!id) return;
    // Ids are numbers today, but community records may not be, and an id is
    // pasted into a selector here.
    var safe = window.CSS && CSS.escape ? CSS.escape(id) : id;
    var tile = els.list.querySelector('article.mod[data-id="' + safe + '"]');
    if (tile) tile.classList.add("lastopened");
  }

  window.addEventListener("pagehide", saveReturnPosition);

  // --- URL state -------------------------------------------------------

  function writeUrlState() {
    var params = new URLSearchParams();
    if (els.search.value) params.set("q", els.search.value);
    if (els.category.value) params.set("category", els.category.value);
    var spt = checkedVersions();
    if (spt.length && spt.length !== sptBoxes().length) {
      params.set("spt", spt.join(","));
    }
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
    saveFilters();
  }

  function saveFilters() {
    try {
      localStorage.setItem(FILTER_KEY, JSON.stringify({
        q: els.search.value, category: els.category.value,
        fika: els.fika.value, show: els.show.value, sort: els.sort.value,
        spt: checkedVersions()
      }));
    } catch (e) { /* storage unavailable: filters just will not persist */ }
  }

  /* Priority: an explicit URL wins, then whatever the reader last used, then
   * the 4.x default. A shared link must show what the sender saw. */
  function restoreFilters() {
    var params = new URLSearchParams(location.search);
    var saved = {};
    try { saved = JSON.parse(localStorage.getItem(FILTER_KEY) || "{}") || {}; }
    catch (e) { saved = {}; }

    els.search.value = params.get("q") || saved.q || "";
    els.category.value = params.get("category") || saved.category || "";
    els.fika.value = params.get("fika") || saved.fika || "";
    els.show.value = params.get("show") || saved.show || "";
    els.sort.value = params.get("sort") || saved.sort || "downloads";

    var spt = params.get("spt") ? params.get("spt").split(",")
            : Array.isArray(saved.spt) ? saved.spt
            : defaultVersions();
    setVersions(spt);
  }

  var debounce;
  els.search.addEventListener("input", function () {
    clearTimeout(debounce);
    debounce = setTimeout(onChange, 120);
  });
  [els.category, els.fika, els.show, els.sort].forEach(function (el) {
    el.addEventListener("change", onChange);
  });
  els.sptSummary.addEventListener("click", function () {
    var open = els.sptPanel.hasAttribute("hidden");
    els.sptPanel.toggleAttribute("hidden", !open);
    els.sptSummary.setAttribute("aria-expanded", open ? "true" : "false");
  });

  document.addEventListener("click", function (event) {
    if (!els.sptPanel.hasAttribute("hidden") &&
        !event.target.closest("#sptfilter")) {
      els.sptPanel.setAttribute("hidden", "");
      els.sptSummary.setAttribute("aria-expanded", "false");
    }
  });

  els.sptPanel.addEventListener("change", function (event) {
    if (event.target.name === "sptmajor") {
      var on = event.target.checked;
      boxesFor(event.target.value).forEach(function (b) { b.checked = on; });
    } else if (event.target.name !== "sptv") {
      return;
    }
    updateSptSummary();
    onChange();
  });

  els.sptPanel.addEventListener("click", function (event) {
    var action = event.target.closest("[data-spt]");
    if (!action) return;
    var which = action.getAttribute("data-spt");
    setVersions(which === "all" ? sptBoxes().map(function (b) { return b.value; })
              : which === "none" ? []
              : defaultVersions());
    onChange();
  });

  els.reset.addEventListener("click", function () {
    els.search.value = "";
    els.category.value = "";
    els.fika.value = "";
    els.show.value = "";
    els.sort.value = "downloads";
    setVersions(defaultVersions());
    try { localStorage.removeItem(FILTER_KEY); } catch (e) { /* no-op */ }
    onChange();
  });

  els.copy.addEventListener("click", copySources);

  els.list.addEventListener("click", function (event) {
    var tag = event.target.closest(".tagfilter");
    if (!tag) return;
    var name = tag.getAttribute("data-control");
    var value = tag.getAttribute("data-value");
    if (name === "spt") {
      setVersions([value]);
    } else {
      var control = els[name];
      if (!control) return;
      control.value = value;
    }
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

  /* The filter panel, built from the facet counts rather than baked into the
   * HTML. Has to happen before restoreFilters(), which sets checkboxes that
   * do not exist until now. */
  function buildFacets(facets) {
    els.category.insertAdjacentHTML("beforeend", facets.categories.map(function (c) {
      return '<option value="' + esc(c.slug) + '">' + esc(c.title) +
        " (" + c.count + ")</option>";
    }).join(""));

    document.getElementById("spt-groups").innerHTML =
      facets.spt.map(function (group) {
        var versions = group.versions.map(function (v) {
          return '<label><input type="checkbox" name="sptv" value="' + esc(v[0]) +
            '"><span>' + esc(v[0]) + '</span><span class="n">' +
            v[1].toLocaleString("en-US") + "</span></label>";
        }).join("");
        return '<details class="sptgroup"' + (group.major === "4" ? " open" : "") +
          '><summary><label class="anymajor"><input type="checkbox" name="sptmajor"' +
          ' value="' + esc(group.major) + '"> Any ' + esc(group.major) +
          '.x</label><span class="tabcount">' + group.count.toLocaleString("en-US") +
          "</span></summary>" +
          '<div class="sptversions">' + versions + "</div></details>";
      }).join("");
  }

  function esc(value) {
    return String(value === null || value === undefined ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#x27;");
  }

  Promise.all([
    window.R.getJSON("data/index.json"),
    window.R.getJSON("data/facets.json"),
    // A share link may carry addons, and this is the only page that can name
    // them. Missing is survivable -- an archive with no addons never emits it
    // -- so it resolves to an empty list rather than failing the whole load.
    window.R.getJSON("data/addon-lookup.json").catch(function () { return []; })
  ]).then(function (loaded) {
    MODS = loaded[0];
    // The importer in collection.js needs these to turn shared ids into names.
    window.MOD_INDEX = MODS;
    window.ADDON_LOOKUP = loaded[2];
    MODS.forEach(function (mod) { BY_ID[mod.id] = mod; });

    buildFacets(loaded[1]);
    restoreFilters();
    applyFilter();
    restoreReturnPosition();
    document.dispatchEvent(new CustomEvent("archive:catalogue"));
  }).catch(function (error) {
    console.error(error);
    els.count.textContent = "The catalogue could not be loaded. " +
      "If you are opening this from a folder rather than a web server, " +
      "see the README — it needs to be served over HTTP.";
  });
})();
