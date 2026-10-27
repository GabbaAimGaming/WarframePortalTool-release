"""MOD 入手一覧"""
from __future__ import annotations

from wfp.core.common import POLARITY_EN, SOURCE_CATS, name_txt
from wfp.core.names import Names, item_key
from wfp.drops.tables import Drops, Sources, mission_place, stage_label


def mod_table(names: Names, drops: Drops | None, sources: Sources | None, owned: set[str] | None = None) -> list[dict]:
    """MOD ごとに入手先の件数と、もっとも確率の高い入手先をまとめる。best の place・detail・stage はテキスト指定。
    種別(type)・対象(compat)・レア度(rarity)はキーのまま(表示名は画面の I18N / CLI は MOD_TYPES・COMPAT_JA・RARITY_JA)"""
    idx: dict[str, list[tuple]] = {}
    for planet, node, mode, event, rot, item, chance, rarity in (drops.rows if drops else []):
        if not event:
            idx.setdefault(item_key(item), []).append(
                ("mission", mission_place(planet, node), name_txt("mode.", mode), stage_label(rot), chance))
    for cat, place, detail, rot, item, chance, rarity in (sources.rows if sources else []):
        idx.setdefault(item_key(item), []).append((cat, place, detail, stage_label(rot), chance))
    owned = owned or set()
    out = []
    for m in names.mods:
        src = idx.get(m["en"].lower(), [])
        counts: dict[str, int] = {}
        for s in src:
            counts[s[0]] = counts.get(s[0], 0) + 1
        best = max(src, key=lambda s: -1 if s[4] is None else s[4]) if src else None  # 確率の無い入手先(クラン研究)は最後
        out.append({
            **m, "polarity_name": POLARITY_EN.get(m["polarity"], m["polarity"]), "owned": m["en"].lower() in owned,
            "counts": {c: counts[c] for c in SOURCE_CATS if c in counts}, "total": len(src),
            "best": {"cat": best[0], "place": best[1], "detail": best[2],
                     "stage": best[3], "chance": best[4]} if best else None,
        })
    return out
