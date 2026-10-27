"""画面向け API: 検索(素材の逆引き・パーツ検索・エリア検索)"""
from __future__ import annotations

from wfp.api.store import ApiError, Store, need_drops
from wfp.core.common import MASTERY_CATS, PART_SKIP_CATS, PLANETS_JA, SOURCE_CATS, name_txt, norm, rank, txt
from wfp.core.names import Names, item_key
from wfp.drops.search import find_sources, group_candidates, pick_candidates
from wfp.drops.tables import mission_place, stage_label


SUGGEST_LIMIT = 10  # 候補として返す最大件数(数量違いを束ねた後)。素材から探す・パーツ検索で共用


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
        if len(out) >= SUGGEST_LIMIT:
            break
    return out


def part_with_owner(names: Names, owners: dict[str, str], name: str) -> tuple[str, str] | None:
    """パーツ検索の対象なら (本体の英名, カテゴリー)。Names.part_of に加えて、
    同梱データの extras(設計図ではない作成素材。例: Mandachord)は本体(Octavia)のカテゴリーで扱う"""
    hit = names.part_of(name)
    if hit is None and (owner := owners.get(item_key(name))):
        hit = names.part_of(owner)
    return hit


def suggest_parts(store: Store, q: str, cat: str, no_prime: bool = False) -> dict:
    """パーツ検索の候補。Warframe・武器などの本体・設計図・パーツ(Names.part_of)だけを返す。

    cats はカテゴリーごとの件数(q に合うもの。並びは MASTERY_CATS)、items は cat で絞った候補(最大 SUGGEST_LIMIT 件)、
    total は絞った後の全件数。カテゴリー名は画面の I18N(part.cat.<キー>)で付ける。入手先は /api/item で引く
    no_prime なら入手先にレリックがある項目(Sources.relic_items)を除く(画面の「Prime を除外する」。件数も除いた後の数)
    """
    if cat and (cat not in MASTERY_CATS or cat in PART_SKIP_CATS):
        raise ApiError(txt("err.part.cat"), 400)
    need_drops(store)
    names, src = store.names(), store.sources()
    owners = src.part_owner if src else {}
    relic = src.relic_items if src and no_prime else set()
    part = lambda n: part_with_owner(names, owners, n)  # noqa: E731
    parts = [n for n in store.all_items() if part(n) and item_key(n) not in relic]
    if q.strip():
        cands = pick_candidates(q, parts, names)
    else:
        cands = sorted(parts, key=lambda n: norm(names.ja(n)))
    bases = list(group_candidates(cands, names).values())  # 数量違いを束ねた、表示に使う英名
    cat_by = {b: part(b)[1] for b in bases}
    counts: dict[str, int] = {}
    for c in cat_by.values():
        counts[c] = counts.get(c, 0) + 1
    picked = [b for b in bases if not cat or cat_by[b] == cat]
    return {
        "total": len(picked),
        "cats": [{"key": c, "n": counts[c]} for c in MASTERY_CATS if c in counts],
        "items": [{"key": b, "ja": names.ja(b), "en": b, "cat": cat_by[b]} for b in picked[:SUGGEST_LIMIT]],
    }


def lookup_item(store: Store, key: str, events: bool) -> dict:
    drops, names = need_drops(store), store.names()
    rows = find_sources(key, drops, store.sources(), names, events=events)
    if not rows:
        raise ApiError(txt("err.item.none"), 404)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["cat"]] = counts.get(r["cat"], 0) + 1
    return {
        "ja": names.ja(key), "en": key, "total": len(rows),
        "cats": [{"key": c, "n": counts[c]} for c in SOURCE_CATS if c in counts],  # 種類の名前は画面の I18N(src.cat.<キー>)
        "rows": rows,  # rarity はキー。place・detail・stage はテキスト指定
    }


def planets(store: Store) -> list[dict]:
    """惑星の一覧。name は表示名のテキスト指定(画面の I18N の planet.<英名>)"""
    drops = need_drops(store)
    return [{"type": "planet", "key": p, "name": name_txt("planet.", p)} for p in drops.planets]


def suggest_areas(store: Store, q: str) -> list[dict]:
    """惑星・ノードの候補。惑星は英名・日本語名(PLANETS_JA)のどちらでも探せる。ノード名は英語(sub は惑星のテキスト指定)"""
    drops = need_drops(store)
    if not q.strip():
        return planets(store)
    out = [p for p in planets(store) if rank(q, [p["key"], PLANETS_JA.get(p["key"], p["key"])]) is not None]
    for planet, node in drops.node_order:
        if rank(q, [node]) is not None:
            out.append({"type": "node", "key": f"{planet}|{node}", "name": node, "sub": name_txt("planet.", planet)})
    return out[:80]


def lookup_area(store: Store, kind: str, key: str, all_items: bool, events: bool) -> dict:
    drops, names = need_drops(store), store.names()
    if kind == "planet":
        targets = [(p, n) for p, n in drops.node_order if p == key]
        title = name_txt("planet.", key)
    else:
        planet, _, node = key.partition("|")
        targets = [(planet, node)]
        title = mission_place(planet, node)
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
            "ja": names.ja(r[5]), "en": r[5], "chance": r[6], "rarity": r[7],
        } for r in sorted(lst, key=lambda x: -x[6])]} for rot, lst in sorted(by_rot.items())]
        if stages or kind == "node":
            nodes.append({"planet": name_txt("planet.", planet), "node": node,
                          "mode": name_txt("mode.", rows[0][2]), "event": rows[0][3], "stages": stages})
    return {"title": title, "nodes": nodes}


# (メソッド, パス) -> 処理。c はリクエスト(wfp/api/server.py の Request)
ROUTES = {
    ("GET", "/api/suggest/item"): lambda c: suggest_items(c.store, c.q.get("q", ""), c.flag("materials", True)),
    ("GET", "/api/suggest/part"): lambda c: suggest_parts(c.store, c.q.get("q", ""), c.q.get("cat", ""), c.flag("noprime")),
    ("GET", "/api/item"): lambda c: lookup_item(c.store, c.q.get("key", ""), c.flag("events")),
    ("GET", "/api/suggest/area"): lambda c: suggest_areas(c.store, c.q.get("q", "")),
    ("GET", "/api/area"): lambda c: lookup_area(c.store, c.q.get("type", "planet"), c.q.get("key", ""), c.flag("all"),
                                                c.flag("events")),
}
