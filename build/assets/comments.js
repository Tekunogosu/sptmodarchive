/* Mod page: render the archived comment threads, then sort and search them.
 *
 * Comments are the reason this rewrite exists. They are 60 MB across the
 * archive -- more than everything else put together -- and the old build
 * rendered every one of them into its mod page, so opening any mod meant
 * downloading its entire comment history whether or not you looked at it.
 * Now they are a separate file per mod, fetched the first time the Comments
 * tab is opened and never otherwise.
 *
 * Threads are the unit of sorting and searching. A reply matching a search is
 * useless without the comment it answers, so a thread survives if anything in
 * it matches, and matches are highlighted wherever they occur.
 */
(function () {
  "use strict";

  var R = window.R;

  function comment(item) {
    var likes = item.likes
      ? '<span class="likes">' + R.plural(item.likes, "like") + "</span>"
      : "";
    var replies = (item.replies || []).map(function (reply) {
      return comment(reply);
    }).join("");
    // `body` is sanitized at build time by sanitize.clean_html(). It is the
    // one string on this page inserted without escaping.
    return '<article class="comment"><div class="chead">' +
      '<span class="who">' + R.esc(item.who) + "</span>" +
      '<time class="when" datetime="' + R.esc(item.at) + '">' +
      R.esc((item.at || "").slice(0, 10)) + "</time>" + likes + "</div>" +
      '<div class="cbody prose">' + item.body + "</div></article>" +
      (replies ? '<div class="replies">' + replies + "</div>" : "");
  }

  function render(data) {
    var threads = data.items.map(function (item) {
      return '<div class="thread-item" data-time="' + item.t +
        '" data-likes="' + (item.likes || 0) +
        '" data-replies="' + (item.n || 0) + '">' + comment(item) + "</div>";
    }).join("");

    return '<p class="panel-note">' + R.num(data.count) + " comments across " +
      R.plural(data.threads, "thread") + ", archived from the Forge.</p>" +
      '<div class="comment-controls">' +
      '<input type="search" id="comment-search" placeholder="Search comments…"' +
      ' autocomplete="off" aria-label="Search comments">' +
      '<select id="comment-sort" aria-label="Sort comments">' +
      '<option value="newest">Newest first</option>' +
      '<option value="oldest">Oldest first</option>' +
      '<option value="likes">Most liked</option>' +
      '<option value="replies">Most replies</option>' +
      "</select></div>" +
      '<p class="empty" id="comment-status"></p>' +
      '<div class="thread" id="comment-thread">' + threads + "</div>";
  }

  /* --- sorting and searching, over the rendered threads ----------------- */

  function bind() {
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

    function time(thread) { return Number(thread.dataset.time) || 0; }
    function likes(thread) { return Number(thread.dataset.likes) || 0; }
    function replies(thread) { return Number(thread.dataset.replies) || 0; }

    var SORTS = {
      newest: function (a, b) { return time(b) - time(a); },
      oldest: function (a, b) { return time(a) - time(b); },
      likes: function (a, b) { return likes(b) - likes(a) || time(b) - time(a); },
      replies: function (a, b) { return replies(b) - replies(a) || time(b) - time(a); }
    };

    function applySort() {
      var cmp = SORTS[sortBox.value] || SORTS.newest;
      threads.slice().sort(cmp).forEach(function (thread) {
        root.appendChild(thread);      // appendChild moves, it does not copy
      });
    }

    function escapeRegex(s) {
      return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    }

    function highlight(thread, term) {
      thread.querySelectorAll(".cbody").forEach(function (body) {
        var original = body.dataset.original;
        body.innerHTML = original;
        if (!term) return;
        // Walk text nodes only, so the term can never match markup and the
        // inserted <mark> cannot break the surrounding HTML.
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
  }

  /* Fetch, render and bind, once. Called by mod.js the first time the
   * Comments tab is opened. */
  window.loadComments = function loadComments(id, panel) {
    if (panel.dataset.loaded) return;
    panel.dataset.loaded = "true";
    R.getJSON("data/comment/" + encodeURIComponent(id) + ".json")
      .then(function (data) {
        panel.querySelector(".comment-slot").innerHTML = render(data);
        bind();
      })
      .catch(function (error) {
        console.error(error);
        panel.querySelector(".comment-slot").innerHTML =
          '<p class="empty">The archived comments for this mod could not be ' +
          "loaded.</p>";
      });
  };
})();
