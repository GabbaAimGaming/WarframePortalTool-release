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


def quests_dir() -> Path:
    return common.APP_DIR / "data" / "quests"


def read_quests(name: str = common.QUEST_FLOW_FILE, src: Path | None = None) -> object | None:
    """data/quests/<name> の JSON(クエスト・ジャンクションの前提条件)。無い・読めなければ None(形の検査は core.quests で行う)"""
    return _read_json((quests_dir() if src is None else src) / name)


def mod_stats_dir() -> Path:
    return common.APP_DIR / "data" / "mod_stats"


def helminth_dir() -> Path:
    return common.APP_DIR / "data" / "helminth"


def read_helminth(name: str = common.HELMINTH_SUBSUME_FILE, src: Path | None = None) -> object | None:
    """data/helminth/<name> の JSON(Helminth で吸収できるアビリティの一覧)。無い・読めなければ None(形の検査は core.helminth で行う)"""
    return _read_json((helminth_dir() if src is None else src) / name)


def archon_dir() -> Path:
    return common.APP_DIR / "data" / "archon"


def read_archon(name: str = common.ARCHON_SHARDS_FILE, src: Path | None = None) -> object | None:
    """data/archon/<name> の JSON(アルコンの欠片の色と効果の一覧)。無い・読めなければ None(形の検査は core.archon で行う)"""
    return _read_json((archon_dir() if src is None else src) / name)


def builds_dir() -> Path:
    return common.APP_DIR / "data" / "builds"


def read_dev_builds(name: str = common.DEV_BUILDS_FILE, src: Path | None = None) -> object | None:
    """data/builds/<name> の JSON(開発者のビルド)。無い・読めなければ None(形の検査は core.devbuilds で行う)"""
    return _read_json((builds_dir() if src is None else src) / name)


def summons_dir() -> Path:
    return common.APP_DIR / "data" / "summons"


def read_summons(name: str = common.SUMMONS_FILE, src: Path | None = None) -> object | None:
    """data/summons/<name> の JSON(呼び出しの一覧)。無い・読めなければ None(形の検査は core.summons で行う)"""
    return _read_json((summons_dir() if src is None else src) / name)


def qa_dir() -> Path:
    return common.APP_DIR / "data" / "qa"


def read_qa(name: str, src: Path | None = None) -> object | None:
    """data/qa/<name> の JSON(Q&A のキーワードの表・答えの文の型・ヒットしなかったときの文)。無い・読めなければ None(形の検査は core.qa で行う)"""
    return _read_json((qa_dir() if src is None else src) / name)


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


def read_mod_targets(name: str = common.MOD_TARGETS_FILE, src: Path | None = None) -> object | None:
    """data/mod_stats/<name> の JSON(MOD 効果検索の影響先の辞書)。無い・読めなければ None(形の検査は core.modstats で行う)"""
    return _read_json((mod_stats_dir() if src is None else src) / name)


def riven_dir() -> Path:
    return common.APP_DIR / "data" / "riven"


def read_riven_words(name: str = common.RIVEN_WORDS_FILE, src: Path | None = None) -> object | None:
    """data/riven/<name> の JSON(Riven の画像の読み取りで使う効果名の辞書)。無い・読めなければ None(形の検査は wfportal_rivenscan で行う)"""
    return _read_json((riven_dir() if src is None else src) / name)


def _read_json(f: Path) -> object | None:
    try:
        return json.loads(f.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
