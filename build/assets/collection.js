/* Collections: mark mods, keep them in the browser, share them as a URL.
 *
 * There is no account and no server. A collection is a list of mod ids in
 * localStorage, and a share link is that same list encoded into the URL. The
 * consequences are worth stating plainly, because they are the design:
 *
 *   - clearing site data clears the collection; a share link is the backup
 *   - file:// and the published site are different origins, so they do not
 *     share a collection
 *   - nothing is transmitted anywhere unless you copy a share link yourself
 *
 * Entries store the mod's name, link, and source URLs alongside its id, so the
 * flyout works on a mod page without loading the 1.3 MB catalogue. Share links
 * carry only ids -- names are resolved on the index, which has the data.
 *
 * Ids are encoded, never list positions: positions shift whenever the
 * catalogue changes and would silently corrupt every link ever shared.
 */
(function () {
  "use strict";

  var STORE_KEY = "spt-archive-collection";
  var OPEN_KEY = "spt-archive-collection-open";
  var VERSION = "1";

  // Path back to the site root, so links work from any directory depth.
  var UP = document.documentElement.getAttribute("data-up") || "";

  // --- storage ---------------------------------------------------------

  var entries = load();
  var listeners = [];

  function load() {
    try {
      var raw = localStorage.getItem(STORE_KEY);
      var parsed = raw ? JSON.parse(raw) : [];
      return Array.isArray(parsed) ? parsed.filter(valid) : [];
    } catch (e) {
      return [];      // corrupt or unavailable storage is an empty collection
    }
  }

  function valid(entry) {
    return entry && (typeof entry.id === "number" || typeof entry.id === "string");
  }

  function save() {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify(entries));
    } catch (e) {
      // Quota or private-mode failure: the collection still works for this
      // page view, it just will not survive a reload. Not worth interrupting.
    }
    listeners.forEach(function (fn) { fn(); });
  }

  function indexOf(id) {
    for (var i = 0; i < entries.length; i++) {
      if (String(entries[i].id) === String(id)) return i;
    }
    return -1;
  }

  // --- varint / base64url ----------------------------------------------

  function writeVarint(bytes, n) {
    while (n > 0x7f) {
      bytes.push((n & 0x7f) | 0x80);
      n = Math.floor(n / 128);
    }
    bytes.push(n);
  }

  function readVarints(bytes) {
    var out = [], shift = 0, value = 0;
    for (var i = 0; i < bytes.length; i++) {
      value += (bytes[i] & 0x7f) * Math.pow(2, shift);
      if (bytes[i] & 0x80) {
        shift += 7;
      } else {
        out.push(value);
        value = 0;
        shift = 0;
      }
    }
    return out;
  }

  function toBase64(bytes) {
    var binary = "";
    for (var i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
    return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }

  function fromBase64(text) {
    var padded = text.replace(/-/g, "+").replace(/_/g, "/");
    while (padded.length % 4) padded += "=";
    var binary = atob(padded);
    var bytes = [];
    for (var i = 0; i < binary.length; i++) bytes.push(binary.charCodeAt(i));
    return bytes;
  }

  // --- encoding schemes -------------------------------------------------

  function universe() {
    return window.ARCHIVE_IDS || [];
  }

  function deltas(sorted) {
    var bytes = [], prev = 0;
    sorted.forEach(function (id) {
      writeVarint(bytes, id - prev);
      prev = id;
    });
    return bytes;
  }

  function undeltas(bytes) {
    var out = [], running = 0;
    readVarints(bytes).forEach(function (d) {
      running += d;
      out.push(running);
    });
    return out;
  }

  function toBitset(ids, max) {
    var bytes = new Array(Math.floor(max / 8) + 1).fill(0);
    ids.forEach(function (id) {
      if (id <= max) bytes[Math.floor(id / 8)] |= 1 << (id % 8);
    });
    return bytes;
  }

  function fromBitset(bytes) {
    var out = [];
    for (var i = 0; i < bytes.length * 8; i++) {
      if (bytes[Math.floor(i / 8)] & (1 << (i % 8))) out.push(i);
    }
    return out;
  }

  /* Three encodings, and whichever is shortest wins. Sparse collections are
   * smallest as a delta list; dense ones as a bitset; and a nearly-complete
   * collection is smallest expressed as what it *excludes*, which is why
   * "everything" encodes to a handful of characters. */
  function encode() {
    var ids = entries.map(function (e) { return e.id; })
                     .filter(function (id) { return typeof id === "number"; })
                     .sort(function (a, b) { return a - b; });
    if (!ids.length) return "";

    var all = universe();
    var candidates = [{ tag: "a", text: toBase64(deltas(ids)) }];

    if (all.length) {
      var max = all[all.length - 1];
      candidates.push({ tag: "c", text: toBase64(toBitset(ids, max)) });

      var marked = {};
      ids.forEach(function (id) { marked[id] = true; });
      var missing = all.filter(function (id) { return !marked[id]; });
      candidates.push({ tag: "b", text: toBase64(deltas(missing)) });
    }

    candidates.sort(function (x, y) { return x.text.length - y.text.length; });
    return VERSION + candidates[0].tag + candidates[0].text;
  }

  function decode(payload) {
    if (!payload || payload.charAt(0) !== VERSION) return null;
    var tag = payload.charAt(1);
    var bytes;
    try {
      bytes = fromBase64(payload.slice(2));
    } catch (e) {
      return null;
    }

    if (tag === "a") return undeltas(bytes);
    if (tag === "c") return fromBitset(bytes);
    if (tag === "b") {
      var excluded = {};
      undeltas(bytes).forEach(function (id) { excluded[id] = true; });
      return universe().filter(function (id) { return !excluded[id]; });
    }
    return null;
  }

  // --- public API -------------------------------------------------------

  var Collection = {
    all: function () { return entries.slice(); },
    count: function () { return entries.length; },
    has: function (id) { return indexOf(id) !== -1; },

    add: function (entry) {
      if (valid(entry) && indexOf(entry.id) === -1) {
        entries.push(entry);
        save();
      }
    },

    remove: function (id) {
      var at = indexOf(id);
      if (at !== -1) {
        entries.splice(at, 1);
        save();
      }
    },

    /* Adding a mod adds what it needs to run. A collection is a "what do I
     * install" list, and a mod without its dependencies is not installable --
     * so the dependencies come too, marked with the mod that pulled them in
     * (`via`) so the flyout can show why they are there.
     *
     * Only direct dependencies: that is what the archive records per mod, and
     * in this data dependency chains are one level deep in practice. */
    addWithDeps: function (entry, deps) {
      var added = 0;
      if (indexOf(entry.id) === -1) {
        entries.push(entry);
        added++;
      } else {
        // Explicitly adding something that arrived as a dependency promotes
        // it: it is now a deliberate choice, not a consequence.
        entries[indexOf(entry.id)].via = null;
      }
      (deps || []).forEach(function (dep) {
        if (indexOf(dep.id) === -1) {
          entries.push({ id: dep.id, name: dep.name, href: dep.href,
                         sources: dep.sources || [], via: entry.id });
          added++;
        }
      });
      save();
      return added;
    },

    toggle: function (entry, deps) {
      if (this.has(entry.id)) this.remove(entry.id);
      else this.addWithDeps(entry, deps);
      return this.has(entry.id);
    },

    replaceAll: function (list) {
      entries = list.filter(valid);
      save();
    },

    clear: function () { entries = []; save(); },

    onChange: function (fn) { listeners.push(fn); },

    shareUrl: function () {
      var payload = encode();
      if (!payload) return "";
      // Always points at the index: it is the only page holding the data
      // needed to turn bare ids back into names and links.
      var base = location.origin === "null"
        ? UP + "index.html"                       // opened from file://
        : new URL(UP + "index.html", location.href).href;
      return base + "?pack=" + payload;
    },

    sourceUrls: function () {
      var urls = [];
      entries.forEach(function (entry) {
        (entry.sources || []).forEach(function (url) {
          if (urls.indexOf(url) === -1) urls.push(url);
        });
      });
      return urls;
    },

    decode: decode,

    // Rows are rendered in batches as you scroll, so freshly
    // inserted toggles need their state applied afterwards.
    syncButtons: function () { syncButtons(); }
  };

  window.Collection = Collection;

  // Another tab changed the collection: adopt it rather than overwrite it.
  window.addEventListener("storage", function (event) {
    if (event.key !== STORE_KEY) return;
    entries = load();
    listeners.forEach(function (fn) { fn(); });
  });

  // --- clipboard --------------------------------------------------------

  function copy(text, button, done) {
    var original = button.textContent;
    var finish = function () {
      button.textContent = done;
      setTimeout(function () { button.textContent = original; }, 2000);
    };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(finish, function () {
        fallback(text, finish);
      });
    } else {
      fallback(text, finish);
    }
  }

  function fallback(text, finish) {
    // file:// and plain http have no clipboard API, which is exactly where an
    // offline archive gets used.
    var area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    try { document.execCommand("copy"); finish(); } catch (e) { /* no-op */ }
    document.body.removeChild(area);
  }

  // --- toast ------------------------------------------------------------

  /* Transient confirmation, top right. Used where something happened that the
   * reader did not explicitly click for -- a silent import, or dependencies
   * arriving alongside a mod -- so the change is never invisible, but does not
   * demand dismissing either. */
  function toast(message) {
    var box = document.getElementById("toast-stack");
    if (!box) {
      box = document.createElement("div");
      box.id = "toast-stack";
      box.className = "toast-stack";
      box.setAttribute("role", "status");
      box.setAttribute("aria-live", "polite");
      document.body.appendChild(box);
    }

    var note = document.createElement("div");
    note.className = "toast";
    note.textContent = message;
    box.appendChild(note);

    setTimeout(function () { note.classList.add("out"); }, 3200);
    setTimeout(function () { note.remove(); }, 3700);
  }

  // --- flyout -----------------------------------------------------------

  function buildFlyout() {
    var aside = document.createElement("aside");
    aside.className = "collection-flyout";
    aside.id = "collection-flyout";
    aside.innerHTML =
      '<button class="collection-tab" type="button" aria-expanded="false"' +
      ' aria-controls="collection-body">' +
      '<span class="collection-tab-label">Collection</span>' +
      '<span class="collection-count">0</span></button>' +
      '<div class="collection-body" id="collection-body">' +
      '  <div class="collection-head">' +
      '    <button type="button" class="linkbtn" data-copy="sources">Copy source URLs</button>' +
      '    <button type="button" class="linkbtn" data-copy="share">Copy share link</button>' +
      '    <button type="button" class="linkbtn danger" data-clear>Clear</button>' +
      '  </div>' +
      '  <ul class="collection-list"></ul>' +
      '</div>';
    document.body.appendChild(aside);
    return aside;
  }

  var flyout = buildFlyout();
  var tab = flyout.querySelector(".collection-tab");
  var list = flyout.querySelector(".collection-list");
  var countBadge = flyout.querySelector(".collection-count");

  function setOpen(open) {
    flyout.classList.toggle("open", open);
    tab.setAttribute("aria-expanded", open ? "true" : "false");
    try { localStorage.setItem(OPEN_KEY, open ? "1" : "0"); } catch (e) { /* no-op */ }
  }

  tab.addEventListener("click", function () {
    setOpen(!flyout.classList.contains("open"));
  });

  flyout.addEventListener("click", function (event) {
    var copyButton = event.target.closest("[data-copy]");
    if (copyButton) {
      var kind = copyButton.getAttribute("data-copy");
      var text = kind === "share"
        ? Collection.shareUrl()
        : Collection.sourceUrls().join("\n");
      if (!text) return;
      copy(text, copyButton, kind === "share" ? "Link copied" : "Copied");
      return;
    }

    if (event.target.closest("[data-clear]")) {
      if (Collection.count() &&
          window.confirm("Remove all " + Collection.count() +
                         " mods from your collection?")) {
        Collection.clear();
      }
      return;
    }

    var remove = event.target.closest("[data-remove]");
    if (remove) {
      event.preventDefault();
      Collection.remove(remove.getAttribute("data-remove"));
    }
  });

  function renderFlyout() {
    var all = Collection.all();
    countBadge.textContent = all.length;
    flyout.classList.toggle("empty", all.length === 0);

    if (!all.length) {
      list.innerHTML = '<li class="collection-empty">No mods marked yet. ' +
        'Use the <strong>+</strong> button on any mod to add it.</li>';
      return;
    }

    // A dependency is listed under the mod that pulled it in. If that mod is
    // later removed, the dependency is still installed-worthy, so it simply
    // returns to the top level rather than vanishing.
    var present = {};
    all.forEach(function (entry) { present[String(entry.id)] = true; });

    var children = {};
    all.forEach(function (entry) {
      if (entry.via && present[String(entry.via)]) {
        (children[String(entry.via)] = children[String(entry.via)] || []).push(entry);
      }
    });

    var top = all.filter(function (entry) {
      return !(entry.via && present[String(entry.via)]);
    });

    list.innerHTML = top.map(function (entry) {
      return item(entry, false) +
        (children[String(entry.id)] || []).map(function (dep) {
          return item(dep, true);
        }).join("");
    }).join("");
  }

  function item(entry, isDependency) {
    var href = UP + (entry.href || "");
    return '<li' + (isDependency ? ' class="dependency"' : "") + '>' +
      (isDependency ? '<span class="dep-mark" title="Required by the mod above"' +
        ' aria-hidden="true">└</span>' : "") +
      '<a href="' + escapeAttr(href) + '">' +
      escapeText(entry.name || String(entry.id)) + "</a>" +
      '<button type="button" class="collection-remove" data-remove="' +
      escapeAttr(String(entry.id)) + '" aria-label="Remove ' +
      escapeAttr(entry.name || "") + '">×</button></li>';
  }

  function escapeText(value) {
    return String(value).replace(/[&<>]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c];
    });
  }

  function escapeAttr(value) {
    return escapeText(value).replace(/"/g, "&quot;");
  }

  // --- mark toggles -----------------------------------------------------

  function depsFrom(button) {
    var raw = button.getAttribute("data-deps");
    if (!raw) return [];
    try {
      var parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
      return [];
    }
  }

  function entryFrom(button) {
    var sources = button.getAttribute("data-sources");
    return {
      id: numericIfPossible(button.getAttribute("data-id")),
      name: button.getAttribute("data-name") || "",
      href: button.getAttribute("data-href") || "",
      sources: sources ? sources.split(" ").filter(Boolean) : []
    };
  }

  function numericIfPossible(value) {
    return /^\d+$/.test(value) ? Number(value) : value;
  }

  function syncButtons() {
    var buttons = document.querySelectorAll("[data-mark]");
    Array.prototype.forEach.call(buttons, function (button) {
      var marked = Collection.has(numericIfPossible(button.getAttribute("data-id")));
      button.classList.toggle("marked", marked);
      button.setAttribute("aria-pressed", marked ? "true" : "false");
      var label = button.querySelector(".mark-label");
      if (label) label.textContent = marked ? "In collection" : "Add to collection";
    });
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-mark]");
    if (!button) return;
    event.preventDefault();

    var deps = depsFrom(button);
    var wasIn = Collection.has(entryFrom(button).id);
    Collection.toggle(entryFrom(button), deps);

    if (!wasIn && deps.length) {
      var pulled = Collection.all().filter(function (row) {
        return row.via === entryFrom(button).id;
      }).length;
      if (pulled) {
        toast("Added with " + pulled + " dependenc" +
              (pulled === 1 ? "y" : "ies"));
      }
    }
  });

  // --- importing a shared link -----------------------------------------

  function resolve(ids) {
    // Only the index carries the catalogue, so only it can turn ids into
    // names and links. Elsewhere a shared link is simply not offered.
    var catalogue = window.MOD_INDEX;
    if (!catalogue) return null;

    var byId = {};
    catalogue.forEach(function (mod) { byId[String(mod.id)] = mod; });

    var found = [], missing = 0;
    ids.forEach(function (id) {
      var mod = byId[String(id)];
      if (!mod) { missing++; return; }
      found.push({ id: mod.id, name: mod.name, href: mod.href,
                   sources: mod.source_urls || [] });
    });
    return { found: found, missing: missing };
  }

  function showImportModal(resolved) {
    var dialog = document.createElement("dialog");
    dialog.className = "import-modal";

    var missing = resolved.missing
      ? '<p class="note">' + resolved.missing +
        " of them are no longer in the archive and were skipped.</p>"
      : "";

    dialog.innerHTML =
      "<h2>Someone shared a collection</h2>" +
      "<p>This link contains <strong>" + resolved.found.length +
      " mods</strong>. You already have <strong>" + Collection.count() +
      "</strong> in your collection.</p>" + missing +
      '<div class="modal-actions">' +
      '  <button type="button" class="linkbtn primary" data-import="merge">' +
      "    Add to my collection</button>" +
      '  <button type="button" class="linkbtn" data-import="replace">' +
      "    Replace my collection</button>" +
      '  <button type="button" class="linkbtn" data-import="dismiss">Cancel</button>' +
      "</div>";

    dialog.addEventListener("click", function (event) {
      var button = event.target.closest("[data-import]");
      if (!button) return;
      apply(button.getAttribute("data-import"), resolved);
      close(dialog);
    });

    // Escape closes without touching anything, same as Cancel.
    dialog.addEventListener("cancel", function () { clearPackParam(); });

    document.body.appendChild(dialog);
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");        // very old browsers

    var primary = dialog.querySelector('[data-import="merge"]');
    if (primary) primary.focus();
  }

  function close(dialog) {
    if (typeof dialog.close === "function" && dialog.open) dialog.close();
    dialog.remove();
  }

  function apply(action, resolved) {
    if (action === "merge") {
      var before = Collection.count();
      resolved.found.forEach(function (entry) { Collection.add(entry); });
      setOpen(true);
      toast("Added " + (Collection.count() - before) + " mods to your collection");
    } else if (action === "replace") {
      Collection.replaceAll(resolved.found);
      setOpen(true);
      toast("Collection replaced with " + resolved.found.length + " mods");
    }
    clearPackParam();
  }

  function clearPackParam() {
    // Drop ?pack= so a reload does not prompt again, keeping other params.
    var params = new URLSearchParams(location.search);
    params.delete("pack");
    var qs = params.toString();
    history.replaceState(null, "", location.pathname + (qs ? "?" + qs : ""));
  }

  function handleSharedLink() {
    var payload = new URLSearchParams(location.search).get("pack");
    if (!payload) return;

    var ids = decode(payload);
    if (!ids || !ids.length) return;

    var resolved = resolve(ids);
    if (!resolved || !resolved.found.length) return;

    // Nothing to lose and nothing to decide: just take the shared collection
    // and show it. Asking would be ceremony for a question with one answer.
    if (Collection.count() === 0) {
      Collection.replaceAll(resolved.found);
      setOpen(true);
      clearPackParam();
      toast("Imported " + resolved.found.length + " mods into your collection");
      return;
    }

    showImportModal(resolved);
  }

  // --- back to top ------------------------------------------------------

  /* Scrolls whichever element is actually scrolling: the index gives the mod
   * list its own overflow so the filters stay put, while every other page
   * scrolls the window. */
  function scroller() { return document.getElementById("listscroll"); }

  var toTop = document.createElement("button");
  toTop.type = "button";
  toTop.className = "to-top";
  toTop.setAttribute("aria-label", "Back to top");
  toTop.innerHTML = "↑";
  document.body.appendChild(toTop);

  toTop.addEventListener("click", function () {
    var box = scroller();
    if (box) box.scrollTo({ top: 0, behavior: "smooth" });
    window.scrollTo({ top: 0, behavior: "smooth" });
  });

  function updateToTop() {
    var box = scroller();
    var offset = box ? box.scrollTop : window.scrollY;
    toTop.classList.toggle("show", offset > 400);
  }

  (scroller() || window).addEventListener("scroll", updateToTop);
  if (scroller()) window.addEventListener("scroll", updateToTop);
  updateToTop();

  // --- start ------------------------------------------------------------

  Collection.onChange(function () {
    renderFlyout();
    syncButtons();
  });

  renderFlyout();
  syncButtons();

  var wasOpen = false;
  try { wasOpen = localStorage.getItem(OPEN_KEY) === "1"; } catch (e) { /* no-op */ }
  if (wasOpen) setOpen(true);

  // Deferred scripts run in document order, all before DOMContentLoaded. This
  // file loads first so index.js can use the API above immediately -- which
  // means the catalogue it publishes does not exist yet, and resolving a
  // shared link has to wait for it.
  document.addEventListener("DOMContentLoaded", handleSharedLink);
})();
