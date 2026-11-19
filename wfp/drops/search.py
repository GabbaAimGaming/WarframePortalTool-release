"""入手先の検索・候補選び"""
from __future__ import annotations

from typing import Callable

from wfp.core.common import rank
from wfp.core.i18n import name_txt, render_ja, txt
from wfp.core.text import norm
from wfp.core.const import AREA_KIND_DEFAULT, AREA_KINDS, SOURCE_CATS
from wfp.core.names import Names, item_key
from wfp.drops.tables import DropRow, Drops, Sources, Vault, mission_place, stage_label


def find_sources(key: str, drops: "Drops", sources: Sources | None, names: Names, events: bool = False,
                 vault: Vault | None = None) -> list[dict]:
    """項目(英名)の入手先を、ミッション・敵・バウンティ・レリック・クラン研究等すべてから集めて確率の高い順に返す(確率の無いクラン研究は最後)。

    cat は入手先の種類のキー(SOURCE_CATS)、敵の行だけ enemy に敵の英名(敵から探すへのリンク用)、rarity はレア度のキー(Common など)、place・detail・stage はテキスト指定。
    vault を渡すと、Vault 入り(いまは出ない)レリックの行に vaulted: True を付ける
    (wfp/core/i18n.py の txt。画面は web/i18n の表で、CLI は render_ja で文にする)。並びは日本語の入手先名で決める。
    Prime Resurgence の期間の内(vault.resurgence)なら、交換できるレリックの行に resurgence: 期限(UNIX 時刻)を付け、
    項目がそのレリック自体なら入手先「Prime Resurgence」の行(cat resurgence・until に期限)を足す
    """
    k = item_key(key)
    out = []
    for planet, node, mode, event, rot, item, chance, rarity in drops.rows:
        if item_key(item) == k and (events or not event):
            out.append({"cat": "mission", "place": mission_place(planet, node), "detail": name_txt("mode.", mode), "event": event,
                        "stage": stage_label(rot), "qty": names.split_qty(item)[0], "chance": chance, "rarity": rarity})
    for r in (sources.rows if sources else []):
        if item_key(r.item) == k:
            row = {"cat": r.cat, "place": r.place, "detail": r.detail, "event": False,
                   "stage": stage_label(r.rot), "qty": names.split_qty(r.item)[0], "chance": r.chance, "rarity": r.rarity}
            if r.cat == "enemy":
                row["enemy"] = r.place  # 敵の英名(画面はここから敵から探すへ移る)
            if vault is not None and r.relic and vault.relic_vaulted(r.relic):
                row["vaulted"] = True
            elif vault is not None and r.relic and vault.relic_offered(r.relic):
                row["resurgence"] = vault.until
            out.append(row)
    if vault is not None and vault.relic_offered(key):
        out.append(_resurgence_row(vault))
    order = {c: i for i, c in enumerate(SOURCE_CATS)}
    # 確率の無い入手先(クラン研究)は確率のある行のあと
    out.sort(key=lambda r: (r["chance"] is None, -(r["chance"] or 0), order.get(r["cat"], 99), render_ja(r["place"])))
    return out


def _resurgence_row(vault: Vault) -> dict:
    """レリック自体の入手先「Prime Resurgence」の行(アヤで交換。確率は無い。until は期限)"""
    return {"cat": "resurgence", "place": txt("src.resurgence.place"), "detail": txt("src.resurgence.detail"), "event": False,
            "stage": stage_label("-"), "qty": "", "chance": None, "rarity": "", "until": vault.until}


def all_item_names(drops: Drops, sources: Sources | None, extra: list[str] | tuple = ()) -> list[str]:
    """候補になる項目の英名。extra はドロップ表に無いが入手先がある項目(いま Prime Resurgence で交換できるレリック)"""
    return sorted(set(drops.item_names) | set(sources.item_names if sources else []) | set(extra))


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


def area_stages(rows: list[DropRow], names: Names, kinds: set[str]) -> dict[str, list[tuple[DropRow, str]]]:
    """エリア検索: 1ノードのドロップ行(Drops.node_rows)をローテーションごとに分け、{ローテーション: [(行, 種類)]} で返す。

    kinds は出す種類(AREA_KINDS のキー)の集まり。並びは種類の順(AREA_KINDS の順)→ 確率の高い順。知らないキーは無視する
    """
    order = list(AREA_KINDS)
    out: dict[str, list[tuple[DropRow, str]]] = {}
    for row in rows:
        kind = names.item_kind(row.item)
        if kind in kinds:
            out.setdefault(row.rot, []).append((row, kind))
    for lst in out.values():
        lst.sort(key=lambda pair: (order.index(pair[1]), -pair[0].chance))
    return dict(sorted(out.items()))


def parse_kinds(raw: object, default: tuple[str, ...] = AREA_KIND_DEFAULT) -> set[str]:
    """画面から来た種類の指定("resource,part" など)を AREA_KINDS のキーの集まりにする。None(指定なし)なら default"""
    if raw is None:
        return set(default)
    return {k for k in str(raw).split(",") if k in AREA_KINDS}


def pick_enemies(query: str, enemies: list[str]) -> list[str]:
    """敵の名前(英名)が query に合うものを、合い方の良い順(同じなら名前順)に返す。query が空なら何も返さない(敵は千件以上あるため)"""
    scored = [(r, norm(n), n) for n in enemies if (r := rank(query, [n])) is not None]
    scored.sort()
    return [n for _, _, n in scored]


def enemy_drops(enemy: str, sources: Sources | None, names: Names, kinds: set[str]) -> list[dict]:
    """敵から探す: 1体の敵が落とすアイテム(Sources の enemy の行)を返す。

    kinds は出す種類(AREA_KINDS のキー)の集まり。並びは種類の順(AREA_KINDS の順)→ 確率の高い順 → 英名。
    同じアイテムでも表(素材・MOD・設計図など)が違えば別の行。detail は表のテキスト指定、chance は1体倒したときに落とす割合(%)、
    kind は種類のキー、qty は数量(無ければ "")、rarity はレア度のキー
    """
    order = list(AREA_KINDS)
    owners = sources.part_owner if sources else {}
    out = []
    for r in (sources.rows if sources else []):
        if r.cat != "enemy" or r.place != enemy:
            continue
        kind = names.item_kind(r.item, owners)
        if kind not in kinds:
            continue
        qty, base = names.split_qty(r.item)
        out.append({"en": base, "ja": names.ja(base), "kind": kind, "detail": r.detail, "qty": qty,
                    "chance": r.chance, "rarity": r.rarity})
    out.sort(key=lambda r: (order.index(r["kind"]), -(r["chance"] or 0), r["en"].lower()))
    return out
