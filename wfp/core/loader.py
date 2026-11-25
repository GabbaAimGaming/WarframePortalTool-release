"""データ置き場から読み込んで、名前辞書・ドロップ表・入手先・Vault の判定・Riven 相場・要求素材集の設計図を組み立てる"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from wfp.core.const import CLAN_FILE, DROPS_FILE, OTHER_FILE
from wfp.core.names import Names
from wfp.core.offers import offer_rows, vendors_on
from wfp.core.recipes import Recipes, check_recipes
from wfp.drops.tables import Drops, Resurgence, Sources, Vault, resurgence_from
from wfp.fetch import riven_stats
from wfp.store import appdata, gamedata, userdata, userdb


DROPS_MISSING = "ドロップ表がありません。先に `python wfportal.py update` を実行してください。"


class DropsMissing(Exception):
    """ドロップ表(missionRewards.json)がまだ無い"""


def load_names(d: Path) -> Names:
    """名前辞書。names.json が無ければ空、壊れていれば gamedata.DataBroken"""
    return Names.from_json(gamedata.read_names(d))


def load_drops(d: Path) -> Drops:
    """ドロップ表。無ければ DropsMissing、壊れていれば gamedata.DataBroken"""
    raw = gamedata.read_drops(d)
    if raw is None:
        raise DropsMissing(DROPS_MISSING)
    try:
        return Drops(raw)
    except (AttributeError, KeyError, TypeError, ValueError) as e:  # JSON としては読めるが、中の形が違う
        raise gamedata.DataBroken(DROPS_FILE) from e


def vendor_choices(d: Path) -> dict[str, bool]:
    """入手先に出す商人の選択(利用者データ offer_vendors)。利用者データを読めなければ選択なし(初期値)で続ける
    (利用者データが壊れていても入手先の検索は止めない。壊れていることは利用者データを使うほかの機能が知らせる)"""
    try:
        return userdata.load_offer_vendors(d)
    except (userdb.UserDbError, sqlite3.Error):
        return {}


def load_sources(d: Path, choices: dict[str, bool] | None = None) -> Sources:
    """ミッション以外の入手先(wfcd/ 以下)と、同梱のクラン研究・Simaris 交換など(data/parts/clan.json / other.json)、
    オプションのシンジケート・クエスト報酬・商人(offers.json。無ければ足さない。名前は item_paths.json と名前辞書で引く。
    商人は利用者が選んだものだけ。choices は商人の選択(省略すると vendor_choices で読む。API は Store が覚えた値を渡す))"""
    offers = None
    raw = gamedata.read_offers(d)
    if raw is not None:
        try:
            names = load_names(d)
        except gamedata.DataBroken:
            names = Names()
        chosen = vendor_choices(d) if choices is None else choices
        offers = offer_rows(raw, gamedata.read_item_paths(d), names, vendors_on(chosen))
    return Sources(gamedata.read_wfcd(d), appdata.read_parts(CLAN_FILE), appdata.read_parts(OTHER_FILE), offers)


def load_resurgence(d: Path) -> Resurgence:
    """Prime Resurgence の期間と交換できるレリック(worldstate.json の resurgence と item_paths.json)。無ければ空"""
    snap = gamedata.read_worldstate(d) or {}
    return resurgence_from(snap.get("resurgence"), gamedata.read_item_paths(d))


def load_vault(d: Path, drops: Drops | None, sources: Sources | None) -> Vault:
    """Vault 入りの判定(いま Prime Resurgence で交換できるレリックは外す)。CLI 用(API は Store.vault)"""
    return Vault(drops, sources, load_resurgence(d))


def load_recipes(d: Path) -> Recipes:
    """要求素材集の設計図(recipes.json)。無い・読めなければ空"""
    return check_recipes(gamedata.read_recipes(d))


def load_rivens(d: Path) -> list[dict] | None:
    """Riven 相場を読んで形をそろえる。無い・読めない・空なら None"""
    raw = gamedata.read_rivens(d)
    if raw is None:
        return None
    try:
        rows = riven_stats.normalize_rivens(raw)
    except ValueError:
        return None
    return rows or None
