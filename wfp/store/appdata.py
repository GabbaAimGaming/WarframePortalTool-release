"""ツールに同梱する設定(data/ の中)の読み込み。

data/ は開発側が手で編集して配布するファイル。自動更新で配布版に置き換わるので、ツールから書き込まない
(利用者のデータは userdata で ~/.wfportal に置く)。

同梱データの種類は BUNDLED の表に1行ずつ(種類 → data/ の下のフォルダ・既定のファイル名)。
読み込みは read_bundled にまとめ、種類ごとの *_dir / read_* はその薄い入口(テストで種類ごとに差し替えるため残す)。
種類を足すときは BUNDLED に1行と、*_dir / read_* を1組。形の検査は使う側(core など)で行う。
"""
from __future__ import annotations

import re
from pathlib import Path

from wfp.core import const
from wfp.store import datadir

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
    return datadir.read_json((bundled_dir(kind) if src is None else src) / name)


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


def qa_lore_dir(src: Path | None = None) -> Path:
    """解説のフォルダ(data/qa/lore/)"""
    return (qa_dir() if src is None else src) / const.QA_LORE_DIR


def read_qa_lore_index(src: Path | None = None) -> object | None:
    """解説の目次(_index.json)。無い・読めなければ None"""
    return datadir.read_json(qa_lore_dir(src) / const.QA_LORE_INDEX)


def lore_part_names(index: object) -> list[str]:
    """目次の files のうち、解説のファイルの名前として正しいもの(QA_LORE_PART_RE。フォルダの外を指す名前は読まない)。並びは目次のまま"""
    files = index.get("files") if isinstance(index, dict) else None
    return [n for n in files if isinstance(n, str) and re.match(const.QA_LORE_PART_RE, n)] if isinstance(files, list) else []


def read_qa_lore_part(name: str, src: Path | None = None) -> object | None:
    """解説のファイル1つ(`{"topics": [...]}`)。無い・読めなければ None"""
    return datadir.read_json(qa_lore_dir(src) / name)


def read_qa_lore(src: Path | None = None) -> dict | None:
    """解説(data/qa/lore/)。目次の files の順に読んで topics を繋げ、1つの形 {as_of, license, credit, topics} にする
    (core.qalore の load_lore が読む形)。目次が無い・読めなければ None。読めないファイル・topics の無いファイルは飛ばす"""
    index = read_qa_lore_index(src)
    if not isinstance(index, dict):
        return None
    topics: list = []
    for name in lore_part_names(index):
        part = read_qa_lore_part(name, src)
        rows = part.get("topics") if isinstance(part, dict) else None
        if isinstance(rows, list):
            topics += rows
    return {**{k: v for k, v in index.items() if k != "files"}, "topics": topics}


def qa_icon_path(set_id: str, name: str, src: Path | None = None) -> Path:
    """Q&A のアイコンの画像の場所(data/qa/icons/<姿の id>/<ファイル>)。名前の検査は使う側(core.qaicon の safe_name)"""
    return (qa_dir() if src is None else src) / const.QA_ICON_DIR / set_id / name


def read_qa_icon(set_id: str, name: str, src: Path | None = None) -> bytes | None:
    """Q&A のアイコンの画像のバイト列。読めなければ None"""
    try:
        return qa_icon_path(set_id, name, src).read_bytes()
    except OSError:
        return None


def read_riven_words(name: str | None = None, src: Path | None = None) -> object | None:
    return read_bundled("riven", name, riven_dir() if src is None else src)

