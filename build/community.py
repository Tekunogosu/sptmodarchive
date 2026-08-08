"""Community-submitted mods: validation and normalisation.

Once the Forge is gone there is no API to scrape, so new mods arrive as small
JSON files in community/, one per mod, added by pull request. This module is
the contract for those files. It is also runnable on its own, which is what
CI uses to check a PR:

    python3 build/community.py            # validate every submission
    python3 build/community.py FILE...    # validate specific files

Submissions are deliberately much smaller than a scraped record -- a
contributor should not have to invent fields like `hub_id`. Everything the
site needs but the author did not supply is filled in with a neutral default,
so a community record and a Forge record are the same shape by the time the
templates see them.

Validation errors name the file, the field, and what was expected, because the
person reading them is a mod author who has never seen this repository.
"""

import glob
import json
import os
import re
import sys

REQUIRED = ("name", "authors", "teaser", "source_links")

# Kept in step with the Forge's own categories so community mods file
# alongside archived ones rather than forming a separate taxonomy.
KNOWN_CATEGORIES = {
    "audio", "bots", "clothing", "equipment",
    "hideout", "items", "locales", "locations",
    "models", "other", "overhauls", "quests",
    "retextures", "scripting", "tools", "traders",
    "weapons",
}

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
URL_RE = re.compile(r"^https?://", re.I)


class SubmissionError(Exception):
    pass


def slugify(text):
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug or "mod"


def check(condition, message):
    if not condition:
        raise SubmissionError(message)


def validate(raw, filename):
    """Raise SubmissionError with an actionable message, or return cleanly."""
    check(isinstance(raw, dict), "file must contain a single JSON object")

    for field in REQUIRED:
        check(raw.get(field), f'"{field}" is required and must not be empty')

    check(isinstance(raw["authors"], list) and raw["authors"],
          '"authors" must be a non-empty list of names, e.g. ["YourName"]')
    check(all(isinstance(a, str) and a.strip() for a in raw["authors"]),
          '"authors" must contain only non-empty strings')

    links = raw["source_links"]
    check(isinstance(links, list) and links,
          '"source_links" must be a non-empty list')
    for link in links:
        check(isinstance(link, dict) and link.get("url"),
              'each entry in "source_links" needs a "url"')
        check(URL_RE.match(link["url"]),
              f'source link "{link["url"]}" must start with http:// or https://')

    slug = raw.get("slug") or slugify(raw["name"])
    check(SLUG_RE.match(slug),
          f'"slug" must be lowercase words separated by hyphens (got "{slug}")')

    category = raw.get("category")
    if category:
        check(category in KNOWN_CATEGORIES,
              f'"category" must be one of: {", ".join(sorted(KNOWN_CATEGORIES))}')

    fika = raw.get("fika", "unknown")
    check(fika in ("compatible", "incompatible", "unknown", True, False),
          '"fika" must be "compatible", "incompatible", or "unknown"')

    expected = f"{slug}.json"
    check(os.path.basename(filename) == expected,
          f"file should be named {expected} to match the mod's slug")

    return slug


def normalise(raw, slug):
    """Expand a submission into the same record shape scraped mods use."""
    fika = raw.get("fika", "unknown")
    category = raw.get("category")

    versions = []
    if raw.get("version") or raw.get("spt_constraint"):
        versions.append({
            "id": None,
            "version": raw.get("version", ""),
            "description": raw.get("changelog", ""),
            "spt_constraint": raw.get("spt_constraint", ""),
            "fika": fika if isinstance(fika, str) else "unknown",
            "downloads": 0,
            "size": None,
            "link": raw.get("download_url", ""),
            "published_at": raw.get("published_at", ""),
            "dependencies": [],
        })

    dependencies = [{"id": d.get("id"), "name": d.get("name", ""),
                     "slug": d.get("slug", ""), "constraint": d.get("constraint", ""),
                     "url": d.get("url", "")}
                    for d in raw.get("dependencies") or []]

    return {
        "id": f"c-{slug}",
        "hub_id": None,
        "guid": raw.get("guid"),
        "name": raw["name"],
        "slug": slug,
        "teaser": raw["teaser"],
        "description_html": raw.get("description_html") or "",
        "thumbnail": raw.get("thumbnail", ""),
        "forge_url": "",
        "downloads": 0,
        "favourites": 0,
        "featured": False,
        "fika": fika is True or fika == "compatible",
        "fika_latest": fika if isinstance(fika, str) else "unknown",
        "category": ({"id": None, "title": category.replace("-", " ").title(),
                      "slug": category} if category else None),
        "license": {"name": raw.get("license", ""), "link": ""},
        "authors": [{"id": None, "name": a, "avatar": ""} for a in raw["authors"]],
        "source_links": [{"url": l["url"], "label": l.get("label", "")}
                         for l in raw["source_links"]],
        "versions": versions,
        "latest_version": raw.get("version", ""),
        "spt_constraint": raw.get("spt_constraint", ""),
        "all_spt_constraints": ([raw["spt_constraint"]]
                                if raw.get("spt_constraint") else []),
        "dependencies": dependencies,
        "all_dependencies": dependencies,
        "published_at": raw.get("published_at", ""),
        "updated_at": raw.get("updated_at") or raw.get("published_at", ""),
        "flags": {"contains_ads": False, "contains_ai_content": False,
                  "ai_disclosure": "", "cheat_notice": False,
                  "profile_binding_notice": False},
        "origin": "community",
    }


def load_all(community_dir, on_error=None):
    """Every valid submission. Invalid ones are reported and skipped."""
    mods, errors = [], []
    for path in sorted(glob.glob(os.path.join(community_dir, "*.json"))):
        if os.path.basename(path).startswith("_"):
            continue        # _template.json and friends are documentation
        try:
            with open(path) as f:
                raw = json.load(f)
            slug = validate(raw, path)
            mods.append(normalise(raw, slug))
        except json.JSONDecodeError as e:
            errors.append((path, f"not valid JSON: {e}"))
        except SubmissionError as e:
            errors.append((path, str(e)))

    if errors and on_error:
        for path, message in errors:
            on_error(path, message)
    return mods, errors


def main(argv):
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    paths = argv[1:] or [os.path.join(here, "community")]

    files = []
    for path in paths:
        files.extend(sorted(glob.glob(os.path.join(path, "*.json")))
                     if os.path.isdir(path) else [path])
    files = [f for f in files if not os.path.basename(f).startswith("_")]

    failures = 0
    for path in files:
        try:
            with open(path) as f:
                raw = json.load(f)
            slug = validate(raw, path)
            normalise(raw, slug)
            print(f"ok    {os.path.basename(path)}")
        except json.JSONDecodeError as e:
            print(f"FAIL  {os.path.basename(path)}: not valid JSON: {e}")
            failures += 1
        except SubmissionError as e:
            print(f"FAIL  {os.path.basename(path)}: {e}")
            failures += 1

    print(f"\n{len(files) - failures}/{len(files)} submission(s) valid")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
