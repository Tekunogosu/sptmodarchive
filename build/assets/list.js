/* One archived mod list: /list/<id>-<slug>.html.
 *
 * A modpack somebody ran together on a given SPT version, rendered as the same
 * card the mod page uses for dependencies -- a list is the third place the
 * archive says "here is a set of mods to install", and there is no reason for
 * it to look like a different kind of thing.
 */
(function () {
  "use strict";

  var R = window.R;
  if (document.body.dataset.page !== "list") return;

  function render(entry) {
    var owner = entry.owner.href
      ? '<a href="' + R.esc(R.url(entry.owner.href)) + '">' + R.esc(entry.owner.name) + "</a>"
      : R.esc(entry.owner.name);

    var note = entry.missing
      ? '<p class="panel-note">' + entry.missing + " mod(s) in this list are no " +
        "longer in the archive.</p>"
      : "";

    return '<div class="modhead"><div class="modhead-main">' +
      '<div class="modhead-title"><h1>' + R.esc(entry.title) + "</h1>" +
      '<button type="button" class="mark mark-wide" id="import-list">' +
      '<span class="mark-label">Add all to collection</span></button></div>' +
      '<div class="byline">by ' + owner + "</div>" +
      '<div class="badges">' +
      (entry.spt ? R.badge("SPT " + entry.spt, "spt") : "") +
      R.badge(R.plural(entry.mods.length, "mod")) + "</div>" +
      "</div></div>" +
      '<section class="panel"><h2>Mods in this list</h2>' + note +
      '<ul class="deplist listmods">' +
      entry.mods.map(R.card).join("") + "</ul></section>" +
      '<section class="panel"><h2>Source</h2>' +
      (entry.delisted
        ? '<p><span class="label">Archived from the original SPT Forge — this ' +
          'list is not on sp-mod.com</span></p>'
        : '<p><a href="' + R.esc(entry.forge_url) + '" target="_blank"' +
          ' rel="noopener noreferrer">View on sp-mod.com</a></p>') +
      "</section>";
  }

  document.addEventListener("archive:rendered", function (event) {
    var entry = event.detail.record;
    R.setTitle(entry.title, entry.mods.length + " mods curated on the SPT Forge.");
    window.initImportList();
  });

  R.detailPage("data/list/", render, "That mod list is not in the archive.");
})();
