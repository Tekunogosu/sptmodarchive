#!/usr/bin/env python3
"""Mirror the images the Forge hosts, so they survive its shutdown.

    python3 scrape/fetch_images.py              # thumbnails + avatars
    python3 scrape/fetch_images.py --embedded   # also images inside descriptions
    python3 scrape/fetch_images.py --limit 20   # small test run
    python3 scrape/fetch_images.py --fresh      # re-download everything

Only images on sp-tarkov hosts are mirrored by default, and the reason is
simply which ones are about to disappear. Mod thumbnails and author avatars
live on forge-static.sp-tarkov.com and die with the Forge; the thousands of
screenshots embedded in mod descriptions sit on imgur, ibb, and GitHub, which
have their own lifetimes and come to ~3.4 GB. Those are available behind
--embedded for anyone who wants them, but they do not belong in a git repo by
default.

Thumbnails are re-encoded to 192px WebP. The site shows them at 48px in the
list and 96px on a mod page, so 192px is a 2x retina copy and visually
identical, at roughly 18 MB instead of 121 MB.

Files are content-addressed by URL hash, so re-running only fetches what is
new, and a mod that changes its thumbnail does not orphan the old one.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
IMAGES = os.path.join(DATA, "images")
MANIFEST = os.path.join(DATA, "images.json")

UA = "Mozilla/5.0 (SPT mod archive; personal archival script)"

# The hosts that go away when the Forge does. Everything else is somebody
# else's infrastructure with its own lifetime.
# Both eras of the site, because the archive holds images from both:
# forge-static served the Forge, files.sp-mod.com serves its successor.
FORGE_HOSTS = {"files.sp-mod.com",
               "forge-static.sp-tarkov.com", "hub.sp-tarkov.com"}

THUMB_PX = 192          # 2x the largest on-page size (96px on a mod page)
AVATAR_PX = 96          # avatars render at 40px at most

_IMG_SRC_RE = re.compile(r'<img[^>]+src="([^"]+)"')


def local_name(url, suffix):
    """A stable filename derived from the URL, not from mod identity.

    Content addressing means two mods sharing an author's avatar share one
    file, and re-running never has to guess whether an existing file is stale.
    """
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    return f"{digest}{suffix}"


def download(url, attempts=3):
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if attempt == attempts - 1:
                return None
            time.sleep(2 ** attempt)
        except Exception:
            if attempt == attempts - 1:
                return None
            time.sleep(2 ** attempt)
    return None


def convert(raw, max_px):
    """Re-encode to a WebP thumbnail. Returns None if it is not an image.

    Pillow is imported lazily and only here, so the build -- which never
    resizes anything -- has no image dependency at all, and neither does CI.
    """
    from io import BytesIO
    from PIL import Image

    with Image.open(BytesIO(raw)) as img:
        img.load()
        # Animated sources collapse to their first frame; a still thumbnail is
        # the point, and keeping the animation would undo the size saving.
        if getattr(img, "is_animated", False):
            img.seek(0)
        img = img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB")
        img.thumbnail((max_px, max_px), Image.LANCZOS)

        out = BytesIO()
        img.save(out, "WEBP", quality=82, method=4)
        return out.getvalue()


def fetch_one(url, max_px, resize):
    """(url, filename, bytes_written) or (url, None, reason)."""
    suffix = ".webp" if resize else os.path.splitext(
        urllib.parse.urlparse(url).path)[1] or ".img"
    name = local_name(url, suffix)
    path = os.path.join(IMAGES, name)

    raw = download(url)
    if raw is None:
        return url, None, "unreachable"

    if resize:
        try:
            data = convert(raw, max_px)
        except Exception as e:
            return url, None, f"not an image ({type(e).__name__})"
    else:
        data = raw

    with open(path, "wb") as f:
        f.write(data)
    return url, name, len(data)


# --- gathering -----------------------------------------------------------

def is_forge_hosted(url):
    return urllib.parse.urlparse(url).netloc in FORGE_HOSTS


def gather_urls(records, include_embedded):
    """Every Forge-hosted image URL, mapped to the size it should be stored at.

    Mods and addons are both accepted, because an addon record carries the
    same `thumbnail` and `authors[].avatar` fields and its images sit on the
    same host that is going away.
    """
    wanted = {}
    for mod in records:
        thumb = mod.get("thumbnail")
        if thumb and is_forge_hosted(thumb):
            wanted[thumb] = THUMB_PX
        for author in mod.get("authors") or []:
            avatar = author.get("avatar")
            if avatar and is_forge_hosted(avatar):
                wanted.setdefault(avatar, AVATAR_PX)
        if include_embedded:
            for src in _IMG_SRC_RE.findall(mod.get("description_html") or ""):
                if is_forge_hosted(src):
                    wanted.setdefault(src, THUMB_PX * 4)
    return wanted


def load_manifest():
    if not os.path.exists(MANIFEST):
        return {}
    with open(MANIFEST) as f:
        try:
            return json.load(f).get("images", {})
        except json.JSONDecodeError:
            return {}


def save_manifest(mapping):
    with open(MANIFEST, "w") as f:
        json.dump({"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                 time.gmtime()),
                   "count": len(mapping), "images": mapping}, f, indent=1)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--embedded", action="store_true",
                    help="also mirror Forge-hosted images inside descriptions")
    ap.add_argument("--no-resize", action="store_true",
                    help="store originals instead of WebP thumbnails")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--fresh", action="store_true", help="re-download everything")
    args = ap.parse_args()

    path = os.path.join(DATA, "mods.json")
    if not os.path.exists(path):
        sys.exit("data/mods.json not found -- run scrape/scrape_mods.py first")
    with open(path) as f:
        records = json.load(f)["mods"]

    # Addons are optional: the archive predates them, and scrape_addons.py may
    # simply not have been run yet. Their thumbnails live on the same dying
    # host, so they are mirrored alongside rather than by a second script.
    addons_path = os.path.join(DATA, "addons.json")
    if os.path.exists(addons_path):
        with open(addons_path) as f:
            addons = json.load(f)["addons"]
        print(f"{len(addons)} addons included", file=sys.stderr)
        records = records + addons

    os.makedirs(IMAGES, exist_ok=True)
    manifest = {} if args.fresh else load_manifest()
    wanted = gather_urls(records, args.embedded)

    todo = [(url, px) for url, px in wanted.items()
            if args.fresh or url not in manifest
            or not os.path.exists(os.path.join(IMAGES, manifest[url]))]

    # Report what is genuinely cached before --limit trims the queue, or a
    # small test run looks like the archive is nearly complete.
    cached = len(wanted) - len(todo)
    if args.limit:
        todo = todo[:args.limit]

    print(f"{len(wanted)} Forge-hosted images; {cached} already mirrored, "
          f"{len(todo)} to fetch this run", file=sys.stderr)
    if not todo:
        save_manifest(manifest)
        return 0

    started, written, failed = time.time(), 0, []
    resize = not args.no_resize

    with ThreadPoolExecutor(args.workers) as pool:
        results = pool.map(lambda item: fetch_one(item[0], item[1], resize), todo)
        for n, (url, name, info) in enumerate(results, 1):
            if name is None:
                failed.append((url, info))
            else:
                manifest[url] = name
                written += info
            if n % 100 == 0 or n == len(todo):
                print(f"  {n}/{len(todo)}  {written / 1e6:.0f} MB",
                      file=sys.stderr)
                save_manifest(manifest)    # survive an interrupted run

    save_manifest(manifest)

    print(f"\nMirrored:  {len(manifest)} images", file=sys.stderr)
    print(f"Written:   {written / 1e6:.1f} MB this run", file=sys.stderr)
    print(f"On disk:   {sum(os.path.getsize(os.path.join(IMAGES, f)) for f in os.listdir(IMAGES)) / 1e6:.1f} MB",
          file=sys.stderr)
    if failed:
        print(f"Failed:    {len(failed)}", file=sys.stderr)
        for url, why in failed[:5]:
            print(f"  {why}: {url}", file=sys.stderr)
    print(f"\nDone in {time.time() - started:.0f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
