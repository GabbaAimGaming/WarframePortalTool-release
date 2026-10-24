"""ツールに同梱する設定(data/ の中)の読み込み。

data/ は開発側が手で編集して配布するファイル。自動更新で配布版に置き換わるので、ツールから書き込まない
(利用者のデータは userdata で ~/.wfportal に置く)。
"""
from __future__ import annotations

import json
from pathlib import Path

from wfp.core import common


def duviri_dir() -> Path:
    return common.APP_DIR / "data" / "duviri"


def spexchange_dir() -> Path:
    return common.APP_DIR / "data" / "spexchange"


def invasion_dir() -> Path:
    return common.APP_DIR / "data" / "invasion"


def mastery_dir() -> Path:
    return common.APP_DIR / "data" / "mastery"


def parts_dir() -> Path:
    return common.APP_DIR / "data" / "parts"


def read_duviri(name: str, src: Path | None = None) -> object | None:
    """data/duviri/<name> の JSON。無い・読めなければ None(形の検査は core.duviri で行う)"""
    return _read_json((duviri_dir() if src is None else src) / name)


def read_spexchange(name: str, src: Path | None = None) -> object | None:
    """data/spexchange/<name> の JSON。無い・読めなければ None(形の検査は core.spexchange で行う)"""
    return _read_json((spexchange_dir() if src is None else src) / name)


def read_invasion(name: str, src: Path | None = None) -> object | None:
    """data/invasion/<name> の JSON。無い・読めなければ None(形の検査は core.invasion で行う)"""
    return _read_json((invasion_dir() if src is None else src) / name)


def read_mastery(name: str, src: Path | None = None) -> object | None:
    """data/mastery/<name> の JSON。無い・読めなければ None(形の検査は core.mastery で行う)"""
    return _read_json((mastery_dir() if src is None else src) / name)


def read_parts(name: str, src: Path | None = None) -> object | None:
    """data/parts/<name> の JSON(クラン研究など)。無い・読めなければ None(形の検査は drops.tables の clan_rows で行う)"""
    return _read_json((parts_dir() if src is None else src) / name)


def _read_json(f: Path) -> object | None:
    try:
        return json.loads(f.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
