import os
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import dotabuff, opendota, predictions
from app.heroes_data import build_hero_map, enrich_hero, role_label

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

app = FastAPI(title="Dota 2 Progress Tracker", version="2.0.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/search")
async def search(q: str = Query(..., min_length=2)):
    try:
        results = await opendota.search_players(q)
        return {"results": results[:10]}
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"OpenDota error: {exc}") from exc


@app.get("/api/resolve")
async def resolve_input(raw: str = Query(..., min_length=1)):
    account_id = opendota.parse_steam_input(raw)
    if account_id is not None:
        return {"account_id": account_id, "method": "direct"}

    try:
        results = await opendota.search_players(raw)
        if not results:
            raise HTTPException(status_code=404, detail="Player not found")
        best = results[0]
        return {
            "account_id": best["account_id"],
            "method": "search",
            "personaname": best.get("personaname"),
        }
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"OpenDota error: {exc}") from exc


@app.get("/api/player/{account_id}")
async def player_profile(account_id: int):
    try:
        import asyncio

        profile, wl, heroes = await asyncio.gather(
            opendota.get_player(account_id),
            opendota.get_player_wl(account_id),
            opendota.get_player_heroes(account_id),
        )
        hero_map = build_hero_map(await opendota.get_heroes())

        enriched_heroes = []
        for hero_stat in heroes:
            hero = hero_map.get(hero_stat.get("hero_id"), {})
            games = hero_stat.get("games", 0) or 0
            win = hero_stat.get("win", 0) or 0
            enriched_heroes.append(
                {
                    **hero_stat,
                    "hero_name": hero.get("hero_name", "Unknown"),
                    "hero_slug": hero.get("hero_slug"),
                    "hero_image": hero.get("hero_image"),
                    "hero_icon": hero.get("hero_icon"),
                    "primary_role": hero.get("primary_role"),
                    "role_label": role_label(hero.get("primary_role", "flex")),
                    "win_rate": round(win / games * 100, 1) if games else 0,
                    "dotabuff_url": dotabuff.hero_url(dotabuff.hero_slug(hero.get("hero_name", "unknown"))),
                }
            )

        enriched_heroes.sort(key=lambda item: item.get("games", 0), reverse=True)
        rank_tier = profile.get("rank_tier")
        mmr_estimate = profile.get("mmr_estimate", {}).get("estimate")

        return {
            "account_id": account_id,
            "profile": profile,
            "wl": wl,
            "heroes": enriched_heroes,
            "rank_label": _rank_label(rank_tier),
            "mmr_estimate": mmr_estimate,
            "dotabuff": {
                "profile_url": dotabuff.profile_url(account_id),
                "matches_url": dotabuff.matches_url(account_id),
            },
        }
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Player not found") from exc
        raise HTTPException(status_code=502, detail=f"OpenDota error: {exc}") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"OpenDota error: {exc}") from exc


@app.get("/api/player/{account_id}/matches")
async def player_matches(account_id: int, limit: int = Query(100, ge=1, le=100)):
    try:
        matches = await opendota.get_player_matches(account_id, limit=limit)
        hero_map = build_hero_map(await opendota.get_heroes())

        detail_ids = [m["match_id"] for m in matches[:30]]
        match_details = await opendota.get_matches_batch(detail_ids, concurrency=8)
        detail_map = {m["match_id"]: m for m in match_details}

        enriched = []
        for match in matches:
            hero = hero_map.get(match.get("hero_id"), {})
            detail = detail_map.get(match.get("match_id"))
            teammates = _extract_teammates(detail, account_id, hero_map) if detail else []

            if detail:
                me = next((p for p in detail.get("players", []) if p.get("account_id") == account_id), None)
                if me and me.get("lane_role") is not None:
                    match = {**match, "lane_role": me.get("lane_role")}

            enriched.append(
                {
                    **match,
                    "won": _match_won(match),
                    "hero_name": hero.get("hero_name", "Unknown"),
                    "hero_image": hero.get("hero_image"),
                    "hero_icon": hero.get("hero_icon"),
                    "hero_slug": hero.get("hero_slug"),
                    "role": predictions.resolve_match_role(match, hero_map),
                    "role_label": role_label(predictions.resolve_match_role(match, hero_map)),
                    "teammates": teammates,
                    "dotabuff_match_url": f"https://www.dotabuff.com/matches/{match.get('match_id')}",
                    "start_date": match.get("start_time"),
                }
            )

        return {"account_id": account_id, "matches": enriched, "total": len(enriched)}
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"OpenDota error: {exc}") from exc


