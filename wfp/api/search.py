"""画面向け API: 検索(アイテムから探す・エリア検索)"""
from __future__ import annotations

from wfp.api.store import ApiError, Store, need_drops
from wfp.core.common import ITEM_KIND_DEFAULT, MASTERY_CATS, PART_SKIP_CATS, PLANETS_JA, SOURCE_CATS, name_txt, norm, rank, txt
from wfp.core.names import item_key
from wfp.drops.search import area_stages, find_sources, group_candidates, parse_kinds, pick_candidates
from wfp.drops.tables import mission_place, stage_label


SUGGEST_LIMIT = 10  # 候補として返す最大件数(数量違いを束ねた後)


def suggest_items(store: Store, q: str, kinds: set[str], cat: str = "", no_prime: bool = False) -> dict:
    """アイテムから探すの候補。種類(AREA_KINDS のキー。Names.item_kind)が kinds に入る項目だけを返す。

    items は候補(最大 SUGGEST_LIMIT 件。kind は種類のキー、パーツなら cat にカテゴリー)、total は絞った後の全件数。
    パーツ(part)だけに効く絞り込み: cat はマスター一覧のカテゴリー(MASTERY_CATS)、
    no_prime は入手先にレリックがある項目(Sources.relic_items)を除く(画面の「Prime を除外する」。名前ではなく入手先で判定するので、
    バウンティで出る Galariak Prime などは残る)。ほかの種類はどちらにも影響されない。
    cats はパーツのカテゴリーごとの件数(q と種類に合うもの。cat で絞る前。並びは MASTERY_CATS)。名前は画面の I18N(mastery.cat.<キー>)
    """
    if cat and (cat not in MASTERY_CATS or cat in PART_SKIP_CATS):
        raise ApiError(txt("err.part.cat"), 400)
    need_drops(store)
    names, src = store.names(), store.sources()
    owners = src.part_owner if src else {}
    relic = src.relic_items if src and no_prime else set()
    kind_of: dict[str, str] = {}
    for n in store.all_items():
        kind = names.item_kind(n, owners)
        if kind in kinds and not (kind == "part" and item_key(n) in relic):
            kind_of[n] = kind
    if q.strip():
        cands = pick_candidates(q, kind_of, names)
    else:
        cands = sorted(kind_of, key=lambda n: norm(names.ja(n)))
    rows = []
    counts: dict[str, int] = {}
    for base in group_candidates(cands, names).values():  # 数量違いを束ねた、表示に使う英名
        kind = names.item_kind(base, owners)
        part_cat = names.part_of(base, owners)[1] if kind == "part" else ""
        if part_cat:
            counts[part_cat] = counts.get(part_cat, 0) + 1
        if not cat or kind != "part" or part_cat == cat:
            rows.append({"key": base, "ja": names.ja(base), "en": base, "kind": kind, "cat": part_cat})
    return {
        "total": len(rows),
        "cats": [{"key": c, "n": counts[c]} for c in MASTERY_CATS if c in counts],
        "items": rows[:SUGGEST_LIMIT],
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


def lookup_area(store: Store, kind: str, key: str, kinds: set[str], events: bool) -> dict:
    """惑星・ノードのドロップをステージごとに返す。kinds は出す種類(AREA_KINDS のキー)の集まり。
    各アイテムの kind は種類のキー(画面は I18N の area.kind.<キー>)"""
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
        stages = [{"stage": stage_label(rot), "items": [{
            "ja": names.ja(r[5]), "en": r[5], "chance": r[6], "rarity": r[7], "kind": item_kind,
        } for r, item_kind in lst]} for rot, lst in area_stages(rows, names, kinds).items()]
        if stages or kind == "node":
            nodes.append({"planet": name_txt("planet.", planet), "node": node,
                          "mode": name_txt("mode.", rows[0][2]), "event": rows[0][3], "stages": stages})
    return {"title": title, "nodes": nodes}


# (メソッド, パス) -> 処理。c はリクエスト(wfp/api/server.py の Request)
ROUTES = {
    ("GET", "/api/suggest/item"): lambda c: suggest_items(c.store, c.q.get("q", ""), parse_kinds(c.q.get("kinds"), ITEM_KIND_DEFAULT),
                                                          c.q.get("cat", ""), c.flag("noprime")),
    ("GET", "/api/item"): lambda c: lookup_item(c.store, c.q.get("key", ""), c.flag("events")),
    ("GET", "/api/suggest/area"): lambda c: suggest_areas(c.store, c.q.get("q", "")),
    ("GET", "/api/area"): lambda c: lookup_area(c.store, c.q.get("type", "planet"), c.q.get("key", ""),
                                                parse_kinds(c.q.get("kinds")), c.flag("events")),
}
