/* Mod page: sort and search the archived comment threads.
 *
 * The comments are rendered into the page by the build, not by this script.
 * That is deliberate: they stay readable with JavaScript off, and the section
 * is a plain <details> so collapsing costs no code at all. This file only
 * adds the two things markup cannot do -- reordering and searching.
 *
 * Threads are the unit of both operations. A reply matching a search is
 * useless without the comment it answers, so a thread survives if anything
 * in it matches, and matches are highlighted wherever they occur.
 */
(function () {
  "use strict";

  var root = document.getElementById("comment-thread");
  if (!root) return;

  var searchBox = document.getElementById("comment-search");
  var sortBox = document.getElementById("comment-sort");
  var status = document.getElementById("comment-status");

  var threads = Array.prototype.slice.call(
    root.querySelectorAll(":scope > .thread-item"));

  // Snapshot the original markup once so highlighting is always applied to
  // clean HTML rather than to the output of a previous highlight pass.
  threads.forEach(function (thread) {
    thread.querySelectorAll(".cbody").forEach(function (body) {
      body.dataset.original = body.innerHTML;
    });
    thread.dataset.text = (thread.textContent || "").toLowerCase();
  });

  // --- sorting ---------------------------------------------------------

  var SORTS = {
    newest: function (a, b) { return time(b) - time(a); },
    oldest: function (a, b) { return time(a) - time(b); },
    likes: function (a, b) { return likes(b) - likes(a) || time(b) - time(a); },
    replies: function (a, b) { return replies(b) - replies(a) || time(b) - time(a); }
  };

  function time(thread) { return Number(thread.dataset.time) || 0; }
  function likes(thread) { return Number(thread.dataset.likes) || 0; }
  function replies(thread) { return Number(thread.dataset.replies) || 0; }

  function applySort() {
    var cmp = SORTS[sortBox.value] || SORTS.newest;
    threads.slice().sort(cmp).forEach(function (thread) {
      root.appendChild(thread);      // appendChild moves, it does not copy
    });
  }

  // --- searching -------------------------------------------------------

  function escapeRegex(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function highlight(thread, term) {
    thread.querySelectorAll(".cbody").forEach(function (body) {
      var original = body.dataset.original;
      if (!term) {
        body.innerHTML = original;
        return;
      }
      // Walk text nodes only, so the term can never match markup and the
      // inserted <mark> cannot break the surrounding HTML.
      body.innerHTML = original;
      var pattern = new RegExp(escapeRegex(term), "gi");
      var walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
      var targets = [];
      while (walker.nextNode()) {
        if (pattern.test(walker.currentNode.nodeValue)) targets.push(walker.currentNode);
        pattern.lastIndex = 0;
      }
      targets.forEach(function (node) {
        var span = document.createElement("span");
        span.innerHTML = node.nodeValue.replace(/[&<>]/g, function (c) {
          return { "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c];
        }).replace(pattern, "<mark>$&</mark>");
        node.parentNode.replaceChild(span, node);
      });
    });
  }

  function applySearch() {
    var term = searchBox.value.trim().toLowerCase();
    var shown = 0;

    threads.forEach(function (thread) {
      var hit = !term || thread.dataset.text.indexOf(term) !== -1;
      thread.hidden = !hit;
      if (hit) shown++;
      highlight(thread, hit ? term : "");
    });

    status.textContent = term
      ? shown + " of " + threads.length + " threads match “" + term + "”"
      : "";
  }

  var debounce;
  searchBox.addEventListener("input", function () {
    clearTimeout(debounce);
    debounce = setTimeout(applySearch, 140);
  });
  sortBox.addEventListener("change", applySort);

  applySort();
})();
