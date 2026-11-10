"""ツールに同梱する設定(data/ の中)の読み込み。

data/ は開発側が手で編集して配布するファイル。自動更新で配布版に置き換わるので、ツールから書き込まない
(利用者のデータは userdata で ~/.wfportal に置く)。

同梱データの種類は BUNDLED の表に1行ずつ(種類 → data/ の下のフォルダ・既定のファイル名)。
読み込みは read_bundled にまとめ、種類ごとの *_dir / read_* はその薄い入口(テストで種類ごとに差し替えるため残す)。
種類を足すときは BUNDLED に1行と、*_dir / read_* を1組。形の検査は使う側(core など)で行う。
"""
from __future__ import annotations

import json
from pathlib import Path

from wfp.core import const

# 種類 -> (data/ の下のフォルダ名, 既定のファイル名。None なら呼ぶ側が名前を渡す)
BUNDLED: dict[str, tuple[str, str | None]] = {
    "duviri": ("duviri", None),                          # デュヴィリサーキットのローテーション(core.duviri)
    "spexchange": ("spexchange", None),                  # 鋼の道のり交換のローテーション(core.spexchange)
    "invasion": ("invasion", None),                      # 侵略サイクルの獲得パーツ(core.invasion)
    "mastery": ("mastery", None),                        # マスター一覧に手で足す項目(core.mastery)
    "parts": ("parts", None),                            # クラン研究・Simaris 交換など(drops.tables の clan_rows)
    "quests": ("quests", const.QUEST_FLOW_FILE),         # クエスト・ジャンクションの前提条件(core.quests)
    "mod_stats": ("mod_stats", const.MOD_TARGETS_FILE),  # MOD 効果検索の影響先の辞書(core.modstats)
    "helminth": ("helminth", const.HELMINTH_SUBSUME_FILE),  # Helminth で吸収できるアビリティ(core.helminth)
    "archon": ("archon", const.ARCHON_SHARDS_FILE),      # アルコンの欠片の色と効果(core.archon)
    "builds": ("builds", const.DEV_BUILDS_FILE),         # 開発者のビルド(core.devbuilds)
    "summons": ("summons", const.SUMMONS_FILE),          # 呼び出し(core.summons)
    "qa": ("qa", None),                                  # Q&A の語の表・答えの文の型など(core.qa)
    "riven": ("riven", const.RIVEN_WORDS_FILE),          # Riven の画像の読み取りの効果名(wfportal_rivenscan)
}


def bundled_dir(kind: str) -> Path:
    """同梱データの種類のフォルダ(data/<フォルダ>)。表に無い種類は KeyError"""
    return const.APP_DIR / "data" / BUNDLED[kind][0]


def read_bundled(kind: str, name: str | None = None, src: Path | None = None) -> object | None:
    """同梱データの JSON。name を省けば表の既定のファイル名、src を省けば bundled_dir(kind)。
    無い・読めなければ None(形の検査は使う側で行う)"""
    if name is None:
        name = BUNDLED[kind][1]
        if name is None:
            raise ValueError(f"read_bundled: {kind} には既定のファイル名が無い")
    return _read_json((bundled_dir(kind) if src is None else src) / name)


# ---- 種類ごとの入口(フォルダ) ----

def duviri_dir() -> Path:
    return bundled_dir("duviri")


def spexchange_dir() -> Path:
    return bundled_dir("spexchange")


def invasion_dir() -> Path:
    return bundled_dir("invasion")


def mastery_dir() -> Path:
    return bundled_dir("mastery")


def parts_dir() -> Path:
    return bundled_dir("parts")


def quests_dir() -> Path:
    return bundled_dir("quests")


def mod_stats_dir() -> Path:
    return bundled_dir("mod_stats")


def helminth_dir() -> Path:
    return bundled_dir("helminth")


def archon_dir() -> Path:
    return bundled_dir("archon")


def builds_dir() -> Path:
    return bundled_dir("builds")


def summons_dir() -> Path:
    return bundled_dir("summons")


def qa_dir() -> Path:
    return bundled_dir("qa")


def riven_dir() -> Path:
    return bundled_dir("riven")


# ---- 種類ごとの入口(読み込み)。フォルダは上の *_dir から取る(テストの差し替えが効くように) ----

def read_duviri(name: str, src: Path | None = None) -> object | None:
    return read_bundled("duviri", name, duviri_dir() if src is None else src)


def read_spexchange(name: str, src: Path | None = None) -> object | None:
    return read_bundled("spexchange", name, spexchange_dir() if src is None else src)


def read_invasion(name: str, src: Path | None = None) -> object | None:
    return read_bundled("invasion", name, invasion_dir() if src is None else src)


def read_mastery(name: str, src: Path | None = None) -> object | None:
    return read_bundled("mastery", name, mastery_dir() if src is None else src)


def read_parts(name: str, src: Path | None = None) -> object | None:
    return read_bundled("parts", name, parts_dir() if src is None else src)


def read_quests(name: str | None = None, src: Path | None = None) -> object | None:
    return read_bundled("quests", name, quests_dir() if src is None else src)


def read_mod_targets(name: str | None = None, src: Path | None = None) -> object | None:
    return read_bundled("mod_stats", name, mod_stats_dir() if src is None else src)


def read_helminth(name: str | None = None, src: Path | None = None) -> object | None:
    return read_bundled("helminth", name, helminth_dir() if src is None else src)


def read_archon(name: str | None = None, src: Path | None = None) -> object | None:
    return read_bundled("archon", name, archon_dir() if src is None else src)


def read_dev_builds(name: str | None = None, src: Path | None = None) -> object | None:
    return read_bundled("builds", name, builds_dir() if src is None else src)


def read_summons(name: str | None = None, src: Path | None = None) -> object | None:
    return read_bundled("summons", name, summons_dir() if src is None else src)


def read_qa(name: str, src: Path | None = None) -> object | None:
    return read_bundled("qa", name, qa_dir() if src is None else src)


def read_riven_words(name: str | None = None, src: Path | None = None) -> object | None:
    return read_bundled("riven", name, riven_dir() if src is None else src)


def _read_json(f: Path) -> object | None:
    try:
        return json.loads(f.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
