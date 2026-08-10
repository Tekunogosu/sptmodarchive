/* The author page: /user/<id>-<slug>.html.
 *
 * Everything the archive holds by one person, in the same card the rest of the
 * site uses for "here is a thing you might install". The tab strip is the
 * point of the structure: the Forge profile also carried a wall and an
 * activity feed, and those become two more entries without the page changing
 * shape.
 */
(function () {
  "use strict";

  var R = window.R;
  if (document.body.dataset.page !== "user") return;

  function render(author) {
    var sections = [];
    if (author.mods.length) {
      sections.push(["mods", "Mods", author.mods.length, R.cards(author.mods)]);
    }
    if (author.addons.length) {
      sections.push(["addons", "Addons", author.addons.length,
                     R.cards(author.addons)]);
    }
    if (author.lists.length) {
      var rows = author.lists.map(function (entry) {
        return '<li class="depcard"><span class="depthumb"></span>' +
          '<div class="depmain"><a class="depname" href="' + R.esc(R.url(entry.href)) +
          '">' + R.esc(entry.title) + "</a>" +
          '<p class="teaser">' + entry.mod_count + " mods" +
          (entry.spt ? " · SPT " + R.esc(entry.spt) : "") +
          "</p></div></li>";
      }).join("");
      sections.push(["lists", "Mod lists", author.lists.length,
                     '<ul class="deplist">' + rows + "</ul>"]);
    }

    var counts = [];
    if (author.mods.length) counts.push(R.plural(author.mods.length, "mod"));
    if (author.addons.length) counts.push(R.plural(author.addons.length, "addon"));
    if (author.lists.length) counts.push(R.plural(author.lists.length, "mod list"));

    var avatar = author.avatar
      ? '<img src="' + R.esc(R.url(author.avatar)) + '" alt="" loading="lazy">' : "";

    return '<div class="modhead">' + avatar +
      '<div class="modhead-main">' +
      '<div class="modhead-title"><h1>' + R.esc(author.name) + "</h1></div>" +
      '<div class="bylinerow">' +
      '<div class="byline">' + R.esc(counts.join(" · ") || "Nothing archived") +
      "</div>" +
      '<div class="badges">' + R.badge("Author", "cat") + "</div></div>" +
      (author.downloads
        ? '<p class="teaser">' + R.num(author.downloads) +
          " downloads across their mods</p>" : "") +
      "</div></div>" +
      R.sectionTabs(sections, "Nothing by this author is archived yet.") +
      '<section class="panel"><h2>Profile</h2>' +
      '<p class="forgelink"><a href="' + R.esc(author.forge_url) + '" target="_blank"' +
      ' rel="noopener noreferrer">Original Forge profile</a>' +
      ' <span class="label">offline after shutdown</span></p></section>';
  }

  document.addEventListener("archive:rendered", function (event) {
    var author = event.detail.record;
    R.setTitle(author.name, author.name + " on the SPT Mod Archive.");
    window.initTabs();
  });

  R.detailPage("data/user/", render, "That author is not in the archive.");
})();
