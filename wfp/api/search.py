"""画面向け API: 検索(素材の逆引き・エリア検索)"""
from __future__ import annotations

from wfp.api.store import ApiError, Store, need_drops
from wfp.core.common import MODES_JA, PLANETS_JA, RARITY_JA, SOURCE_CATS, norm, rank
from wfp.drops.search import find_sources, group_candidates, pick_candidates
from wfp.drops.tables import stage_label


def suggest_items(store: Store, q: str, materials_only: bool) -> list[dict]:
    need_drops(store)
    names, items = store.names(), store.all_items()
    if q.strip():
        cands = pick_candidates(q, items, names, materials_only)
    else:
        cands = [n for n in items if not materials_only or names.is_resource(n)]
        cands.sort(key=lambda n: norm(names.ja(n)))
    out = []
    for base in group_candidates(cands, names).values():
        out.append({"key": base, "ja": names.ja(base), "en": base})
        if len(out) >= 80:
            break
    return out


def lookup_item(store: Store, key: str, events: bool) -> dict:
    drops, names = need_drops(store), store.names()
    rows = find_sources(key, drops, store.sources(), names, events=events)
    if not rows:
        raise ApiError("該当する入手先がありません。", 404)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["cat"]] = counts.get(r["cat"], 0) + 1
    return {
        "ja": names.ja(key), "en": key, "total": len(rows),
        "cats": [{"key": c, "ja": SOURCE_CATS[c], "n": counts[c]} for c in SOURCE_CATS if c in counts],
        "rows": [{**r, "rarity_key": r["rarity"], "rarity": r["rarity_ja"]} for r in rows],
    }


def planets(store: Store) -> list[dict]:
    drops = need_drops(store)
    return [{"type": "planet", "key": p, "ja": PLANETS_JA.get(p, p)} for p in drops.planets]


def suggest_areas(store: Store, q: str) -> list[dict]:
    drops = need_drops(store)
    if not q.strip():
        return planets(store)
    out = [p for p in planets(store) if rank(q, [p["key"], p["ja"]]) is not None]
    for planet, node in drops.node_order:
        if rank(q, [node]) is not None:
            out.append({"type": "node", "key": f"{planet}|{node}", "ja": node, "sub": PLANETS_JA.get(planet, planet)})
    return out[:80]


def lookup_area(store: Store, kind: str, key: str, all_items: bool, events: bool) -> dict:
    drops, names = need_drops(store), store.names()
    if kind == "planet":
        targets = [(p, n) for p, n in drops.node_order if p == key]
        title = PLANETS_JA.get(key, key)
    else:
        planet, _, node = key.partition("|")
        targets = [(planet, node)]
        title = f"{PLANETS_JA.get(planet, planet)} / {node}"
    nodes = []
    for planet, node in targets:
        rows = [r for r in drops.rows if r[0] == planet and r[1] == node]
        if not rows or (rows[0][3] and not events):
            continue
        by_rot: dict[str, list] = {}
        for r in rows:
            if all_items or names.is_resource(r[5]):
                by_rot.setdefault(r[4], []).append(r)
        stages = [{"stage": stage_label(rot), "items": [{
            "ja": names.ja(r[5]), "en": r[5], "chance": r[6], "rarity": RARITY_JA.get(r[7], r[7]), "rarity_key": r[7],
        } for r in sorted(lst, key=lambda x: -x[6])]} for rot, lst in sorted(by_rot.items())]
        if stages or kind == "node":
            nodes.append({"planet": PLANETS_JA.get(planet, planet), "node": node,
                          "mode": MODES_JA.get(rows[0][2], rows[0][2]), "event": rows[0][3], "stages": stages})
    return {"title": title, "nodes": nodes}


# (メソッド, パス) -> 処理。c はリクエスト(wfp/api/server.py の Request)
ROUTES = {
    ("GET", "/api/suggest/item"): lambda c: suggest_items(c.store, c.q.get("q", ""), c.flag("materials", True)),
    ("GET", "/api/item"): lambda c: lookup_item(c.store, c.q.get("key", ""), c.flag("events")),
    ("GET", "/api/suggest/area"): lambda c: suggest_areas(c.store, c.q.get("q", "")),
    ("GET", "/api/area"): lambda c: lookup_area(c.store, c.q.get("type", "planet"), c.q.get("key", ""), c.flag("all"),
                                                c.flag("events")),
}
