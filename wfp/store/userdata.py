"""利用者のデータ(所持・マスター済み・サイクルの時刻合わせ・ビルドなど)の読み書き

置き場は SQLite(wfp/store/userdb.py の userdata.db)。読み出すときに値を検査し、形の合わないものは捨てる
(前の JSON から取り込んだ値もここで同じように扱う)。

- 読むだけ: load_*(一覧の表示など)
- 変える: `with editing(d, 種類) as 値:` の中で値をその場で変える(set は add / discard、list は builds[:] = …、dict は代入)。
  開くときにほかの書き込みを待ち、読む → 変える → 書くを1つのトランザクションで行う(画面から2つ同時に来ても、
  CLI と画面が同時でも片方が消えない)。中で例外が出たら何も書かない
- save_*: まるごと置き換える(テスト・取り込み用。普段の変更は editing を使う)
"""
from __future__ import annotations

from pathlib import Path

from wfp.core.const import CYCLES, CYCLE_SOURCES
from wfp.store import userdb


# cycles: {"cetus": {"anchor": 基準時刻, "source": "worldstate" | "manual", "synced_at": 保存した時刻}, ...,
#          "_clock": {"offset": 公式サーバーの時刻 - PC の時刻(秒), "synced_at": ...}}
#   以前の形式 {"cetus": 基準時刻(数値)} も読める(手動の時刻合わせとして扱う)
def _clean_cycles(raw) -> dict:
    out = {}
    for key, v in (raw if isinstance(raw, dict) else {}).items():
        if key == "_clock":
            if isinstance(v, dict) and isinstance(v.get("offset"), (int, float)):
                out["_clock"] = v
        elif key in CYCLES:
            if isinstance(v, (int, float)):
                out[key] = {"anchor": float(v), "source": "manual", "synced_at": None}
            elif isinstance(v, dict) and isinstance(v.get("anchor"), (int, float)) and v.get("source") in CYCLE_SOURCES:
                out[key] = v
    return out


# arcanes_owned: {"英語名(小文字)": ランク}。キーがあれば所持、値が今のランク(0〜最大ランク)
def _clean_ranks(raw: dict) -> dict[str, int]:
    return {str(k).lower(): v for k, v in raw.items() if isinstance(v, int) and not isinstance(v, bool) and v >= 0}


def _as_dict(raw) -> dict:
    return raw if isinstance(raw, dict) else {}


# 種類ごとの読み出すときの検査(load_* と editing で同じものを使う)
#   mods_owned: 所持にした MOD の英語名(小文字)  mastered: マスター済みにした項目の id
#   quests_done: 完了にしたクエスト・ジャンクションの id(クエストは内部パス、ジャンクションは junction:<キー>)
#   invasion_parts: 侵略サイクルで取得済みにしたパーツの内部パス(同梱の data/invasion/parts.json の path)
#   baro_owned: バロ吉入手一覧の手動チェック(品物の英語名。小文字)  builds: ビルドの一覧(並び順のまま)
#   duviri_adjust: デュヴィリのローテーションの手動調整 {"normal": {"id", "week", "set_at"}, ...}(中身の検査は core.duviri)
#   baro_seen: この PC で記録したバロの来訪 {"visits": {来訪日: {...}}}(中身の検査は wfportal_baro)
_CLEANERS = {
    "cycles": _clean_cycles,
    "mods_owned": lambda raw: {x.lower() for x in raw},
    "mastered": set, "quests_done": set, "invasion_parts": set, "baro_owned": set,
    "arcanes_owned": _clean_ranks,
    "builds": lambda raw: [b for b in raw if isinstance(b, dict)],
    "duviri_adjust": _as_dict, "baro_seen": _as_dict,
}


def _load(d: Path, kind: str):
    return _CLEANERS[kind](userdb.read_kind(d, kind))


def editing(d: Path, kind: str):
    """`with editing(d, "mastered") as done:` の形で使う。値(load_* と同じ形)をその場で変えると、抜けるときに書く"""
    return userdb.editing_kind(d, kind, _CLEANERS[kind])


def load_cycles(d: Path) -> dict:
    return _load(d, "cycles")


def save_cycles(d: Path, store: dict) -> None:
    userdb.write_kind(d, "cycles", store)


def load_owned(d: Path) -> set[str]:
    return _load(d, "mods_owned")


def save_owned(d: Path, owned: set[str]) -> None:
    userdb.write_kind(d, "mods_owned", owned)


def load_mastered(d: Path) -> set[str]:
    return _load(d, "mastered")


def save_mastered(d: Path, done: set[str]) -> None:
    userdb.write_kind(d, "mastered", done)


def load_quests_done(d: Path) -> set[str]:
    return _load(d, "quests_done")


def save_quests_done(d: Path, done: set[str]) -> None:
    userdb.write_kind(d, "quests_done", done)


def load_arcanes_owned(d: Path) -> dict[str, int]:
    return _load(d, "arcanes_owned")


def save_arcanes_owned(d: Path, owned: dict[str, int]) -> None:
    userdb.write_kind(d, "arcanes_owned", owned)


def load_builds(d: Path) -> list[dict]:
    return _load(d, "builds")


def save_builds(d: Path, builds: list[dict]) -> None:
    userdb.write_kind(d, "builds", builds)


def load_duviri_adjust(d: Path) -> dict:
    return _load(d, "duviri_adjust")


def save_duviri_adjust(d: Path, adjust: dict) -> None:
    userdb.write_kind(d, "duviri_adjust", adjust)


def load_invasion_parts(d: Path) -> set[str]:
    return _load(d, "invasion_parts")


def save_invasion_parts(d: Path, owned: set[str]) -> None:
    userdb.write_kind(d, "invasion_parts", owned)


def load_baro_seen(d: Path) -> dict:
    return _load(d, "baro_seen")


def load_baro_owned(d: Path) -> set[str]:
    return _load(d, "baro_owned")
