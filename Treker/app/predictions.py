import math
from typing import Any

from app.heroes_data import infer_role_from_hero, infer_role_from_lane, role_label


def wilson_lower_bound(wins: int, games: int, z: float = 1.28) -> float:
    if games == 0:
        return 0.0
    p = wins / games
    denominator = 1 + z * z / games
    centre = p + z * z / (2 * games)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * games)) / games)
    return max(0.0, (centre - margin) / denominator)


def match_won(match: dict[str, Any]) -> bool:
    radiant_win = match.get("radiant_win", False)
    player_slot = match.get("player_slot", 0)
    is_radiant = player_slot < 128
    return radiant_win == is_radiant


def resolve_match_role(match: dict[str, Any], hero_map: dict[int, dict[str, Any]]) -> str:
    lane_role = match.get("lane_role")
    if lane_role is not None:
        mapped = infer_role_from_lane(lane_role)
        if mapped:
            return mapped

    hero = hero_map.get(match.get("hero_id"), {})
    return infer_role_from_hero(hero)


def analyze_roles(
    matches: list[dict[str, Any]], hero_map: dict[int, dict[str, Any]]
) -> dict[str, Any]:
    role_stats: dict[str, dict[str, int | float | str]] = {}

    for match in matches:
        role = resolve_match_role(match, hero_map)
        bucket = role_stats.setdefault(
            role,
            {"role": role, "label": role_label(role), "games": 0, "wins": 0, "win_rate": 0.0, "score": 0.0},
        )
        bucket["games"] = int(bucket["games"]) + 1
        if match_won(match):
            bucket["wins"] = int(bucket["wins"]) + 1

    ranked = []
    for role, stats in role_stats.items():
        games = int(stats["games"])
        wins = int(stats["wins"])
        win_rate = round(wins / games * 100, 1) if games else 0
        score = round(wilson_lower_bound(wins, games) * 100, 1)
        ranked.append(
            {
                **stats,
                "win_rate": win_rate,
                "score": score,
                "confidence": round(min(games / 15, 1.0) * 100),
            }
        )

    ranked.sort(key=lambda item: (item["score"], item["games"]), reverse=True)
    best = ranked[0] if ranked else None

    return {
        "roles": ranked,
        "recommended_role": best,
        "summary": (
            f"Лучшая роль — {best['label']} ({best['win_rate']}% WR за {best['games']} игр)"
            if best
            else "Недостаточно данных"
        ),
    }


def analyze_hero_picks(
    matches: list[dict[str, Any]],
    hero_map: dict[int, dict[str, Any]],
    meta_map: dict[int, float] | None = None,
    recommended_role: str | None = None,
) -> dict[str, Any]:
    hero_stats: dict[int, dict[str, Any]] = {}

    for match in matches:
        hero_id = match.get("hero_id")
        if not hero_id:
            continue

        hero = hero_map.get(hero_id, {})
        role = resolve_match_role(match, hero_map)
        bucket = hero_stats.setdefault(
            hero_id,
            {
                "hero_id": hero_id,
                "hero_name": hero.get("hero_name", "Unknown"),
                "hero_image": hero.get("hero_image"),
                "hero_icon": hero.get("hero_icon"),
                "hero_slug": hero.get("hero_slug"),
                "primary_role": hero.get("primary_role"),
                "role": role,
                "games": 0,
                "wins": 0,
            },
        )
        bucket["games"] += 1
        if match_won(match):
            bucket["wins"] += 1

    picks = []
    for hero_id, stats in hero_stats.items():
        games = stats["games"]
        wins = stats["wins"]
        if games < 2:
            continue

        player_wr = wilson_lower_bound(wins, games)
        meta_wr = (meta_map or {}).get(hero_id, 0.5)
        confidence = min(games / 12, 1.0)
        score = player_wr * confidence + meta_wr * (1 - confidence) * 0.25
        role_bonus = 0.08 if recommended_role and stats["role"] == recommended_role else 0.0
        score = min(1.0, score + role_bonus)

        picks.append(
            {
                **stats,
                "win_rate": round(wins / games * 100, 1),
                "score": round(score * 100, 1),
                "recommendation": _hero_verdict(wins, games, score),
            }
        )

    picks.sort(key=lambda item: (item["score"], item["games"]), reverse=True)
    avoid = sorted(
        [p for p in picks if p["games"] >= 3 and p["win_rate"] < 45],
        key=lambda item: item["win_rate"],
    )[:5]

    return {
        "recommended": picks[:8],
        "avoid": avoid,
        "pool_size": len(picks),
    }


