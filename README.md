# SPT Mod Archive

A community archive of the Single Player Tarkov mod listings from
[forge.sp-tarkov.com](https://forge.sp-tarkov.com), built because the Forge is
shutting down.

The Forge is where mods were *listed*; the repositories are where they *live*.
Once the listings are gone the code still exists but becomes very hard to find,
and everything wrapped around it — which mod needs which, whether something
works in Fika co-op, and the years of comments where the actual troubleshooting
happened — disappears completely. This archives all of it.

**Open `site/index.html` in a browser.** No server, no internet, no build step.

---

## What is archived

Every mod on the Forge, regardless of SPT version, including long-dead 3.x
mods that nothing else preserves. For each one:

- name, authors, teaser, and the full rendered description
- **every** source repository, not just the first — mods that ship a separate
  client and server repo, or one repo per SPT generation, keep both, each with
  the label the Forge gave it
- **Fika compatibility**, at both mod and per-version level
- category, matching the Forge's own taxonomy
- complete version history: version, SPT constraint, release notes, downloads,
  Fika status, and dependencies per version
- dependencies, linked to their own page in the archive
- downloads, favourites, license, publish and update dates
- author notices: contains ads, AI content, cheat warnings, profile binding
- **the comment threads**, with authors, timestamps, likes, and reply nesting

Everything lands in `data/mods.json` and `data/comments/*.json`. The site is
rendered from those files, so the data is usable on its own.

---

## Daily use

```bash
python3 scrape/scrape_mods.py        # refresh mod listings from the Forge
python3 scrape/scrape_comments.py    # archive comment threads
python3 scrape/repo_status.py        # check the source repos (not the Forge)
python3 build/build.py               # rebuild site/
```

All four are safe to re-run and only fetch what changed. **After the Forge shuts
down, drop the first two.** `repo_status.py` and `build.py` never contact
sp-tarkov.com, so they keep working indefinitely — which is the point: the
listings die, the repositories do not.

If the Forge returns nothing (i.e. it is gone), the scraper aborts *without
writing*, so a dead site can never blank the archive.

---

## The site

`build/build.py` renders a static site into `site/`:

```
site/index.html              the catalogue — search, filter, sort
site/mod/<id>-<slug>.html    one page per mod
site/all-mods.html           plain list, works without JavaScript
site/assets/                 one stylesheet, two small scripts
```

There is no framework and no dependency of any kind — everything is plain
Python and vanilla JavaScript. Host it on GitHub Pages, or open the files
directly off disk; both work identically.

**The index** carries the whole catalogue inline, so filtering is instant and
works offline. You can search across mod names, authors, dependencies, GUIDs,
categories, and repo URLs — typing `CommonLib` finds every mod that needs it.
Filter by category, SPT line, Fika compatibility, whether a mod has
dependencies or comments; sort by downloads, update date, name, comment count,
or Fika-first. Filters are reflected in the URL, so any view can be linked.

**Each mod page** carries everything above, with dependencies linked to their
own pages, and the comments in a collapsible section — collapsed by default,
newest first, with sorting (newest, oldest, most liked, most replies) and a
search box that filters whole threads and highlights matches. Replies stay
attached to the comment they answer.

---

## Adding a mod after the Forge is gone

Two ways, both documented in [`community/README.md`](community/README.md):

- **Open an issue** using the *Add a mod* template and fill in the form.
- **Open a pull request** adding one small JSON file to `community/`. Copy
  `community/_template.json`, fill in four required fields, run
  `python3 build/community.py` to check it, and submit.

CI validates every submission and rebuilds the site on merge. Community mods
are shown with a *Community* badge and sit alongside archived ones, using the
same categories.

---

## The scripts

Four files, each with one job, handing off through files on disk so any of them
can be run alone.

```
scrape_mods.py     ──→  data/mods.json      ──┐
scrape_comments.py ──→  data/comments/*.json ─┼──→  build.py  ──→  site/
community/*.json   ─────────────────────────  ┘
```

### `scrape/scrape_mods.py`

Pulls every mod from the Forge's public JSON API.

```bash
python3 scrape/scrape_mods.py                # everything (~1,800 mods)
python3 scrape/scrape_mods.py --spt '4.*'    # only mods matching a filter
python3 scrape/scrape_mods.py --limit 20     # small test run
python3 scrape/scrape_mods.py --fresh        # ignore the cache
```

Three passes: enumerate mods (50/page), then per mod fetch the detail endpoint
(the only source of the full description) and the versions endpoint (the only
source of dependencies and the complete version history). Per-mod results cache
in `data/raw_mods.jsonl` keyed by `updated_at`, so re-runs only refetch mods
that changed. Cold run ~25 minutes; warm run under a minute.

### `scrape/scrape_comments.py`

Archives comment threads. **This is the fragile one** — see below.

```bash
python3 scrape/scrape_comments.py --probe          # verify it still works
python3 scrape/scrape_comments.py --spt '4.'       # current-gen mods first
python3 scrape/scrape_comments.py                  # everything else
python3 scrape/scrape_comments.py --fresh          # re-fetch mods already done
```

Results are one file per mod, so an interrupted run keeps everything already
collected and a re-run picks up where it stopped. Budget several hours for a
full pass — the cost is pagination, at ten comments per request.

**Run `--probe` first.** It exercises the entire handshake against one
known-good mod and tells you whether the parser still matches the site.

### `scrape/repo_status.py`

Checks when each source repository was last updated. **Never contacts the
Forge**, so this is the script that stays useful forever.

```bash
python3 scrape/repo_status.py               # refresh anything over 12h old
python3 scrape/repo_status.py --max-age 0   # force a full re-check
python3 scrape/repo_status.py --limit 20    # small test run
```

Every source link is checked, not just the first — a mod with separate client
and server repos has two, and "is any of this still maintained?" cannot be
answered from one URL. GitHub goes through GraphQL at 50 repos per request;
GitLab, Codeberg, and Gitea use their own REST APIs and need no auth. Results
land in `data/repos.json` and appear on each mod page as last commit, latest
release, stars, and whether the author archived the repo.

Needs a GitHub token — see below.

### `build/build.py`

Renders `site/`. Never touches the network.

```bash
python3 build/build.py               # full build
python3 build/build.py --limit 30    # quick build while iterating
```

### `build/community.py`

Validates community submissions; also runs as part of the build.

```bash
python3 build/community.py           # check every submission
```

---

## GitHub token

Required only by `repo_status.py`, purely to raise the rate limit from
**60/hour to 5,000/hour**. Every field requested is public, so the token needs
**no scopes and no repository access**.

Create either a fine-grained token with "Public Repositories (read-only)" and no
permissions enabled, or a classic token with every scope left unchecked.

It is read from `$GITHUB_TOKEN`, else `--token-file`, else `.github-sptmods` in
this folder or your home directory. Keep it `chmod 600` and never commit it.

Check it is being picked up without revealing it:

```bash
curl -s -H "Authorization: Bearer $(cat .github-sptmods)" \
  https://api.github.com/rate_limit | grep -o '"limit":[0-9]*' | head -1
```

`"limit":5000` is good. `"limit":60` means it is not being read.

---

## Fixing a bad source link

Some mods point at repositories that are dead, moved, or simply wrong. Put
corrections in `source_overrides.json`, keyed by the mod's `id`:

```json
{
  "1277": {
    "source_code_url": "https://github.com/sgtlaggy/spt-HeadVoiceSelector-server",
    "note": "why you changed it"
  }
}
```

These are applied on every scrape, so they survive re-runs — editing
`mods.json` by hand would not. The corrected URL is added *in front of* the
original rather than replacing it: a dead link is still evidence of where a mod
used to live.

---

## Notes and gotchas

Things learned the hard way, worth knowing before changing anything.

- **The mods API needs an explicit `sort`.** Its default ordering is not
  unique, so rows shift between pages and mods get silently duplicated *and*
  skipped. An early version of this collected 681 rows covering only 520
  distinct mods.
- **The versions endpoint 500s if you pass `sort`** — the one place you cannot
  do the above. Ordering is imposed after the fetch instead.
- **`per_page` caps at 50** whatever you ask for, and inline `versions` caps at
  10 per mod. The full history only comes from `/mod/{id}/versions`.
- **Dependencies exist only on `/mod/{id}/versions`**, and are declared *per
  version* — a mod may have gained or dropped one over time, so the archive
  keeps both the latest version's dependencies and the union across all of them.
- **A dropped request looks exactly like an empty result.** This is the single
  biggest hazard in the whole project: a rate-limited run will happily record
  hundreds of mods as having no versions and no dependencies. Every fetch here
  returns an explicit success flag, a partly-fetched mod is never cached, and
  the run aborts rather than writing a truncated archive.
- **Comments have no API.** They are rendered by a Livewire component the page
  loads lazily, so archiving them means performing the browser's handshake:
  fetch the mod page for a session cookie, CSRF token, the build-hashed
  endpoint (`/livewire-<hash>/update`), and a signed component snapshot; POST
  that snapshot back with a `__lazyLoad` call; then page with
  `gotoPage(n, 'commentPage')`. None of it is a public interface and the
  checksum cannot be forged, only replayed.
- **Comment pagination belongs to a *nested* component.** Calling `gotoPage` on
  the outer comments tab returns HTTP 500. The pager's snapshot only exists
  inside the HTML the lazy load returns.
- **The Forge's comment count excludes replies.** "46 results" means 46
  top-level comments; this archive stores 136 for that mod once replies are
  included. `--probe` compares against the top-level count for exactly this
  reason.
- **Forge HTML is re-hosted, so it is sanitised.** Descriptions and comments are
  other people's markup, and serving it from another origin means we cannot
  inherit the Forge's guarantees. `build/sanitize.py` runs a strict allowlist:
  unknown tags dropped, every attribute named explicitly, `javascript:` URLs
  rejected including control-character bypasses like `java&#09;script:`.
  Video embeds, which are bare divs carrying a data attribute, become ordinary
  links so the reference is not silently lost.
- **Rate limit is 300 requests/minute.** The scraper sleeps 1s per worker
  between requests, landing near 240/min with headroom for retries, and honours
  `Retry-After` when it still gets a 429.

---

## Files

| Path | What it is |
|---|---|
| `site/` | **The thing you open.** Generated; safe to delete and rebuild |
| `data/mods.json` | Every archived mod. The primary artifact |
| `data/comments/<id>.json` | Archived comment threads, one file per mod |
| `data/raw_mods.jsonl` | Per-mod fetch cache (delete to force a refetch) |
| `community/*.json` | Mods contributed by pull request |
| `source_overrides.json` | Manual source-URL corrections |
| `scrape/forge.py` | Shared API client and the Livewire session |
| `build/sanitize.py` | HTML allowlist |
| `build/templates.py` | Page rendering |

Both caches are safe to delete; they only cost time to rebuild. `data/mods.json`
and `data/comments/` are the archive itself — those are the ones to back up.
