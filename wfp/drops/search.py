"""入手先の検索・候補選び"""
from __future__ import annotations

from typing import Callable

from wfp.core.common import MODES_JA, PLANETS_JA, RARITY_JA, SOURCE_CATS, norm, rank
from wfp.core.names import Names, item_key
from wfp.drops.tables import Drops, Sources, stage_label


def find_sources(key: str, drops: "Drops", sources: Sources | None, names: Names, events: bool = False) -> list[dict]:
    """項目(英名)の入手先を、ミッション・敵・バウンティ・レリック・クラン研究等すべてから集めて確率の高い順に返す(確率の無いクラン研究は最後)。"""
    k = item_key(key)
    out = []
    for planet, node, mode, event, rot, item, chance, rarity in drops.rows:
        if item_key(item) == k and (events or not event):
            out.append({"cat": "mission", "place": f"{PLANETS_JA.get(planet, planet)} / {node}", "planet": PLANETS_JA.get(planet, planet),
                        "node": node, "detail": MODES_JA.get(mode, mode), "event": event, "stage": stage_label(rot),
                        "qty": names.split_qty(item)[0], "chance": chance, "rarity": rarity})
    for cat, place, detail, rot, item, chance, rarity in (sources.rows if sources else []):
        if item_key(item) == k:
            out.append({"cat": cat, "place": place, "planet": "", "node": place, "detail": detail, "event": False,
                        "stage": stage_label(rot), "qty": names.split_qty(item)[0], "chance": chance, "rarity": rarity})
    order = {c: i for i, c in enumerate(SOURCE_CATS)}
    # 確率の無い入手先(クラン研究)は確率のある行のあと
    out.sort(key=lambda r: (r["chance"] is None, -(r["chance"] or 0), order.get(r["cat"], 99), r["place"]))
    for r in out:
        r["cat_ja"] = SOURCE_CATS.get(r["cat"], r["cat"])
        r["rarity_ja"] = RARITY_JA.get(r["rarity"], r["rarity"])
    return out


def all_item_names(drops: Drops, sources: Sources | None) -> list[str]:
    return sorted(set(drops.item_names) | set(sources.item_names if sources else []))


def pick_candidates(query: str, item_names, names: Names, materials_only: bool = False,
                    keep: Callable[[str], bool] | None = None) -> list[str]:
    """名前(英名・日本語名・ひらがな)が query に合う項目を、合い方の良い順に返す。
    materials_only は素材だけに絞る。keep を渡すと、それが True を返す項目だけに絞る(パーツ検索など)"""
    if isinstance(item_names, Drops):  # 以前の呼び方 (ドロップ表を直接渡す) にも対応
        item_names = item_names.item_names
    scored = []
    for n in item_names:
        if (materials_only and not names.is_resource(n)) or (keep is not None and not keep(n)):
            continue
        r = rank(query, [n, names.ja(n), names.split_qty(n)[1]])
        if r is not None:
            scored.append((r, norm(names.ja(n)), n))
    scored.sort()
    return [n for _, _, n in scored]


def group_candidates(cands: list[str], names: Names) -> dict[str, str]:
    """候補を数量違い・大文字小文字違いで束ねる -> {キー: 表示に使う英名}"""
    groups: dict[str, str] = {}
    for n in cands:
        groups.setdefault(item_key(n), names.split_qty(n)[1])
    return groups
