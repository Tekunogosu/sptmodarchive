/* The mod page: /mod/<id>-<slug>.html.
 *
 * Everything except the comments arrives in one file, data/mod/<id>.json --
 * typically 6 KB, against the 45 KB average of the HTML page this replaced.
 * The comments are a second file, fetched only if the tab is opened.
 */
(function () {
  "use strict";

  var R = window.R;
  if (document.body.dataset.page !== "mod") return;

  function render(mod) {
    var sections = [];

    if (mod.description) {
      sections.push(["description", "Description", null,
                     '<div class="prose">' + mod.description + "</div>"]);
    }
    // Directly after Description: an addon is something you install *for this
    // mod*, so it belongs beside the mod's own text rather than behind its
    // version history.
    if (mod.addons && mod.addons.length) {
      sections.push(["addons", "Addons", mod.addons.length, R.cards(mod.addons)]);
    }
    if (mod.deps && mod.deps.length) {
      sections.push(["dependencies", "Dependencies", mod.dep_count,
                     R.cards(mod.deps)]);
    }
    if (mod.versions && mod.versions.length) {
      sections.push(["versions", "Versions", mod.version_count,
                     R.versions(mod.versions, mod.versions_hidden, mod.mark)]);
    }
    // The panel is emitted empty and filled on first open. It has to exist up
    // front so the tab strip counts it and so a #comments link still lands
    // somewhere -- the count comes from the index, not from the file.
    if (mod.comments) {
      sections.push(["comments", "Comments", mod.comments,
                     '<div class="comment-slot">' +
                     '<p class="empty">Loading comments…</p></div>']);
    }

    var tabs = sections.length
      ? R.sectionTabs(sections)
      : '<section class="panel"><p class="empty">No description, versions, or ' +
        "comments were archived for this mod.</p></section>";

    // The crumbs and the <h1> are already in the page -- the build writes
    // them so a reader without JavaScript still gets them. This replaces the
    // container they sit in, so head() supplies the real heading block.
    return R.head(mod) + R.splitcols(mod) + tabs;
  }

  document.addEventListener("archive:rendered", function (event) {
    var mod = event.detail.record;
    R.setTitle(mod.name, mod.teaser);

    window.initTabs();

    var tabRoot = document.getElementById("mod-tabs");
    var panel = document.getElementById("comments");
    if (!tabRoot || !panel) return;

    // initTabs() fires this once for whichever tab the hash selects, so
    // arriving at #comments loads them without a second click.
    tabRoot.addEventListener("archive:tab", function (e) {
      if (e.detail.panel === "comments") window.loadComments(mod.id, panel);
    });
    if (!panel.hidden) window.loadComments(mod.id, panel);
  });

  R.detailPage("data/mod/", render,
               "That mod is not in the archive. It may never have been listed, " +
               "or it may have been removed before it could be captured.");
})();
