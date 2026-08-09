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

Plus the Forge's **user-curated mod lists** — 199 of them, each a set of mods
somebody ran together on a stated SPT version. That curation exists nowhere
else: no repository records which mods work as a pack.

And the images: mod thumbnails and author avatars are mirrored locally, because
they live on `forge-static.sp-tarkov.com` and die with the site.

Everything lands in `data/mods.json`, `data/comments/*.json`, `data/lists.json`
and `data/images/`. The site is rendered from those files, so the data is
usable on its own.

---

## Keeping it current

**Steps 1 and 5 now run themselves.** The `Refresh archive` workflow scrapes
mods and re-checks every source repository every two hours, commits both files,
and republishes the site — see [Automation](#automation) below. What is left to
run by hand is the part no schedule should own: comments, lists, and images.

Run these in order. `data/mods.json` is the spine — everything else reads it,
so it goes first. The rest are independent of each other.

```bash
python3 scrape/scrape_mods.py                  # 1. mods, versions, deps   (~1 min)
python3 scrape/fetch_images.py                 # 2. thumbnails for new mods (seconds)
python3 scrape/scrape_comments.py --probe      # 3. check comments still work
python3 scrape/scrape_comments.py --spt '4.'   #    new current-gen mods
python3 scrape/scrape_lists.py                 # 4. curated mod lists      (~3 min)
python3 scrape/repo_status.py                  # 5. repo activity          (~10 min)
python3 build/build.py                         # 6. preview locally        (~3 s)
git add -A && git commit -m "Refresh archive" && git push
```

**Step 6 is optional.** Pushing is what publishes: CI rebuilds `site/` from the
committed data and deploys it to Pages, and `site/` is gitignored precisely so
the generated output never has to be committed. Run `build.py` locally when you
want to see a change before it goes live (`python3 -m http.server -d site 8000`),
or to browse the archive offline — not to publish it.

Everything only fetches what changed, so a weekly run is roughly 15 minutes and
mostly unattended.

**Always `--probe` before a long comment run.** It exercises the whole Livewire
handshake against one known mod in about ten seconds. If it fails, the Forge
changed something and the parser needs fixing — don't start a multi-hour run.

**Never run two scrapers against the Forge at once.** They compete for the same
300 requests/minute and trigger 429s; sequential finishes sooner.

**As shutdown approaches, invert the priorities.** Mod data takes a minute to
re-pull at any time, but comments take hours and get exactly one chance.
Finishing the pre-4.x comment pass matters more than fresh download counts.

**After the Forge shuts down, drop steps 1–4.** `repo_status.py` and `build.py`
never contact sp-tarkov.com, so they keep working indefinitely — which is the
whole point: the listings die, the repositories do not.

A dead Forge cannot corrupt the archive. If enumeration returns nothing, or
returns only part of the catalogue, `scrape_mods.py` aborts *without writing*.
Running it after shutdown refuses rather than blanking your data.

Failures are never cached either. A mod that returns a 500 stays in the queue
for next time instead of being recorded as having no comments — so re-running
is always the correct response to errors.

---

## Automation

Two workflows. `build.yml` validates pull requests and publishes on push;
`refresh.yml` is the scheduled one, running **every two hours**:

```
scrape_mods.py  →  repo_status.py  →  commit  →  build.py  →  deploy to Pages
```

Mods first, because `repo_status.py` reads every source link out of
`data/mods.json` — so a mod added this run has its repository checked in the
same run rather than hours later. Both scrapes, the commit, and the deploy live
in one workflow on purpose: a push made with `GITHUB_TOKEN` does not trigger
other workflows, so committing data and expecting `build.yml` to notice would
publish nothing.

**Nothing here needs a personal access token.** `repo_status.py` runs on the
built-in `GITHUB_TOKEN`, which reads public repository data at 1,000
requests/hour — against roughly 26 GraphQL calls and 21 REST calls per run. The
`.github-sptmods` file is only for running it locally.

**The fetch cache is what makes two-hourly polite**, and it is committed for
exactly that reason. `data/raw_mods.jsonl` holds one raw payload per mod keyed
by `updated_at`, so a run refetches only what changed; without it every run
would be ~3,600 requests against a dying server, twelve times a day. Committing
it means the checkout restores it, with no Actions cache to expire or evict —
and it stops being "cheap to rebuild" the moment the Forge goes offline.

**It is compacted on every run** to one line per mod, sorted by id. Records are
*appended* as they arrive, which is what makes an interrupted run resumable,
but a refetched mod would otherwise leave its old record behind forever. The
compaction runs after the fetching, so both properties hold: crash-safe during
the run, and a clean line-per-mod diff at the end. In practice a run that
changes 20 mods adds roughly 40 KB to the repository.

**A failed scrape is not a failed run.** The scrape step is
`continue-on-error`, because `scrape_mods.py` aborts without writing rather
than truncating the archive — so the worst case is a run that republishes the
mod data already committed. That is also what every run will look like after
the shutdown, and it must not stop the repository status from refreshing.

**When the Forge goes offline**, delete the *Scrape the Forge* step and the two
cache steps around it from `refresh.yml`, and drop `data/mods.json` from the
commit step. Everything below them keeps working untouched. Two hours is also
far more often than dead repositories need checking — `0 6,18 * * *` is a
reasonable cadence to fall back to.

**`mods.json` is written sorted by id** so these commits stay small. Ordering
it by downloads instead moved a mod's entire record every time two of them
swapped rank, which turned a handful of changed counters into thousands of
changed lines on a file CI now commits twelve times a day. `build.py` sorts by
downloads at render time, so nothing on the site depends on the file's order —
the only visible difference is that `--limit N` on the scrapers now means "the
N lowest ids" rather than "the N most downloaded".

---

## The site

`build/build.py` renders a static site into `site/`:

```
site/index.html              the catalogue — search, filter, sort
site/mod/<id>-<slug>.html    one page per mod            (1,826)
site/lists.html              index of curated mod lists
site/list/<id>-<slug>.html   one page per list             (199)
site/all-mods.html           plain list, works without JavaScript
site/sitemap.xml             every page, with real last-modified dates
site/robots.txt              points crawlers at the sitemap
site/assets/                 one stylesheet, five small scripts, mirrored images
```

No framework and no dependency of any kind — plain Python and vanilla
JavaScript. Host it on GitHub Pages, or open the files off disk.

**The index** carries the whole catalogue inline, so filtering is instant and
works offline. Search covers mod names, authors, dependencies, GUIDs,
categories, repository names and URLs — typing `CommonLib` finds every mod that
needs it. Filter by category, Fika compatibility, dependencies, comments,
collection membership, and by **exact SPT version**: a panel of checkboxes
grouped by major line, defaulting to 4.x, with a whole-generation toggle per
group. Sort by downloads, release date, name, comments, stars, Fika-first or
collection-first. Filter state is remembered in the browser and reflected in
the URL, so a link shows the sender's view while your own saved state survives
a reload. Clicking any tag or author name filters by it.

**Each mod page** splits into tabs — Description, Dependencies, Versions,
Comments — with the key facts and every source repository side by side above
them. Dependencies are cards showing thumbnail, name and teaser, each addable
on its own. Comments are sorted (newest, oldest, most liked, most replies) and
searchable, filtering whole threads and highlighting matches, with replies
attached to the comment they answer.

**List pages** show a curated pack with each mod resolved to a working link,
and an *Add all to collection* button that toggles the whole set at once.

**Links between mods stay inside the archive.** Descriptions, version notes and
comments are full of links to other mods — on the Forge, and, in older text, on
the Hub that preceded it. Every one of those would be a dead end. Where the
archive holds the mod being linked to, `build/archive_links.py` rewrites the
link to its page here, fragment included, so `…/mod/902/bigbrain#versions`
lands on the Versions tab. Both id schemes are understood, since a mod that
predates the migration is linked by its Hub id in old comments; download URLs
resolve to the mod's page, which carries the repository the file lived in.
Around 3,400 links come home this way. Links naming a mod that was never
archived are left pointing at the dead site — that still records where the mod
used to live. Each mod page keeps one deliberate outbound link to its original
Forge page, as provenance.

---

## Collections

A collection is a set of mods you have marked, kept in the browser's
localStorage. There is no account and no server, which has consequences worth
stating plainly:

- clearing site data clears the collection; a share link is the only backup
- `file://` and the published site are separate origins and do not share one
- nothing is transmitted anywhere unless you copy a share link yourself

Mark mods from the index, a mod page, a list page, or `all-mods.html`. Adding a
mod also adds the dependencies its current version needs, shown indented under
it in the drawer. The drawer (top right) lists what you have, links each mod to
its releases page, and copies either every source URL or a share link.

**Share links** encode the mod ids into the URL itself, choosing whichever of
three encodings is shortest: a delta-varint list for small collections, a
bitset for large ones, and the *complement* for nearly-complete ones — which is
why "every mod in the archive" is about five characters. In practice: 5 mods
≈ 14 characters, 100 ≈ 138, and the worst case (around 500 mods) ≈ 485.

Ids are encoded, never list positions — positions shift whenever the catalogue
changes and would silently corrupt every link ever shared. Opening a link with
an empty collection imports it silently; otherwise it asks whether to merge or
replace, so a link can never destroy somebody's list.

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

Seven files, each with one job, handing off through files on disk so any of
them can be run alone — and so a half-finished run is never lost.

```
scrape_mods.py     ──→  data/mods.json       ──┐
scrape_comments.py ──→  data/comments/*.json  ─┤
fetch_images.py    ──→  data/images/          ─┼──→  build.py  ──→  site/
repo_status.py     ──→  data/repos.json       ─┤      (+ community.py
scrape_lists.py    ──→  data/lists.json       ─┤        validates submissions)
community/*.json   ──────────────────────────  ┘
```

Only the first three ever contact the Forge. `repo_status.py` talks to the code
hosts, and `build.py` talks to nothing at all.

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
that changed. Cold run ~25 minutes; warm run under a minute. That cache is
committed, and compacted to one sorted line per mod at the end of every run —
see [Automation](#automation).

### `scrape/scrape_comments.py`

Archives comment threads. **This is the fragile one** — see below.

```bash
python3 scrape/scrape_comments.py --probe          # verify it still works
python3 scrape/scrape_comments.py --spt '4.'       # current-gen mods first
python3 scrape/scrape_comments.py                  # everything else
python3 scrape/scrape_comments.py --max-age 30     # also refresh sets over 30 days old
python3 scrape/scrape_comments.py --fresh          # re-fetch every mod from scratch
```

Results are one file per mod, so an interrupted run keeps everything already
collected and a re-run picks up where it stopped. Budget several hours for a
full pass — the cost is pagination, at ten comments per request.

**Run `--probe` first.** It exercises the entire handshake against one
known-good mod and tells you whether the parser still matches the site.

**By default a mod is fetched only once.** That is what makes an interrupted
run resumable, but on its own it also means an archived mod never picks up new
comments. `--max-age DAYS` reopens that: thread sets older than the given age
are refetched, so a maintenance run stays incremental. `--fresh` re-fetches
everything and takes as long as the original pass — rarely what you want.

### `scrape/fetch_images.py`

Mirrors the images the Forge hosts, so they survive its shutdown.

```bash
python3 scrape/fetch_images.py              # thumbnails + avatars
python3 scrape/fetch_images.py --embedded   # also images inside descriptions
python3 scrape/fetch_images.py --no-resize  # keep originals instead of WebP
```

Only sp-tarkov hosts are mirrored, and the reason is simply which images are
about to disappear. Mod thumbnails and author avatars live on
`forge-static.sp-tarkov.com` and die with the Forge. The ~3,400 screenshots
embedded in descriptions sit on imgur, ibb, and GitHub — roughly **3.4 GB**, on
hosts with their own lifetimes — so they stay as external links by default.

Thumbnails are re-encoded to 192px WebP: the site shows them at 48px in the
list and 96px on a mod page, so this is a 2x retina copy and visually
identical. **2,198 images come to 8 MB**, against 121 MB at original size.

Files are content-addressed by URL hash, so re-running only fetches what is
new, and two mods sharing an author's avatar share one file. Pillow is used
here and *only* here — imported lazily, so neither `build.py` nor CI needs it.

`--embedded` is mostly of historical interest now: 74 of the 81 Forge-hosted
embedded images were already unreachable when this was written, because
`hub.sp-tarkov.com` is gone. They are unrecoverable by anyone.

### `scrape/scrape_lists.py`

Archives the Forge's curated mod lists into `data/lists.json`.

```bash
python3 scrape/scrape_lists.py            # every list
python3 scrape/scrape_lists.py --limit 5  # small test run
```

No API and no Livewire handshake needed: the list pages server-render their
mods, so this is ordinary HTML scraping — the index at `/lists`, then one
request per list. About three minutes for all 199.

Aborts without writing if enumeration comes back short, and keeps the previous
record for any single list whose fetch fails, so a partial run never shrinks
the archive.

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
python3 build/build.py                          # full build
python3 build/build.py --limit 30               # quick build while iterating
python3 build/build.py --base-url https://…     # serving from somewhere else
```

`--base-url` only affects `sitemap.xml`, which must carry absolute URLs. It
defaults to the GitHub Pages address, so change it if the site moves to a
custom domain.

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
- **`mods.sp-tarkov.com` file ids are not Hub file ids.** The site before the
  Hub numbered its files from 1 in its own sequence, so
  `mods.sp-tarkov.com/files/file/93-…` and `hub.sp-tarkov.com/files/file/93-…`
  are unrelated mods. `archive_links.py` rewrites Hub links and deliberately
  leaves the fifteen `mods.` ones alone: a link nobody can follow beats a link
  that confidently goes somewhere wrong.
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
- **`updated_at` is a database timestamp, not a mod update.** The Forge
  bulk-touches rows during migrations: 1,510 of 1,826 mods share just three
  such days, and the Forge's own pages display that date too. Anywhere the
  archive says when a mod last changed, it uses the newest version's publish
  date instead. The raw field is still kept in `mods.json`.
- **SPT constraints are ranges, not versions.** `~4.0 <4.1.0`, `>=3.8.0 <3.9`,
  `4.0.x`, `4.1.` and a bare `*` all occur. Only the first version in the
  string names the line a mod targets; splitting on "." lets the upper bound
  bleed in and produces labels like "4.0 <4". `spt_label()` normalises them.
- **Version and category counts are of distinct mods, never sums.** A mod
  supporting 4.0.13 and 4.1.0 belongs to both, so per-version counts cannot be
  added: 704 mods support some 4.x and 1,409 some 3.x, overlapping by 287 —
  which is exactly the 1,826 total.
- **`repos.json` is written for small diffs**, because CI commits it every two
  hours. Keys are sorted so a run that checks hosts in a different order does not
  reshuffle the file, and freshness is recorded once at the top rather than per
  repository. An earlier per-record `checked_at` rewrote all 1,346 entries on
  every run, burying the few repositories that had actually moved. A run where
  nothing changed now produces a two-line diff.
- **Archived HTML can trip GitHub's secret scanning.** Mod descriptions embed
  images that GitHub itself serves from S3 via pre-signed URLs carrying
  `X-Amz-Credential=AKIA…`. That is GitHub's own access key *id* — an
  identifier, not a credential, and the signature expires within hours — but
  push protection matches the shape and blocks the push. `scrub_signed_urls()`
  strips the signing parameters on write, keeping the URL itself, so a
  re-scrape can never reintroduce it. Note those parameters appear as `&amp;`
  in this HTML, not `&`; a scrubber matching only the bare form silently does
  nothing.

---

## Files

| Path | What it is |
|---|---|
| `site/` | **The thing you open.** Generated; gitignored, rebuilt by CI |
| `data/mods.json` | Every archived mod. The primary artifact |
| `data/comments/<id>.json` | Archived comment threads, one file per mod |
| `data/images/` | Mirrored thumbnails and avatars (content-addressed) |
| `data/images.json` | Image URL → local filename manifest |
| `data/lists.json` | Archived curated mod lists |
| `data/repos.json` | Source-repository activity |
| `data/raw_mods.jsonl` | Per-mod fetch cache: the raw API payloads (delete to refetch) |
| `community/*.json` | Mods contributed by pull request |
| `source_overrides.json` | Manual source-URL corrections |
| `scrape/forge.py` | Shared API client and the Livewire session |
| `build/sanitize.py` | HTML allowlist |
| `build/archive_links.py` | Forge/Hub links rewritten to archive pages |
| `build/templates.py` | Page rendering |

`data/mods.json`, `data/comments/`, `data/lists.json` and `data/images/`
**are** the archive — those are what to back up. `site/` regenerates from them,
and `repos.json` only costs time to rebuild.

`raw_mods.jsonl` is the exception among the caches: it is only cheap to rebuild
while the Forge is up. After that it is the raw payloads behind `mods.json` —
every field the Forge served, including the ones `build_record()` does not
keep — and unrecoverable by anyone. It is committed for that reason as much as
for CI's.

`site/` is gitignored on purpose: it is 1,826 generated files that would churn
on every build, and CI rebuilds and deploys it from the committed data. The
trade-off is that a broken commit to `data/` takes the live site down until the
next green run — pull requests are checked by the `validate` job, but direct
pushes are not.
