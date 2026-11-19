"""データ置き場から読み込んで、名前辞書・ドロップ表・入手先・Vault の判定・Riven 相場・要求素材集の設計図を組み立てる"""
from __future__ import annotations

from pathlib import Path

from wfp.core.const import CLAN_FILE, DROPS_FILE, OTHER_FILE
from wfp.core.names import Names
from wfp.core.recipes import Recipes, check_recipes
from wfp.drops.tables import Drops, Resurgence, Sources, Vault, resurgence_from
from wfp.fetch import riven_stats
from wfp.store import appdata, gamedata


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


def load_sources(d: Path) -> Sources:
    """ミッション以外の入手先(wfcd/ 以下)と、同梱のクラン研究・Simaris 交換など(data/parts/clan.json / other.json)"""
    return Sources(gamedata.read_wfcd(d), appdata.read_parts(CLAN_FILE), appdata.read_parts(OTHER_FILE))


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
