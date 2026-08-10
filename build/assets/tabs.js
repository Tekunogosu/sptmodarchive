/* Detail pages: turn the stacked sections into tabs.
 *
 * The panels are markup by the time this runs -- render.js builds them, this
 * promotes them to a tablist. Kept as two steps because the nav is a row of
 * in-page anchors and the panels are ordinary sections, so a failure here
 * leaves a long scrolling page rather than an empty one.
 *
 * Keyboard and screen-reader behaviour follows the ARIA tabs pattern: arrow
 * keys move between tabs, Home/End jump to the ends, and only the active tab
 * is in the focus order.
 *
 * Selecting a tab fires `archive:tab` on the tablist root, carrying the panel
 * id. That is how the mod page knows to go and fetch its comments, which are
 * the one panel whose content is not already on the page.
 */
(function () {
  "use strict";

  window.initTabs = function initTabs() {
    var root = document.getElementById("mod-tabs");
    if (!root || root.dataset.enhanced) return;

    var list = root.querySelector(".tablist");
    var tabs = Array.prototype.slice.call(list.querySelectorAll(".tab"));
    var panels = tabs.map(function (tab) {
      return document.getElementById(tab.getAttribute("href").slice(1));
    });

    if (!tabs.length || panels.indexOf(null) !== -1) return;

    list.setAttribute("role", "tablist");
    tabs.forEach(function (tab, i) {
      tab.setAttribute("role", "tab");
      tab.id = "tab-" + panels[i].id;
      panels[i].setAttribute("role", "tabpanel");
      panels[i].setAttribute("aria-labelledby", tab.id);
      panels[i].setAttribute("tabindex", "0");
    });

    function select(index, focus) {
      tabs.forEach(function (tab, i) {
        var active = i === index;
        tab.setAttribute("aria-selected", active ? "true" : "false");
        // Only the selected tab is tabbable; arrow keys move within the list.
        tab.setAttribute("tabindex", active ? "0" : "-1");
        panels[i].hidden = !active;
      });
      if (focus) tabs[index].focus();
      root.dispatchEvent(new CustomEvent("archive:tab", {
        detail: { panel: panels[index].id }
      }));
    }

    function indexFromHash() {
      var hash = location.hash.slice(1);
      if (!hash) return 0;
      for (var i = 0; i < panels.length; i++) {
        // Match the panel itself, or anything inside it, so a link to a
        // specific element still opens the tab containing it.
        if (panels[i].id === hash || panels[i].querySelector("#" + CSS.escape(hash))) {
          return i;
        }
      }
      return 0;
    }

    list.addEventListener("click", function (event) {
      var tab = event.target.closest(".tab");
      if (!tab) return;
      event.preventDefault();
      var index = tabs.indexOf(tab);
      select(index, false);
      // replaceState rather than assigning location.hash: switching tabs should
      // not add a history entry per click, but the URL should stay shareable.
      history.replaceState(null, "", location.pathname + location.search +
                           "#" + panels[index].id);
    });

    list.addEventListener("keydown", function (event) {
      var current = tabs.indexOf(document.activeElement);
      if (current === -1) return;

      var next = {
        ArrowLeft: current - 1,
        ArrowRight: current + 1,
        Home: 0,
        End: tabs.length - 1
      }[event.key];

      if (next === undefined) return;
      event.preventDefault();
      select((next + tabs.length) % tabs.length, true);
    });

    window.addEventListener("hashchange", function () {
      select(indexFromHash(), false);
    });

    select(indexFromHash(), false);
    root.dataset.enhanced = "true";
  };
})();