@app.get("/api/player/{account_id}/analysis")
async def player_analysis(account_id: int, limit: int = Query(100, ge=20, le=100)):
    try:
        import asyncio

        matches, hero_stats_raw, hero_map_list = await asyncio.gather(
            opendota.get_player_matches(account_id, limit=limit),
            opendota.get_hero_stats(),
            opendota.get_heroes(),
        )

        hero_map = build_hero_map(hero_map_list)
        meta_map = _meta_win_rates(hero_stats_raw)

        detail_ids = [m["match_id"] for m in matches[:40]]
        match_details = await opendota.get_matches_batch(detail_ids, concurrency=8)
        detail_lookup = {m["match_id"]: m for m in match_details}

        enriched_matches = []
        for match in matches:
            detail = detail_lookup.get(match.get("match_id"))
            if detail:
                me = next((p for p in detail.get("players", []) if p.get("account_id") == account_id), None)
                if me and me.get("lane_role") is not None:
                    match = {**match, "lane_role": me.get("lane_role")}
            enriched_matches.append({**match, "won": _match_won(match)})

        role_analysis = predictions.analyze_roles(enriched_matches, hero_map)
        recommended_role = role_analysis["recommended_role"]["role"] if role_analysis["recommended_role"] else None
        hero_picks = predictions.analyze_hero_picks(
            enriched_matches, hero_map, meta_map, recommended_role
        )

        points = _progress_points(enriched_matches, hero_map)

        return {
            "account_id": account_id,
            "games_analyzed": len(enriched_matches),
            "roles": role_analysis,
            "heroes": hero_picks,
            "progress": points,
            "model_note": "Модель на основе Wilson score по последним 100 матчам + мета OpenDota",
        }
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"OpenDota error: {exc}") from exc


@app.get("/api/player/{account_id}/party")
async def player_party(account_id: int, limit: int = Query(100, ge=20, le=100)):
    try:
        import asyncio

        peers, matches = await asyncio.gather(
            opendota.get_player_peers(account_id),
            opendota.get_player_matches(account_id, limit=limit),
        )

        peer_analysis = predictions.analyze_peers(peers)
        detail_ids = [m["match_id"] for m in matches[:35]]
        match_details = await opendota.get_matches_batch(detail_ids, concurrency=8)
        recent_teammates = predictions.analyze_recent_teammates(match_details, account_id)

        return {
            "account_id": account_id,
            "peers": peer_analysis,
            "recent_teammates": recent_teammates,
            "games_analyzed": len(matches),
        }
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"OpenDota error: {exc}") from exc


@app.get("/api/progress/{account_id}")
async def player_progress(account_id: int, limit: int = Query(100, ge=10, le=100)):
    try:
        matches = await opendota.get_player_matches(account_id, limit=limit)
        hero_map = build_hero_map(await opendota.get_heroes())
        enriched = [{**m, "won": _match_won(m)} for m in matches]
        points = _progress_points(enriched, hero_map)

        recent = points[-20:] if len(points) > 20 else points
        wins_last_20 = sum(1 for point in recent if point["won"])

        return {
            "account_id": account_id,
            "total_analyzed": len(points),
            "overall_win_rate": points[-1]["win_rate"] if points else 0,
            "last_20_win_rate": round(wins_last_20 / len(recent) * 100, 1) if recent else 0,
            "current_streak": _current_streak(points),
            "points": points,
        }
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"OpenDota error: {exc}") from exc


RANK_BRACKETS = {
    "herald": 1,
    "guardian": 2,
    "crusader": 3,
    "archon": 4,
    "legend": 5,
    "ancient": 6,
    "divine": 7,
    "immortal": 8,
}


@app.get("/api/meta/pro")
async def meta_pro_tracker(
    rank: str = Query("all", pattern="^(herald|guardian|crusader|archon|legend|ancient|divine|immortal|all)$"),
):
    try:
        return await build_meta(rank)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Meta fetch error: {exc}") from exc


@app.get("/api/dotabuff/meta")
async def dotabuff_meta():
    return await build_meta("all")


async def build_meta(rank: str = "all") -> dict[str, Any]:
    hero_stats = await opendota.get_hero_stats()
    heroes = [enrich_hero(h) for h in hero_stats]

    parsed = [_bracket_stats(hero, rank) for hero in heroes]
    total_picks = sum(item["picks"] for item in parsed) or 1
    rows = []

    for hero, stats in zip(heroes, parsed):
        picks = stats["picks"]
        wins = stats["wins"]
        bans = stats["bans"]
        if picks < 50:
            continue

        win_rate = round(wins / picks * 100, 2)
        pick_rate = round(picks / total_picks * 100, 2)
        ban_rate = round(bans / total_picks * 100, 2)
        tier = _meta_tier(win_rate, pick_rate)

        rows.append(
            {
                "hero_id": hero["hero_id"],
                "hero_name": hero["hero_name"],
                "hero_image": hero["hero_image"],
                "hero_icon": hero["hero_icon"],
                "hero_slug": hero["hero_slug"],
                "primary_role": hero["primary_role"],
                "role_label": role_label(hero["primary_role"]),
                "win_rate": win_rate,
                "pick_rate": pick_rate,
                "ban_rate": ban_rate,
                "pro_pick": hero.get("pro_pick") or 0,
                "pro_ban": hero.get("pro_ban") or 0,
                "tier": tier,
                "dotabuff_url": dotabuff.hero_url(hero["hero_slug"]),
            }
        )

    rows.sort(key=lambda item: item["win_rate"], reverse=True)
    bracket_label = "все ранги" if rank == "all" else rank.capitalize()
    return {
        "heroes": rows,
        "source": "opendota",
        "rank_bracket": rank,
        "updated_note": f"Мета ({bracket_label}) · стиль Dota2ProTracker",
    }