def analyze_peers(peers: list[dict[str, Any]], min_games: int = 5) -> dict[str, Any]:
    partners = []

    for peer in peers:
        with_games = peer.get("with_games") or 0
        if with_games < min_games:
            continue

        with_wins = peer.get("with_win") or 0
        with_wr = round(with_wins / with_games * 100, 1)
        score = wilson_lower_bound(with_wins, with_games) * 100

        partners.append(
            {
                "account_id": peer.get("account_id"),
                "personaname": peer.get("personaname") or f"Player {peer.get('account_id')}",
                "avatar": peer.get("avatarfull") or peer.get("avatar"),
                "with_games": with_games,
                "with_wins": with_wins,
                "with_win_rate": with_wr,
                "score": round(score, 1),
                "last_played": peer.get("last_played"),
                "dotabuff_url": f"https://www.dotabuff.com/players/{peer.get('account_id')}",
            }
        )

    partners.sort(key=lambda item: (item["score"], item["with_games"]), reverse=True)

    play_with = [p for p in partners if p["with_win_rate"] >= 52][:10]
    avoid = sorted(
        [p for p in partners if p["with_win_rate"] <= 45 and p["with_games"] >= 8],
        key=lambda item: item["with_win_rate"],
    )[:10]

    return {
        "all": partners[:25],
        "play_with": play_with,
        "avoid": avoid,
        "summary": _party_summary(play_with, avoid),
    }


def analyze_recent_teammates(
    match_details: list[dict[str, Any]], account_id: int
) -> list[dict[str, Any]]:
    stats: dict[int, dict[str, Any]] = {}

    for match in match_details:
        players = match.get("players") or []
        me = next((p for p in players if p.get("account_id") == account_id), None)
        if not me:
            continue

        my_team = me.get("player_slot", 0) < 128
        my_won = match_won({**me, "radiant_win": match.get("radiant_win")})

        for player in players:
            pid = player.get("account_id")
            if not pid or pid == account_id:
                continue

            same_team = (player.get("player_slot", 0) < 128) == my_team
            if not same_team:
                continue

            bucket = stats.setdefault(
                pid,
                {
                    "account_id": pid,
                    "personaname": player.get("personaname") or player.get("name") or f"Player {pid}",
                    "avatar": player.get("avatarfull") or player.get("avatar"),
                    "games": 0,
                    "wins": 0,
                },
            )
            bucket["games"] += 1
            if my_won:
                bucket["wins"] += 1

    result = []
    for pid, data in stats.items():
        games = data["games"]
        if games < 2:
            continue
        result.append(
            {
                **data,
                "with_win_rate": round(data["wins"] / games * 100, 1),
                "dotabuff_url": f"https://www.dotabuff.com/players/{pid}",
            }
        )

    result.sort(key=lambda item: (item["with_win_rate"], item["games"]), reverse=True)
    return result[:15]


def _hero_verdict(wins: int, games: int, score: float) -> str:
    wr = wins / games
    if games >= 5 and wr >= 0.58:
        return "Отличный пик"
    if games >= 3 and wr >= 0.52:
        return "Рекомендуется"
    if wr >= 0.48:
        return "Нейтрально"
    return "Лучше избегать"


def _party_summary(play_with: list[dict], avoid: list[dict]) -> str:
    if play_with and avoid:
        return f"С {play_with[0]['personaname']} — {play_with[0]['with_win_rate']}% WR. Избегайте {avoid[0]['personaname']} ({avoid[0]['with_win_rate']}%)."
    if play_with:
        return f"Лучший тиммейт — {play_with[0]['personaname']} ({play_with[0]['with_win_rate']}% WR в пати)."
    return "Недостаточно данных о пати."
