#!/usr/bin/env python3
"""Check when each archived mod's source repository was last updated.

    python3 scrape/repo_status.py                # refresh anything over 12h old
    python3 scrape/repo_status.py --max-age 0    # force a full re-check
    python3 scrape/repo_status.py --limit 20     # small test run

Reads data/mods.json and data/addons.json, and talks **only to the code
hosts** -- never to the Forge -- so this keeps working indefinitely after
the listing site goes offline. That is the point of it: the listing is
what disappears, while the repositories are what the archive ultimately exists
to point at.

Every source link is checked, not just the first. Mods that ship a separate
client and server repo, or one repo per SPT generation, have more than one, and
the interesting question -- "is any of this still maintained?" -- is not
answerable from the first URL alone.

GitHub goes through the GraphQL API, which answers 50 repos per request.
GitLab, Codeberg, and Gitea use their own REST APIs and need no auth. Results
cache in data/repos.json; re-running is cheap.

Token: $GITHUB_TOKEN, else --token-file, else .github-sptmods in this project
or your home directory. Only public data is requested, so a token with no
scopes and no repository access is sufficient -- it exists purely to raise the
rate limit from 60/hour to 5,000/hour.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
UA = "spt-mod-archive (personal mod tracker)"
BATCH = 50          # repos per GraphQL query
GITEA_HOSTS = {"codeberg.org", "gitea.com"}

# Hosts that no longer serve anything. dev.sp-tarkov.com was the SPT team's own
# Gitea and is gone -- it now 301s to github.com/sp-tarkov. Probing it means
# three timeouts per repo, so 25 dead links used to stall a run for an hour.
# Recording them as gone immediately is both faster and more truthful.
DEAD_HOSTS = {"dev.sp-tarkov.com", "hub.sp-tarkov.com"}

# Hosts that are real but are not code forges, so there is no commit to read.
NOT_A_FORGE = {"drive.google.com", "virustotal.com", "mega.nz", "mediafire.com"}


# --- token ---------------------------------------------------------------

def read_token(explicit):
    if os.environ.get("GITHUB_TOKEN"):
        return os.environ["GITHUB_TOKEN"].strip()
    for path in filter(None, [explicit,
                              os.path.join(HERE, ".github-sptmods"),
                              os.path.expanduser("~/.github-sptmods")]):
        if os.path.isfile(path):
            with open(path) as f:
                return f.read().strip()
    return None


# --- repo URL parsing ----------------------------------------------------

def parse_repo(url):
    """Reduce a source URL to the repository it belongs to.

    Handles the messy shapes real listings contain: /tree/<branch>,
    /releases/tag/<v>, deep subpaths, and trailing .git. Returns None when no
    repository can be named.
    """
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    parts = [s for s in parsed.path.strip("/").split("/") if s]
    if len(parts) < 2:
        return None

    owner, name = parts[0], parts[1].removesuffix(".git")

    # A /tree/<ref> URL names the branch the mod actually ships from, which is
    # not always the repository's default branch.
    ref = None
    if len(parts) > 3 and parts[2] in ("tree", "blob", "src"):
        ref = parts[3]

    return {"host": host, "owner": owner, "name": name, "ref": ref,
            "full_name": f"{owner}/{name}", "url": url,
            "path": parsed.path.strip("/")}


# --- GitHub (GraphQL) ----------------------------------------------------

# Three things are asked of releases, and they cost very differently.
#
# Every tag is wanted, so a mod version can be linked to the release that
# shipped it -- but only the tag and its date are stored, because a release
# page URL is derivable from the repository and the tag, and storing 40 URLs
# per repository would add megabytes to a file CI commits eight times a day.
#
# Assets are fetched in full for the latest release: their size and download
# URL, because that is the release a reader is most likely to install.
#
# The five newest releases additionally give up their asset *filenames*, which
# is what lets a collection pin an older version to a file rather than to a
# landing page. Names alone, because on every host here the download URL is
# `<repo>/releases/download/<tag>/<name>` -- see templates.asset_url(). Five,
# because a name is ~26 bytes and 40 of them per repository is the megabyte
# the paragraph above is about. They accumulate: `carry_release_files()` keeps
# what earlier runs learned, so the covered set grows with every release cut
# rather than being capped at five forever.
REPO_FIELDS = """
    nameWithOwner isArchived stargazerCount pushedAt url
    defaultBranchRef { name target { ... on Commit {
        oid committedDate messageHeadline url } } }
    latestRelease { tagName publishedAt url descriptionHTML
        releaseAssets(first: 5) { nodes { name downloadUrl size } } }
    releases(first: 40, orderBy: {field: CREATED_AT, direction: DESC}) {
        nodes { tagName publishedAt } }
    recent: releases(first: 5, orderBy: {field: CREATED_AT, direction: DESC}) {
        nodes { tagName releaseAssets(first: 3) { nodes { name } } } }"""

PINNED_FIELD = """
    pinned: ref(qualifiedName: %s) { name target { ... on Commit {
        oid committedDate messageHeadline url } } }"""


def with_files(releases, by_tag):
    """Attach asset filenames to the release rows we have them for.

    `by_tag` covers the newest few releases only, so most rows come back
    untouched. A row with no files is not given an empty list -- an absent key
    is a byte cheaper across thousands of rows, and reads correctly as "not
    known" rather than "this release shipped nothing".

    GitLab is the exception and stores whole URLs here, because its asset links
    are arbitrary rather than built from the tag. templates.asset_url() tells
    the two apart by looking for a scheme.
    """
    for release in releases:
        files = by_tag.get(release["tag"]) or []
        if files:
            release["files"] = files
    return releases


def carry_release_files(old, new):
    """Keep the filenames earlier runs learned, for releases now out of reach.

    Only the five newest releases are asked for their assets, so a repository
    that has cut ten releases since the archive started would otherwise know
    the files for the newest five and have silently forgotten the rest. Every
    run merges what it already had, which is what makes five-at-a-time add up
    to full coverage over time.

    The new fetch always wins where both have an answer: a release's assets can
    be replaced after publication, and the fresh read is the true one.
    """
    if not (old and new) or new.get("status") != "ok":
        return new
    known = {release.get("tag"): release.get("files")
             for release in old.get("releases") or []
             if release.get("files")}
    if not known:
        return new
    for release in new.get("releases") or []:
        if "files" not in release and known.get(release.get("tag")):
            release["files"] = known[release["tag"]]
    return new


def store(cache, url, record):
    """One way into the cache, so nothing lands there unmerged."""
    cache[url] = carry_release_files(cache.get(url), record)


def build_query(entries):
    parts = []
    for i, entry in enumerate(entries):
        pinned = (PINNED_FIELD % json.dumps(entry["ref"])) if entry["ref"] else ""
        parts.append('  r%d: repository(owner: %s, name: %s) {%s%s\n  }' % (
            i, json.dumps(entry["owner"]), json.dumps(entry["name"]),
            REPO_FIELDS, pinned))
    return "query {\n" + "\n".join(parts) + "\n}"


def graphql(token, query, attempts=4):
    body = json.dumps({"query": query}).encode()
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(
                "https://api.github.com/graphql", data=body,
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": "application/json", "User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (403, 429, 500, 502, 503, 504):
                time.sleep(2 ** attempt * 3)
                continue
            raise
        except Exception:
            if attempt == attempts - 1:
                raise
            time.sleep(2 ** attempt * 2)
    return None


def commit_of(node):
    target = (node or {}).get("target") or {}
    if not target.get("committedDate"):
        return None
    return {"date": target["committedDate"],
            "message": target.get("messageHeadline", ""),
            "sha": (target.get("oid") or "")[:10],
            "url": target.get("url", "")}


def fetch_github(token, entries):
    """Returns {source_url: record}. Missing repos get status 'not_found'."""
    out = {}
    for start in range(0, len(entries), BATCH):
        chunk = entries[start:start + BATCH]
        data = graphql(token, build_query(chunk))
        payload = (data or {}).get("data") or {}

        for i, entry in enumerate(chunk):
            node = payload.get(f"r{i}")
            if not node:
                out[entry["url"]] = missing_record(entry)
                continue

            # Prefer the branch the URL pinned; fall back to the default.
            commit = commit_of(node.get("pinned")) or \
                commit_of(node.get("defaultBranchRef"))
            release = node.get("latestRelease") or {}

            out[entry["url"]] = {
                "url": entry["url"], "host": entry["host"],
                "full_name": node.get("nameWithOwner", entry["full_name"]),
                "status": "ok",
                "archived": bool(node.get("isArchived")),
                "stars": node.get("stargazerCount", 0),
                "branch": entry["ref"] or
                          (node.get("defaultBranchRef") or {}).get("name", ""),
                "commit": commit,
                "release": {"tag": release.get("tagName", ""),
                            "date": release.get("publishedAt", ""),
                            "url": release.get("url", ""),
                            "html": release.get("descriptionHTML", ""),
                            "assets": [
                                {"name": a.get("name", ""),
                                 "url": a.get("downloadUrl", ""),
                                 "size": a.get("size") or 0}
                                for a in (release.get("releaseAssets") or {})
                                          .get("nodes") or []
                                if a.get("downloadUrl")]}
                           if release else None,
                "releases": with_files(
                    [{"tag": r.get("tagName", ""),
                      "date": r.get("publishedAt", "")}
                     for r in (node.get("releases") or {}).get("nodes") or []
                     if r.get("tagName")],
                    {r.get("tagName", ""):
                        [a.get("name", "") for a
                         in (r.get("releaseAssets") or {}).get("nodes") or []
                         if a.get("name")]
                     for r in (node.get("recent") or {}).get("nodes") or []}),
            }

        print(f"  github {min(start + BATCH, len(entries))}/{len(entries)}",
              file=sys.stderr)
    return out


# --- GitLab / Gitea (REST, no auth needed) -------------------------------

def get_json(url, attempts=3):
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2 ** attempt)
        except Exception:
            time.sleep(2 ** attempt)
    return None


def missing_record(entry):
    return {"url": entry["url"], "host": entry["host"],
            "full_name": entry.get("full_name") or entry.get("path", ""),
            "status": "not_found"}


def fetch_gitlab(entry):
    project = urllib.parse.quote(entry["path"], safe="")
    base = f"https://gitlab.com/api/v4/projects/{project}"
    commits = get_json(f"{base}/repository/commits?per_page=1")
    if commits is None:
        return missing_record(entry)

    commit = commits[0] if commits else {}
    # Same 20 as GitHub, so a mod's older versions can be linked whichever
    # host it lives on.
    releases = get_json(f"{base}/releases?per_page=40") or []
    release = releases[0] if releases else {}
    links = ((release.get("assets") or {}).get("links") or []) if release else []
    return {
        "url": entry["url"], "host": entry["host"], "full_name": entry["path"],
        "status": "ok", "archived": False, "stars": 0, "branch": "",
        "commit": {"date": commit.get("created_at", ""),
                   "message": commit.get("title", ""),
                   "sha": (commit.get("id") or "")[:10],
                   "url": commit.get("web_url", "")} if commit else None,
        "release": {"tag": release.get("tag_name", ""),
                    "date": release.get("released_at", ""),
                    "url": entry["url"],
                    "html": release.get("description_html", ""),
                    "assets": [{"name": l.get("name", ""),
                                "url": l.get("url", ""), "size": 0}
                               for l in links if l.get("url")]}
                   if release else None,
        # Whole URLs, not names: a GitLab release links assets wherever the
        # author pointed them, so there is nothing to rebuild them from.
        "releases": with_files(
            [{"tag": r.get("tag_name", ""), "date": r.get("released_at", "")}
             for r in releases if r.get("tag_name")],
            {r.get("tag_name", ""):
                [l.get("url", "") for l
                 in ((r.get("assets") or {}).get("links") or []) if l.get("url")]
             for r in releases[:5]}),
    }


def fetch_gitea(entry):
    base = f"https://{entry['host']}/api/v1/repos/{entry['owner']}/{entry['name']}"
    commits = get_json(f"{base}/commits?limit=1")
    if commits is None:
        return missing_record(entry)

    commit = commits[0] if commits else {}
    info = commit.get("commit", {}) if commit else {}
    releases = get_json(f"{base}/releases?limit=40") or []
    release = releases[0] if releases else {}
    return {
        "url": entry["url"], "host": entry["host"],
        "full_name": entry["full_name"], "status": "ok",
        "archived": False, "stars": 0, "branch": "",
        "commit": {"date": (info.get("author") or {}).get("date", ""),
                   "message": (info.get("message") or "").splitlines()[0][:200],
                   "sha": (commit.get("sha") or "")[:10],
                   "url": commit.get("html_url", "")} if commit else None,
        "release": {"tag": release.get("tag_name", ""),
                    "date": release.get("published_at", ""),
                    "url": release.get("html_url", ""), "html": "",
                    "assets": [{"name": a.get("name", ""),
                                "url": a.get("browser_download_url", ""),
                                "size": a.get("size") or 0}
                               for a in release.get("assets") or []
                               if a.get("browser_download_url")]}
                   if release else None,
        "releases": with_files(
            [{"tag": r.get("tag_name", ""), "date": r.get("published_at", "")}
             for r in releases if r.get("tag_name")],
            {r.get("tag_name", ""):
                [a.get("name", "") for a in r.get("assets") or [] if a.get("name")]
             for r in releases[:5]}),
    }


# --- cache ---------------------------------------------------------------

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def age_hours(stamp):
    try:
        when = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return 1e9
    return (datetime.now(timezone.utc) - when).total_seconds() / 3600


def load_cache(path):
    """Returns (repos, generated_at). Missing or corrupt reads as empty."""
    if not os.path.exists(path):
        return {}, None
    with open(path) as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            return {}, None
    return data.get("repos", {}), data.get("generated_at")


def save_cache(path, cache):
    """Write the cache so that unchanged repos produce no diff.

    Two things make that work, and both matter because this file is committed
    every two hours by CI. Keys are sorted, so a run that checks hosts in
    a different order does not reshuffle the file. And freshness is recorded
    once at the top rather than per repo -- a per-record `checked_at` rewrote
    all 1,346 entries on every run, which buried the handful of repositories
    that had actually moved and made the file's history unreadable.
    """
    with open(path, "w") as f:
        json.dump({"generated_at": now_iso(), "repo_count": len(cache),
                   "repos": cache}, f, indent=1, sort_keys=True)


# --- main ----------------------------------------------------------------

def source_urls(records):
    """Every distinct source URL in the archive, with what uses it.

    Mods and addons are both accepted: an addon record carries the same
    `source_links` field, and its repository outlives the Forge for exactly
    the same reason a mod's does. Several addons live in the repository of the
    mod they extend, so the same URL legitimately appears under both -- which
    is why this keys by URL and collects the names against it.
    """
    urls = {}
    for record in records:
        for link in record["source_links"]:
            urls.setdefault(link["url"], []).append(record["name"])
    return urls


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mods", default=os.path.join(DATA, "mods.json"))
    ap.add_argument("--addons", default=os.path.join(DATA, "addons.json"))
    ap.add_argument("--cache", default=os.path.join(DATA, "repos.json"))
    ap.add_argument("--token-file")
    ap.add_argument("--max-age", type=float, default=12.0,
                    help="reuse cached results younger than this many hours")
    ap.add_argument("--limit", type=int, help="only check the first N repos")
    args = ap.parse_args()

    token = read_token(args.token_file)
    if not token:
        print("No GitHub token found. Set $GITHUB_TOKEN or create "
              ".github-sptmods.\nOnly public data is read, so a token with no "
              "scopes is enough.", file=sys.stderr)
        return 1

    if not os.path.exists(args.mods):
        sys.exit(f"{args.mods} not found — run scrape/scrape_mods.py first")
    with open(args.mods) as f:
        records = json.load(f)["mods"]

    # Optional: the archive predates addons, and scrape_addons.py may simply
    # not have been run. Their repositories are checked the same way.
    if os.path.exists(args.addons):
        with open(args.addons) as f:
            addons = json.load(f)["addons"]
        print(f"{len(addons)} addons included", file=sys.stderr)
        records = records + addons

    entries, unparsed = {}, []
    for url in source_urls(records):
        info = parse_repo(url)
        if info:
            entries[url] = info
        else:
            unparsed.append(url)

    cache, generated_at = load_cache(args.cache)

    # Freshness is now a property of the whole file rather than of each repo.
    # That is honest about what actually happens: every run re-checks every
    # repo, so they were always the same age -- the per-record timestamps
    # tracked nothing extra and rewrote the file on every run. A repo we have
    # never seen is fetched regardless of how recent the file is.
    stale = age_hours(generated_at) >= args.max_age
    todo = [e for e in entries.values() if stale or e["url"] not in cache]
    fresh = len(entries) - len(todo)
    if args.limit:
        todo = todo[:args.limit]

    print(f"{len(entries)} repos across {len(records)} mods and addons; "
          f"{fresh} cached, {len(entries) - fresh} stale", file=sys.stderr)
    if unparsed:
        print(f"{len(unparsed)} URL(s) name no repo, e.g. {unparsed[0]}",
              file=sys.stderr)

    github = [e for e in todo if e["host"] == "github.com"]
    gitlab = [e for e in todo if e["host"] == "gitlab.com"]
    gitea = [e for e in todo if e["host"] in GITEA_HOSTS]
    dead = [e for e in todo if e["host"] in DEAD_HOSTS]
    not_forge = [e for e in todo if e["host"] in NOT_A_FORGE]
    handled = {id(e) for e in github + gitlab + gitea + dead + not_forge}
    other = [e for e in todo if id(e) not in handled]

    for entry in dead:
        store(cache, entry["url"],
              {**missing_record(entry), "status": "host_gone"})
    for entry in not_forge:
        store(cache, entry["url"],
              {**missing_record(entry), "status": "not_a_repo"})
    if dead:
        print(f"  {len(dead)} link(s) on hosts that no longer exist",
              file=sys.stderr)

    if github:
        for url, record in fetch_github(token, github).items():
            store(cache, url, record)
        # Persist before the slow serial hosts: losing a completed GitHub pass
        # to a timeout further down would mean redoing all of it.
        save_cache(args.cache, cache)

    for entry in gitlab:
        store(cache, entry["url"], fetch_gitlab(entry))
    for entry in gitea:
        store(cache, entry["url"], fetch_gitea(entry))
    for entry in other:
        print(f"  skipped unsupported host: {entry['host']}", file=sys.stderr)

    save_cache(args.cache, cache)

    resolved = [r for r in cache.values() if r.get("status") == "ok"]
    missing = [r for r in cache.values() if r.get("status") == "not_found"]
    archived = [r for r in resolved if r.get("archived")]
    dated = sorted((r for r in resolved if (r.get("commit") or {}).get("date")),
                   key=lambda r: r["commit"]["date"], reverse=True)

    print(f"\nResolved:  {len(resolved)}", file=sys.stderr)
    print(f"Not found: {len(missing)}", file=sys.stderr)
    print(f"Archived:  {len(archived)}", file=sys.stderr)
    if dated:
        print(f"Newest commit: {dated[0]['commit']['date'][:10]}  "
              f"{dated[0]['full_name']}", file=sys.stderr)
        print(f"Oldest commit: {dated[-1]['commit']['date'][:10]}  "
              f"{dated[-1]['full_name']}", file=sys.stderr)
    for record in missing[:8]:
        print(f"  missing: {record['url']}", file=sys.stderr)

    print(f"\nWrote {args.cache}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
