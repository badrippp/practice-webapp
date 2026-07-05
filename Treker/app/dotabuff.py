from typing import Any

import httpx

DOTABUFF_BASE = "https://www.dotabuff.com"


def profile_url(account_id: int) -> str:
    return f"{DOTABUFF_BASE}/players/{account_id}"


def hero_url(hero_slug: str) -> str:
    return f"{DOTABUFF_BASE}/heroes/{hero_slug}"


def matches_url(account_id: int) -> str:
    return f"{profile_url(account_id)}/matches"


def heroes_meta_url() -> str:
    return f"{DOTABUFF_BASE}/heroes"


def hero_slug(name: str) -> str:
    return name.lower().replace(" ", "-").replace("'", "")


async def fetch_hero_meta() -> dict[str, Any]:
    """Fetch hero win/pick rates from Dotabuff public page data."""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; Dota2ProgressTracker/1.0)",
        "Accept": "text/html,application/xhtml+xml",
    }

    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            response = await client.get(f"{DOTABUFF_BASE}/heroes", headers=headers)
            if response.status_code != 200:
                return {"heroes": [], "source": "dotabuff", "error": "unavailable"}

            html = response.text
            heroes: list[dict[str, str]] = []

            import re

            pattern = re.compile(
                r'href="/heroes/([^"]+)"[^>]*>.*?<div class="name">([^<]+)</div>.*?'
                r'<div class="label">Win Rate</div>\s*<div class="value">([^<]+)</div>.*?'
                r'<div class="label">Pick Rate</div>\s*<div class="value">([^<]+)</div>',
                re.DOTALL,
            )

            for match in pattern.finditer(html):
                slug, name, win_rate, pick_rate = match.groups()
                heroes.append(
                    {
                        "slug": slug,
                        "name": name.strip(),
                        "win_rate": win_rate.strip(),
                        "pick_rate": pick_rate.strip(),
                        "url": hero_url(slug),
                    }
                )

            if heroes:
                return {"heroes": heroes[:30], "source": "dotabuff", "error": None}

            return {"heroes": [], "source": "dotabuff", "error": "parse_failed"}
    except Exception as exc:
        return {"heroes": [], "source": "dotabuff", "error": str(exc)}
