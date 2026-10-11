"""Educational images for place_image.

Searched images come from Wikimedia Commons. Generated images are only accepted
when a provider returns an https URL on the allowlist. This service does not
ship an image generator.
"""

import logging
from urllib.parse import urlparse

import httpx

from src.core.config import get_settings
from src.modules.teacher.protocol import image_url_allowed

logger = logging.getLogger("sybeez.ai.teacher.images")


def image_from_wikimedia(payload: dict) -> str | None:
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
        for info in page.get("imageinfo") or []:
            if not isinstance(info, dict):
                continue
            mime = str(info.get("mime") or "")
            if mime and not mime.startswith("image/"):
                continue
            url = info.get("thumburl") or info.get("url")
            if isinstance(url, str) and image_url_allowed(url, get_settings().image_hosts):
                return url
    return None


async def search_educational_image(query: str) -> str | None:
    settings = get_settings()
    cleaned = " ".join(query.split())[:200]
    if not cleaned:
        return None
    url = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": cleaned,
        "gsrnamespace": "6",
        "gsrlimit": "3",
        "prop": "imageinfo",
        "iiprop": "url|mime",
        "iiurlwidth": "640",
        "format": "json",
    }
    try:
        async with httpx.AsyncClient(timeout=settings.upstream_timeout_seconds) as client:
            response = await client.get(url, params=params, headers={"Accept": "application/json"})
            response.raise_for_status()
            found = image_from_wikimedia(response.json())
    except (httpx.HTTPError, ValueError):
        logger.warning("educational image search failed")
        return None
    if found and urlparse(found).scheme == "https":
        return found
    return None
