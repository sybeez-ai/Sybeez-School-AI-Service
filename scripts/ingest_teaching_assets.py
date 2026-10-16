# ruff: noqa
"""Build the teaching asset library: Wikimedia Commons -> child-safety check -> S3 -> manifest.

Usage (needs AWS credentials for the bucket and GEMINI_API_KEY for the safety check):
  python scripts/ingest_teaching_assets.py --bucket B --cdn https://xxxx.cloudfront.net \
      --out apps/ai/src/modules/assets/manifest.json [--glb-dir /tmp/glb] [--only slug,slug]

Only openly licensed files are kept (CC0, public domain, CC BY, CC BY-SA); attribution is recorded.
Every image must pass a Gemini vision check "appropriate for school children". Nothing is
hot-linked at runtime: the app serves S3 objects through CloudFront.
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from teaching_topics import TOPICS  # noqa: E402

UA = {"User-Agent": "SybeezTeachingAssets/1.0 (https://school.sybeez.ai; assets@sybeez.ai)"}
COMMONS = "https://commons.wikimedia.org/w/api.php"
OK_LICENSE = re.compile(r"^(cc0|public domain|pd\b|pd-|cc[- ]by(-sa)?[- ]\d)", re.I)
MIN_W = 600
PER_TOPIC = 3


def strip(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def commons_candidates(client: httpx.Client, query: str) -> list[dict]:
    r = client.get(
        COMMONS,
        params={
            "action": "query", "format": "json", "generator": "search", "gsrsearch": f"filetype:bitmap|drawing {query}",
            "gsrnamespace": 6, "gsrlimit": 14, "prop": "imageinfo", "iiprop": "url|extmetadata|size|mime",
            "iiurlwidth": 1024,
        },
        headers=UA, timeout=30,
    )
    r.raise_for_status()
    pages = (r.json().get("query") or {}).get("pages") or {}
    out = []
    for p in sorted(pages.values(), key=lambda x: x.get("index", 99)):
        ii = (p.get("imageinfo") or [{}])[0]
        meta = ii.get("extmetadata") or {}
        lic = strip((meta.get("LicenseShortName") or {}).get("value", ""))
        if not OK_LICENSE.search(lic):
            continue
        if ii.get("mime") not in ("image/jpeg", "image/png", "image/svg+xml"):
            continue
        if (ii.get("width") or 0) < MIN_W:
            continue
        out.append(
            {
                "title": strip(p.get("title", "")).removeprefix("File:"),
                "url": ii.get("thumburl") or ii.get("url"),
                "page": ii.get("descriptionurl"),
                "license": lic,
                "license_url": strip((meta.get("LicenseUrl") or {}).get("value", "")),
                "author": strip((meta.get("Artist") or {}).get("value", ""))[:160],
                "description": strip((meta.get("ImageDescription") or {}).get("value", ""))[:300],
            }
        )
    return out


def child_safe(client: httpx.Client, jpeg: bytes, key: str) -> tuple[bool, str]:
    body = {
        "contents": [{"parts": [
            {"text": 'Is this image appropriate and useful for teaching school children aged 6-16 (no nudity, violence, gore, hateful symbols, ads, watermarks or text that is unreadable)? Reply ONLY JSON {"safe":true|false,"educational":true|false,"reason":"short"}.'},
            {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(jpeg).decode()}},
        ]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
    }
    r = client.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent",
        headers={"x-goog-api-key": key}, json=body, timeout=60,
    )
    if r.status_code >= 400:
        return False, f"moderation unavailable ({r.status_code})"  # fail closed
    try:
        data = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
        return bool(data.get("safe")) and bool(data.get("educational")), str(data.get("reason", ""))[:120]
    except Exception:
        return False, "moderation unparseable"


def to_jpeg(raw: bytes) -> bytes:
    from io import BytesIO

    from PIL import Image

    im = Image.open(BytesIO(raw))
    if im.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        im = im.convert("RGBA")
        bg.paste(im, mask=im.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")
    im.thumbnail((1024, 1024))
    buf = BytesIO()
    im.save(buf, "JPEG", quality=84, optimize=True)
    return buf.getvalue()


def s3_put(bucket: str, key: str, data: bytes, ctype: str) -> None:
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(data)
        path = f.name
    subprocess.run(
        ["aws", "s3", "cp", path, f"s3://{bucket}/{key}", "--content-type", ctype,
         "--cache-control", "public, max-age=31536000, immutable", "--quiet"],
        check=True,
    )
    os.unlink(path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", required=True)
    ap.add_argument("--cdn", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--glb-dir")
    ap.add_argument("--only", default="")
    ap.add_argument("--no-upload", action="store_true")
    a = ap.parse_args()
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        sys.exit("GEMINI_API_KEY is required for the child-safety check")
    only = {s for s in a.only.split(",") if s}
    cdn = a.cdn.rstrip("/")
    out_path = Path(a.out)
    manifest = json.loads(out_path.read_text()) if out_path.exists() else {"version": 1, "cdn": cdn, "topics": {}, "models": {}}
    manifest["cdn"] = cdn

    if a.glb_dir:
        for glb in sorted(Path(a.glb_dir).glob("*.glb")):
            k = f"models/{glb.stem}.glb"
            if not a.no_upload:
                s3_put(a.bucket, k, glb.read_bytes(), "model/gltf-binary")
            manifest["models"][glb.stem] = {"key": k, "url": f"{cdn}/{k}", "license": "Original work, CC0 (generated by Sybeez)", "bytes": glb.stat().st_size}

    with httpx.Client(follow_redirects=True) as client:
        for t in TOPICS:
            if only and t["slug"] not in only:
                continue
            images, rejected = [], []
            try:
                cands, words = [], t["query"].split()
                # Relax the query until Commons returns something usable.
                for n in (len(words), max(3, len(words) - 2), 3, 2):
                    cands = commons_candidates(client, " ".join(words[:n]))
                    if cands:
                        break
            except Exception as exc:  # network hiccup: keep going, topic stays uncovered
                print(f"  ! {t['slug']}: search failed {type(exc).__name__}")
                cands = []
            for c in cands:
                if len(images) >= PER_TOPIC:
                    break
                try:
                    raw = client.get(c["url"], headers=UA, timeout=60).content
                    jpeg = to_jpeg(raw)
                except Exception:
                    continue
                ok, why = child_safe(client, jpeg, key)
                if not ok:
                    rejected.append(why)
                    continue
                n = len(images) + 1
                k = f"images/{t['subject'].lower()}/{t['slug']}/{n}.jpg"
                if not a.no_upload:
                    s3_put(a.bucket, k, jpeg, "image/jpeg")
                images.append(
                    {
                        "key": k, "url": f"{cdn}/{k}", "caption": c["description"] or c["title"], "alt": f"{t['title']}: {c['title']}"[:200],
                        "license": c["license"], "license_url": c["license_url"], "author": c["author"], "source": c["page"],
                    }
                )
                time.sleep(0.4)
            manifest["topics"][t["slug"]] = {
                "slug": t["slug"], "title": t["title"], "subject": t["subject"], "classes": t["classes"],
                "aliases": t["aliases"], "key_terms": t["key_terms"], "model3d": t["model3d"], "images": images,
            }
            print(f"{t['slug']:28} images={len(images)} rejected={len(rejected)} model3d={t['model3d'] or '-'}")
            time.sleep(0.5)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
    covered = sum(1 for v in manifest["topics"].values() if v["images"])
    print(f"manifest: {covered}/{len(manifest['topics'])} topics with images, {len(manifest['models'])} models")


if __name__ == "__main__":
    main()
