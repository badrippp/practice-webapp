from typing import Any

STEAM_CDN = "https://cdn.cloudflare.steamstatic.com"

ROLE_LABELS = {
    "carry": "Керри (Safe)",
    "mid": "Мид",
    "offlane": "Оффлейн",
    "support": "Саппорт",
    "hard_support": "Полный саппорт",
    "flex": "Флекс",
}

LANE_ROLE_MAP = {
    1: "carry",
    2: "mid",
    3: "offlane",
    4: "support",
}


def hero_slug(internal_name: str) -> str:
    return internal_name.replace("npc_dota_hero_", "")


def hero_image(internal_name: str) -> str:
    slug = hero_slug(internal_name)
    return f"{STEAM_CDN}/apps/dota2/images/dota_react/heroes/{slug}.png"


def hero_icon(internal_name: str) -> str:
    slug = hero_slug(internal_name)
    return f"{STEAM_CDN}/apps/dota2/images/dota_react/heroes/icons/{slug}.png"


def enrich_hero(hero: dict[str, Any]) -> dict[str, Any]:
    internal = hero.get("name") or f"npc_dota_hero_{hero.get('hero_slug', 'unknown')}"
    localized = hero.get("localized_name") or hero.get("hero_name") or "Unknown"
    slug = hero_slug(internal) if internal.startswith("npc_") else internal
    return {
        **hero,
        "hero_id": hero.get("id") or hero.get("hero_id"),
        "hero_name": localized,
        "hero_internal": internal if internal.startswith("npc_") else f"npc_dota_hero_{slug}",
        "hero_slug": slug,
        "hero_image": hero_image(f"npc_dota_hero_{slug}"),
        "hero_icon": hero_icon(f"npc_dota_hero_{slug}"),
        "primary_role": infer_role_from_hero(hero),
    }


def build_hero_map(heroes: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for hero in heroes:
        enriched = enrich_hero(hero)
        result[enriched["hero_id"]] = enriched
    return result


def infer_role_from_hero(hero: dict[str, Any]) -> str:
    roles = hero.get("roles") or []
    role_set = set(roles)

    if "Carry" in role_set:
        return "carry"
    if "Support" in role_set and "Nuker" not in role_set and "Disabler" in role_set:
        return "hard_support"
    if "Support" in role_set:
        return "support"
    if "Nuker" in role_set or "Escape" in role_set:
        return "mid"
    if "Initiator" in role_set or "Durable" in role_set or "Pusher" in role_set:
        return "offlane"
    if "Support" in role_set:
        return "support"
    return "flex"


def infer_role_from_lane(lane_role: int | None) -> str | None:
    if lane_role is None:
        return None
    return LANE_ROLE_MAP.get(lane_role)


def role_label(role_key: str) -> str:
    return ROLE_LABELS.get(role_key, role_key)
