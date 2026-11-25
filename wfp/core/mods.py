"""MOD 入手一覧"""
from __future__ import annotations

from wfp.core.const import POLARITY_EN
from wfp.core.names import Names
from wfp.drops.search import source_brief, source_index
from wfp.drops.tables import Drops, Sources


def mod_table(names: Names, drops: Drops | None, sources: Sources | None, owned: set[str] | None = None,
              confirmed: set[str] | None = None, index: dict[str, list[tuple]] | None = None) -> list[dict]:
    """MOD ごとに入手先の件数と、もっとも確率の高い入手先をまとめる(drops/search の source_brief)。best の place・detail・stage はテキスト指定。
    confirmed は画面の読み取りで利用者が所持と確定した MOD(英名の小文字。所持のものだけ印を付ける)。
    種別(type)・対象(compat)・レア度(rarity)はキーのまま(表示名は画面の I18N / CLI は MOD_TYPES・COMPAT_JA・RARITY_JA)。
    index は作り済みの source_index(画面の API は Store.source_index で覚えたもの)。省くと drops・sources から作る"""
    idx = index if index is not None else source_index(drops, sources)
    owned, confirmed = owned or set(), confirmed or set()
    out = []
    for m in names.mods:
        k = m["en"].lower()
        out.append({
            **m, "polarity_name": POLARITY_EN.get(m["polarity"], m["polarity"]), "owned": k in owned,
            "confirmed": k in owned and k in confirmed, **source_brief(idx.get(k, [])),
        })
    return out