def _bracket_stats(hero: dict, rank: str) -> dict[str, int]:
    if rank == "all":
        brackets = range(1, 9)
    else:
        brackets = [RANK_BRACKETS[rank]]

    picks = sum(hero.get(f"{bracket}_pick") or 0 for bracket in brackets)
    wins = sum(hero.get(f"{bracket}_win") or 0 for bracket in brackets)
    bans = sum(hero.get(f"{bracket}_ban") or 0 for bracket in brackets)
    return {"picks": picks, "wins": wins, "bans": bans}


def _extract_teammates(
    match: dict[str, Any] | None, account_id: int, hero_map: dict[int, dict[str, Any]]
) -> list[dict[str, Any]]:
    if not match:
        return []

    players = match.get("players") or []
    me = next((p for p in players if p.get("account_id") == account_id), None)
    if not me:
        return []

    my_team_radiant = me.get("player_slot", 0) < 128
    teammates = []

    for player in players:
        pid = player.get("account_id")
        if not pid or pid == account_id:
            continue
        same_team = (player.get("player_slot", 0) < 128) == my_team_radiant
        if not same_team:
            continue

        hero_id = player.get("hero_id")
        hero = hero_map.get(hero_id, {})
        teammates.append(
            {
                "account_id": pid,
                "personaname": player.get("personaname") or player.get("name") or "?",
                "avatar": opendota.steam_avatar(player.get("avatarfull") or player.get("avatar")),
                "hero_id": hero_id,
                "hero_icon": hero.get("hero_icon"),
                "hero_image": hero.get("hero_image"),
            }
        )

    return teammates[:4]


def _match_won(match: dict[str, Any]) -> bool:
    return predictions.match_won(match)


def _progress_points(matches: list[dict[str, Any]], hero_map: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    points = []
    cumulative_wins = 0
    cumulative_games = 0

    for index, match in enumerate(reversed(matches)):
        cumulative_games += 1
        if match.get("won") or _match_won(match):
            cumulative_wins += 1

        hero = hero_map.get(match.get("hero_id"), {})
        points.append(
            {
                "index": index + 1,
                "match_id": match.get("match_id"),
                "won": match.get("won") if "won" in match else _match_won(match),
                "hero_name": hero.get("hero_name", "?"),
                "hero_image": hero.get("hero_image"),
                "kills": match.get("kills", 0),
                "deaths": match.get("deaths", 0),
                "assists": match.get("assists", 0),
                "duration": match.get("duration", 0),
                "start_time": match.get("start_time"),
                "win_rate": round(cumulative_wins / cumulative_games * 100, 1),
            }
        )

    return points


def _meta_win_rates(hero_stats: list[dict[str, Any]]) -> dict[int, float]:
    result: dict[int, float] = {}
    for hero in hero_stats:
        stats = _bracket_stats(hero, "all")
        if stats["picks"]:
            result[hero["id"]] = stats["wins"] / stats["picks"]
    return result


def _meta_tier(win_rate: float, pick_rate: float) -> str:
    score = win_rate + min(pick_rate, 15) * 0.15
    if score >= 54:
        return "S"
    if score >= 51:
        return "A"
    if score >= 48:
        return "B"
    if score >= 45:
        return "C"
    return "D"


def _rank_label(rank_tier: int | None) -> str:
    if not rank_tier:
        return "Unranked"

    tier = rank_tier // 10
    stars = rank_tier % 10
    names = {
        1: "Herald",
        2: "Guardian",
        3: "Crusader",
        4: "Archon",
        5: "Legend",
        6: "Ancient",
        7: "Divine",
        8: "Immortal",
    }
    name = names.get(tier, "Unknown")
    if tier == 8:
        return name
    return f"{name} {stars}"


def _current_streak(points: list[dict]) -> dict:
    if not points:
        return {"type": "none", "count": 0}

    last_won = points[-1]["won"]
    count = 0
    for point in reversed(points):
        if point["won"] == last_won:
            count += 1
        else:
            break

    return {"type": "win" if last_won else "loss", "count": count}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=True,
    )
