"""Educational images for place_image.

Searched images come from Wikimedia Commons. Generated images are only accepted
when a provider returns an https URL on the allowlist. This service does not
ship an image generator.

School pictures should be simple labelled diagrams. A Class 6 student should
not be shown a research figure (for example a C4 leaf cross-section).
"""

import logging
import re
import time
from urllib.parse import urlparse

import httpx

from src.core.config import get_settings
from src.modules.teacher.protocol import image_url_allowed

logger = logging.getLogger("sybeez.ai.teacher.images")

# File names and captions that are too technical for a school diagram.
_TOO_TECHNICAL = re.compile(
    r"c4|c3\b|kranz|complicat|biochem|organelle|electron.?micro|histolog|cytolog|molecule",
    re.IGNORECASE,
)
_CACHE: dict[str, tuple[float, str | None]] = {}
_CACHE_HIT_SECONDS = 600.0
_CACHE_MISS_SECONDS = 30.0


def too_technical(text: str) -> bool:
    return bool(_TOO_TECHNICAL.search(text or ""))


def image_ok_for_class(image: dict, class_no: int | None) -> bool:
    """Drop research figures for every class through class 10, including when class is unknown."""
    blob = " ".join(str(image.get(key) or "") for key in ("caption", "alt", "source", "url", "title"))
    if not too_technical(blob):
        return True
    return class_no is not None and class_no >= 11


def kid_search_query(query: str, class_no: int | None) -> str:
    """Bias Commons search toward a simple labelled diagram for this grade."""
    base = " ".join((query or "").split())[:140]
    if not base:
        return ""
    if class_no is not None and class_no >= 9:
        extra = "simple labelled diagram"
    else:
        extra = "simple labelled diagram for kids"
    if extra.lower() in base.lower():
        return base[:200]
    return f"{base} {extra}"[:200]


def image_from_wikimedia(payload: dict, *, allow_technical: bool = False) -> str | None:
    pages = (payload.get("query") or {}).get("pages") or {}
    if isinstance(pages, dict):
        page_list = list(pages.values())
    elif isinstance(pages, list):
        page_list = pages
    else:
        return None
    for page in page_list:
        if not isinstance(page, dict):
            continue
        if not allow_technical and too_technical(str(page.get("title") or "")):
            continue
        for info in page.get("imageinfo") or []:
            if not isinstance(info, dict):
                continue
            mime = str(info.get("mime") or "")
            if mime and not mime.startswith("image/"):
                continue
            described = " ".join(
                str(info.get(key) or "") for key in ("extmetadata", "descriptionshorturl", "comment")
            )
            if not allow_technical and too_technical(described):
                continue
            url = info.get("thumburl") or info.get("url")
            if isinstance(url, str) and image_url_allowed(url, get_settings().image_hosts):
                if not allow_technical and too_technical(url):
                    continue
                return url
    return None


async def search_educational_image(query: str, *, class_no: int | None = None) -> str | None:
    settings = get_settings()
    cleaned = kid_search_query(query, class_no)
    if not cleaned:
        return None
    allow_technical = class_no is not None and class_no >= 11
    cache_key = f"{int(allow_technical)}:{cleaned.lower()}"
    cached = _CACHE.get(cache_key)
    now = time.monotonic()
    if cached and now - cached[0] < (_CACHE_HIT_SECONDS if cached[1] else _CACHE_MISS_SECONDS):
        return cached[1]
    url = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": cleaned,
        "gsrnamespace": "6",
        "gsrlimit": "8",
        "prop": "imageinfo",
        "iiprop": "url|mime",
        "iiurlwidth": "640",
        "format": "json",
    }
    try:
        async with httpx.AsyncClient(timeout=settings.upstream_timeout_seconds) as client:
            response = await client.get(url, params=params, headers={"Accept": "application/json"})
            response.raise_for_status()
            found = image_from_wikimedia(response.json(), allow_technical=allow_technical)
    except (httpx.HTTPError, ValueError):
        logger.warning("educational image search failed")
        return None
    if found and urlparse(found).scheme == "https":
        if len(_CACHE) > 500:
            _CACHE.clear()
        _CACHE[cache_key] = (now, found)
        return found
    _CACHE[cache_key] = (now, None)
    return None
