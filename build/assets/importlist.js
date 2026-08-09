/* List page: add or remove the whole list in one click.
 *
 * The button drives the per-mod mark buttons already rendered next to each
 * entry rather than carrying its own copy of the list. That keeps one source
 * of truth, and means dependencies are pulled in exactly as they would be by
 * clicking each mod individually.
 *
 * It is a toggle, and reports which way it will go: once every mod in the
 * list is in the collection, the same button takes them back out.
 */
(function () {
  "use strict";

  var button = document.getElementById("import-list");
  if (!button || !window.Collection) return;

  var label = button.querySelector(".mark-label");
  var marks = Array.prototype.slice.call(
    document.querySelectorAll(".listmods [data-mark]"));
  if (!marks.length) return;

  function idOf(mark) {
    var raw = mark.getAttribute("data-id");
    return /^\d+$/.test(raw) ? Number(raw) : raw;
  }

  function ids() {
    return marks.map(idOf);
  }

  function allPresent() {
    return ids().every(function (id) { return window.Collection.has(id); });
  }

  function sync() {
    var complete = allPresent();
    // Reusing the mark button's own styling gives the green/✓ state and the
    // red ×-on-hover preview for free.
    button.classList.toggle("marked", complete);
    button.setAttribute("aria-pressed", complete ? "true" : "false");
    if (!label) return;
    if (complete) {
      // Two labels, swapped by CSS on hover: the state, and what a click
      // would do to it.
      label.innerHTML = '<span class="lbl-state">All mods added to collection</span>' +
        '<span class="lbl-hover">Remove all from collection</span>';
    } else {
      label.textContent = "Add all to collection";
    }
  }

  button.addEventListener("click", function () {
    if (allPresent()) {
      /* Only the mods this list names are removed. Dependencies that came in
       * alongside them stay: they may be needed by something else, and
       * silently deleting them would be surprising. */
      ids().forEach(function (id) { window.Collection.remove(id); });
    } else {
      marks.forEach(function (mark) {
        if (!window.Collection.has(idOf(mark))) mark.click();
      });
    }
    sync();
  });

  window.Collection.onChange(sync);
  sync();
})();
