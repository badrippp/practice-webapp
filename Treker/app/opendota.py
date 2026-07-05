import asyncio
import os
from typing import Any

import httpx

BASE_URL = "https://api.opendota.com/api"
STEAM_CDN = "https://cdn.cloudflare.steamstatic.com"


def _params(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    params: dict[str, Any] = extra.copy() if extra else {}
    api_key = os.getenv("OPENDOTA_API_KEY")
    if api_key:
        params["api_key"] = api_key
    return params


async def get(path: str, params: dict[str, Any] | None = None) -> Any:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{BASE_URL}{path}", params=_params(params))
        response.raise_for_status()
        return response.json()


async def search_players(query: str) -> list[dict[str, Any]]:
    return await get("/search", {"q": query})


async def get_player(account_id: int) -> dict[str, Any]:
    return await get(f"/players/{account_id}")


async def get_player_wl(account_id: int) -> dict[str, Any]:
    return await get(f"/players/{account_id}/wl")


async def get_player_matches(account_id: int, limit: int = 20) -> list[dict[str, Any]]:
    return await get(f"/players/{account_id}/matches", {"limit": limit})


async def get_player_heroes(account_id: int) -> list[dict[str, Any]]:
    return await get(f"/players/{account_id}/heroes")


async def get_player_totals(account_id: int) -> list[dict[str, Any]]:
    return await get(f"/players/{account_id}/totals")


async def get_player_peers(account_id: int) -> list[dict[str, Any]]:
    return await get(f"/players/{account_id}/peers")


async def get_match(match_id: int) -> dict[str, Any]:
    return await get(f"/matches/{match_id}")


async def get_matches_batch(match_ids: list[int], concurrency: int = 6) -> list[dict[str, Any]]:
    semaphore = asyncio.Semaphore(concurrency)
    results: list[dict[str, Any]] = []

    async def fetch_one(match_id: int) -> dict[str, Any] | None:
        async with semaphore:
            try:
                return await get_match(match_id)
            except httpx.HTTPError:
                return None

    fetched = await asyncio.gather(*[fetch_one(mid) for mid in match_ids])
    results.extend(item for item in fetched if item)
    return results


async def get_heroes() -> list[dict[str, Any]]:
    return await get("/heroes")


async def get_hero_stats() -> list[dict[str, Any]]:
    return await get("/heroStats")


def parse_steam_input(raw: str) -> int | None:
    value = raw.strip()
    if not value:
        return None

    if value.isdigit():
        account_id = int(value)
        if account_id > 76561197960265728:
            return account_id - 76561197960265728
        return account_id

    if "/profiles/" in value:
        steam64 = value.rstrip("/").split("/profiles/")[-1].split("/")[0]
        if steam64.isdigit():
            return int(steam64) - 76561197960265728

    if "steamcommunity.com/id/" in value:
        return None

    return None


def steam_avatar(url: str | None) -> str:
    return url or f"{STEAM_CDN}/apps/dota2/images/dota_react/heroes/icons/pudge.png"
