"""データ置き場から読み込んで、名前辞書・ドロップ表・入手先・Riven 相場を組み立てる"""
from __future__ import annotations

from pathlib import Path

from wfp.core.names import Names
from wfp.drops.tables import Drops, Sources
from wfp.fetch import riven_stats
from wfp.store import gamedata


DROPS_MISSING = "ドロップ表がありません。先に `python wfportal.py update` を実行してください。"


class DropsMissing(Exception):
    """ドロップ表(missionRewards.json)がまだ無い"""


def load_names(d: Path) -> Names:
    """名前辞書。names.json が無ければ空"""
    return Names.from_json(gamedata.read_names(d))


def load_drops(d: Path) -> Drops:
    """ドロップ表。無ければ DropsMissing"""
    raw = gamedata.read_drops(d)
    if raw is None:
        raise DropsMissing(DROPS_MISSING)
    return Drops(raw)


def load_sources(d: Path) -> Sources:
    """ミッション以外の入手先(wfcd/ 以下)"""
    return Sources(gamedata.read_wfcd(d))


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
