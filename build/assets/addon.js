/* The addon page: /addon/<id>-<slug>.html.
 *
 * Deliberately simpler than a mod page. An addon has no repository health, no
 * dependencies and no comments -- the Forge never gave it any -- so this is
 * its description, its versions, and a way back to the mod it extends.
 */
(function () {
  "use strict";

  var R = window.R;
  if (document.body.dataset.page !== "addon") return;

  function render(addon) {
    var parent = addon.parent
      ? '<p class="addonparent">Extends <a href="' + R.esc(addon.parent.href) +
        '">' + R.esc(addon.parent.name) + "</a></p>"
      : '<p class="addonparent">The mod this addon extends is not in the ' +
        "archive.</p>";

    var sections = [];
    if (addon.description) {
      sections.push(["description", "Description", null,
                     '<div class="prose">' + addon.description + "</div>"]);
    }
    if (addon.versions && addon.versions.length) {
      sections.push(["versions", "Versions", addon.version_count,
                     R.versions(addon.versions, addon.versions_hidden, addon.mark)]);
    }

    return R.head(addon, parent) + R.splitcols(addon) + R.sectionTabs(sections);
  }

  document.addEventListener("archive:rendered", function (event) {
    R.setTitle(event.detail.record.name, event.detail.record.teaser);
    window.initTabs();
  });

  R.detailPage("data/addon/", render, "That addon is not in the archive.");
})();
