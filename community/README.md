# Adding a mod

This folder is how the archive keeps growing after the Forge is gone. One JSON
file per mod, added by pull request. No build tools, no account beyond GitHub,
and nothing here needs the Forge to still exist.

**If you would rather not touch JSON:** open an issue using the *Add a mod*
template and fill in the form. A maintainer will turn it into a file for you.
That path is slower but perfectly welcome.

## Adding a mod yourself

1. Copy `_template.json` to `your-mod-slug.json` in this folder.
   The filename must match the mod's slug: *My Cool Mod* → `my-cool-mod.json`.
2. Fill in the four required fields: `name`, `authors`, `teaser`, and
   `source_links`. Delete any optional field you do not need.
3. Check it:

   ```bash
   python3 build/community.py
   ```

   This prints `ok` per file, or tells you exactly what to fix.
4. Open a pull request. CI runs the same check.

That is the whole process. You do not need to rebuild the site — that happens
when the change is merged.

## Fields

| Field | Required | Notes |
|---|---|---|
| `name` | yes | Display name |
| `authors` | yes | List of names, e.g. `["YourName"]` |
| `teaser` | yes | One sentence, shown in the mod list |
| `source_links` | yes | List of `{"url": ..., "label": ...}`. A mod with a separate client and server repo lists both; `label` distinguishes them (`"3.11"`, `"4.0"`, `"server"`) |
| `slug` | no | Defaults to a slug made from `name` |
| `category` | no | One of the categories listed below |
| `fika` | no | `"compatible"`, `"incompatible"`, or `"unknown"` (the default) |
| `spt_constraint` | no | SPT version range, e.g. `"~4.1.0"` |
| `version` | no | Current version string |
| `description_html` | no | Longer description. Simple HTML only — anything else is stripped when the site is built |
| `download_url`, `license`, `guid`, `thumbnail` | no | Self-explanatory |
| `published_at`, `updated_at` | no | `YYYY-MM-DD` |
| `dependencies` | no | List of `{"name": ..., "url": ...}` |

### Categories

`audio`, `bots`, `clothing`, `equipment`, `hideout`, `items`, `locales`,
`locations`, `models`, `other`, `overhauls`, `quests`, `retextures`,
`scripting`, `tools`, `traders`, `weapons`

These mirror the Forge's own categories so community mods sit alongside
archived ones rather than in a separate bucket.

## Notes

- **Community mods are labelled as such** on the site, with a *Community* badge.
  They have no download counts, because there is nothing counting them.
- **Editing an existing archived mod** is a different thing: those records come
  from the scrape and are regenerated. To correct a bad source URL on an
  archived mod, edit `source_overrides.json` instead — see the main README.
- **Only add mods you have the right to list.** A link to a public repository is
  fine. Do not paste someone else's mod files or descriptions into this folder.
