#!/usr/bin/env python3
"""Check when each archived mod's source repository was last updated.

    python3 scrape/repo_status.py                # refresh anything over 12h old
    python3 scrape/repo_status.py --max-age 0    # force a full re-check
    python3 scrape/repo_status.py --limit 20     # small test run

Reads data/mods.json and talks **only to the code hosts** -- never to the
Forge -- so this keeps working indefinitely after forge.sp-tarkov.com goes
offline. That is the point of it: the Forge listing is what disappears, while
the repositories are what the archive ultimately exists to point at.

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

REPO_FIELDS = """
    nameWithOwner isArchived stargazerCount pushedAt url
    defaultBranchRef { name target { ... on Commit {
        oid committedDate messageHeadline url } } }
    latestRelease { tagName publishedAt url descriptionHTML }"""

PINNED_FIELD = """
    pinned: ref(qualifiedName: %s) { name target { ... on Commit {
        oid committedDate messageHeadline url } } }"""


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
                            "html": release.get("descriptionHTML", "")}
                           if release else None,
                "checked_at": now_iso(),
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
            "status": "not_found", "checked_at": now_iso()}


def fetch_gitlab(entry):
    project = urllib.parse.quote(entry["path"], safe="")
    base = f"https://gitlab.com/api/v4/projects/{project}"
    commits = get_json(f"{base}/repository/commits?per_page=1")
    if commits is None:
        return missing_record(entry)

    commit = commits[0] if commits else {}
    releases = get_json(f"{base}/releases?per_page=1") or []
    release = releases[0] if releases else {}
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
                    "html": release.get("description_html", "")}
                   if release else None,
        "checked_at": now_iso(),
    }


def fetch_gitea(entry):
    base = f"https://{entry['host']}/api/v1/repos/{entry['owner']}/{entry['name']}"
    commits = get_json(f"{base}/commits?limit=1")
    if commits is None:
        return missing_record(entry)

    commit = commits[0] if commits else {}
    info = commit.get("commit", {}) if commit else {}
    releases = get_json(f"{base}/releases?limit=1") or []
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
                    "url": release.get("html_url", ""), "html": ""}
                   if release else None,
        "checked_at": now_iso(),
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
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        try:
            return json.load(f).get("repos", {})
        except json.JSONDecodeError:
            return {}


def save_cache(path, cache):
    with open(path, "w") as f:
        json.dump({"generated_at": now_iso(), "repo_count": len(cache),
                   "repos": cache}, f, indent=1)


# --- main ----------------------------------------------------------------

def source_urls(mods):
    """Every distinct source URL in the archive, with the mods that use it."""
    urls = {}
    for mod in mods:
        for link in mod["source_links"]:
            urls.setdefault(link["url"], []).append(mod["name"])
    return urls


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mods", default=os.path.join(DATA, "mods.json"))
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
        mods = json.load(f)["mods"]

    entries, unparsed = {}, []
    for url in source_urls(mods):
        info = parse_repo(url)
        if info:
            entries[url] = info
        else:
            unparsed.append(url)

    cache = load_cache(args.cache)
    todo = [e for e in entries.values()
            if age_hours((cache.get(e["url"]) or {}).get("checked_at"))
            >= args.max_age]
    fresh = len(entries) - len(todo)
    if args.limit:
        todo = todo[:args.limit]

    print(f"{len(entries)} repos across {len(mods)} mods; "
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
        cache[entry["url"]] = {**missing_record(entry), "status": "host_gone"}
    for entry in not_forge:
        cache[entry["url"]] = {**missing_record(entry), "status": "not_a_repo"}
    if dead:
        print(f"  {len(dead)} link(s) on hosts that no longer exist",
              file=sys.stderr)

    if github:
        cache.update(fetch_github(token, github))
        # Persist before the slow serial hosts: losing a completed GitHub pass
        # to a timeout further down would mean redoing all of it.
        save_cache(args.cache, cache)

    for entry in gitlab:
        cache[entry["url"]] = fetch_gitlab(entry)
    for entry in gitea:
        cache[entry["url"]] = fetch_gitea(entry)
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
