"""MOD 入手一覧"""
from __future__ import annotations

from wfp.core.common import COMPAT_JA, MODES_JA, MOD_TYPES, PLANETS_JA, POLARITY_EN, RARITY_JA, SOURCE_CATS
from wfp.core.names import Names, item_key
from wfp.drops.tables import Drops, Sources, stage_label


def mod_table(names: Names, drops: Drops | None, sources: Sources | None, owned: set[str] | None = None) -> list[dict]:
    """MOD ごとに入手先の件数と、もっとも確率の高い入手先をまとめる。"""
    idx: dict[str, list[tuple]] = {}
    for planet, node, mode, event, rot, item, chance, rarity in (drops.rows if drops else []):
        if not event:
            idx.setdefault(item_key(item), []).append(
                ("mission", f"{PLANETS_JA.get(planet, planet)} / {node}", MODES_JA.get(mode, mode), stage_label(rot), chance))
    for cat, place, detail, rot, item, chance, rarity in (sources.rows if sources else []):
        idx.setdefault(item_key(item), []).append((cat, place, detail, stage_label(rot), chance))
    owned = owned or set()
    out = []
    for m in names.mods:
        src = idx.get(m["en"].lower(), [])
        counts: dict[str, int] = {}
        for s in src:
            counts[s[0]] = counts.get(s[0], 0) + 1
        best = max(src, key=lambda s: s[4]) if src else None
        out.append({
            **m, "type_ja": MOD_TYPES.get(m["type"], m["type"]), "compat_ja": COMPAT_JA.get(m.get("compat", ""), m.get("compat", "")), "polarity_name": POLARITY_EN.get(m["polarity"], m["polarity"]),
            "rarity_ja": RARITY_JA.get(m["rarity"], m["rarity"]), "owned": m["en"].lower() in owned,
            "counts": {c: counts[c] for c in SOURCE_CATS if c in counts}, "total": len(src),
            "best": {"cat": best[0], "cat_ja": SOURCE_CATS[best[0]], "place": best[1], "detail": best[2],
                     "stage": best[3], "chance": best[4]} if best else None,
        })
    return out
