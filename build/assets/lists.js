/* The mod-list index: lists.html.
 *
 * Small enough to render in one pass -- there are a couple of hundred lists,
 * not two thousand mods -- so this has none of the virtual scrolling the
 * catalogue needs.
 */
(function () {
  "use strict";

  var R = window.R;
  if (document.body.dataset.page !== "lists") return;

  function card(entry) {
    return '<article class="listcard"><div>' +
      '<h2 class="title"><a href="' + R.esc(R.url(entry.href)) + '">' +
      R.esc(entry.title) + "</a></h2>" +
      '<div class="byline">by ' + R.esc(entry.owner) + "</div>" +
      '<div class="badges">' +
      (entry.spt ? R.badge("SPT " + entry.spt, "spt") : "") +
      R.badge(R.plural(entry.mod_count, "mod")) + "</div></div>" +
      '<div class="stats"><div class="statnums"><b>' + entry.mod_count +
      "</b>mods</div></div></article>";
  }

  R.getJSON("data/lists.json").then(function (lists) {
    document.getElementById("lists-heading").textContent =
      "Mod lists (" + lists.length + ")";
    document.getElementById("listgrid").innerHTML = lists.map(card).join("");
    document.getElementById("page-status").remove();
  }).catch(function (error) {
    console.error(error);
    R.fail("The mod lists could not be loaded.");
  });
})();
