"""アルケイン所持一覧"""
from __future__ import annotations

from wfp.core.common import ARCANE_CATS, ARCANE_DROP_ONLY_CATS, ARCANE_DROP_ONLY_MAX_RANK, RARITY_JA
from wfp.core.names import Names, arcane_cat


def arcane_entries(names: Names, drop_items=()) -> list[dict]:
    """所持一覧に載せるアルケイン = 公式データの一覧 + ドロップ表にだけあるもの(ARCANE_DROP_ONLY_CATS のカテゴリー)

    drop_items: ドロップ表・入手先データの英語名 (all_item_names の結果)。ドロップ表だけのものは
    日本語名・レア度が無いため、日本語名は名前辞書にあれば使い(無ければ英語名)、レア度は空にする
    """
    out = list(names.arcane_list)
    known = {m["en"].lower() for m in out}
    for name in sorted(set(drop_items), key=str.lower):
        cat = arcane_cat(name)
        if cat in ARCANE_DROP_ONLY_CATS and name.lower() not in known:
            known.add(name.lower())
            out.append({"en": name, "ja": names._get(name) or name, "cat": cat, "rarity": "",
                        "max_rank": ARCANE_DROP_ONLY_MAX_RANK, "drop_only": True})
    order = list(ARCANE_CATS)
    return sorted(out, key=lambda m: (order.index(m["cat"]) if m["cat"] in order else len(order), m["en"].lower()))


def arcane_table(names: Names, owned: dict[str, int], drop_items=()) -> list[dict]:
    """所持状況つきの一覧。ランクは最大ランクを超えないように丸める(ゲーム側で最大ランクが下がった場合に備えて)"""
    out = []
    for m in arcane_entries(names, drop_items):
        k = m["en"].lower()
        out.append({**m, "cat_ja": ARCANE_CATS.get(m["cat"], m["cat"]),
                    "rarity_ja": RARITY_JA.get(m["rarity"], m["rarity"]), "owned": k in owned,
                    "rank": min(owned[k], m["max_rank"]) if k in owned else None})
    return out


def arcane_summary(rows: list[dict]) -> dict:
    """カテゴリーごと(と全体 "all")の 件数 / 所持数 / ランク最大の数"""
    out = {c: {"total": 0, "owned": 0, "maxed": 0} for c in ARCANE_CATS}
    for r in rows:
        o = out.setdefault(r["cat"], {"total": 0, "owned": 0, "maxed": 0})
        o["total"] += 1
        o["owned"] += r["owned"]
        o["maxed"] += r["owned"] and r["rank"] == r["max_rank"]
    out["all"] = {k: sum(v[k] for v in out.values()) for k in ("total", "owned", "maxed")}
    return out


class ArcaneNotFound(ValueError):
    """一覧に無いアルケイン名"""


def set_arcanes_owned(names: Names, owned: dict[str, int], targets: list[str], is_owned: bool,
                      rank_: int | None = None, drop_items=()) -> list[dict]:
    """所持状況を変更する(owned を書き換える。保存は呼び出し側)。変更したアルケインを返す

    - is_owned=False: 未所持にする(ランクも消える)
    - is_owned=True: 所持にする。rank_ を省くと、所持済みならランクはそのまま、未所持ならランク 0
    - 一覧に無い名前は ArcaneNotFound、0〜最大ランクの範囲外のランクは ValueError (どちらも何も変更しない)
    """
    by = {m["en"].lower(): m for m in arcane_entries(names, drop_items)}
    hits = []
    for en in targets:
        m = by.get(str(en).lower())
        if m is None:
            raise ArcaneNotFound(f"アルケインが見つかりません: {en}")
        if rank_ is not None and not (0 <= rank_ <= m["max_rank"]):
            raise ValueError(f"{m['en']} のランクは 0〜{m['max_rank']} です: {rank_}")
        hits.append(m)
    for m in hits:
        k = m["en"].lower()
        if not is_owned:
            owned.pop(k, None)
        else:
            owned[k] = rank_ if rank_ is not None else min(owned.get(k, 0), m["max_rank"])
    return hits
