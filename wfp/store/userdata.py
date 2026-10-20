"""利用者のデータ(所持・マスター済み・サイクルの時刻合わせ・ビルド)の読み書き"""
from __future__ import annotations

import json
from pathlib import Path

from wfp.core.common import CYCLES, CYCLE_SOURCES


# cycles.json の形式:
#   {"cetus": {"anchor": 基準時刻, "source": "worldstate" | "manual", "synced_at": 保存した時刻}, ...,
#    "_clock": {"offset": 公式サーバーの時刻 - PC の時刻(秒), "synced_at": ...}}
#   以前の形式 {"cetus": 基準時刻(数値)} も読める(手動の時刻合わせとして扱う)
def load_cycles(d: Path) -> dict:
    f = d / "cycles.json"
    try:
        raw = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except ValueError:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    out = {}
    for key, v in raw.items():
        if key == "_clock":
            if isinstance(v, dict) and isinstance(v.get("offset"), (int, float)):
                out["_clock"] = v
        elif key in CYCLES:
            if isinstance(v, (int, float)):
                out[key] = {"anchor": float(v), "source": "manual", "synced_at": None}
            elif isinstance(v, dict) and isinstance(v.get("anchor"), (int, float)) and v.get("source") in CYCLE_SOURCES:
                out[key] = v
    return out


def save_cycles(d: Path, store: dict) -> None:
    (d / "cycles.json").write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")


def load_owned(d: Path) -> set[str]:
    f = d / "mods_owned.json"
    return {x.lower() for x in json.loads(f.read_text(encoding="utf-8"))} if f.exists() else set()


def save_owned(d: Path, owned: set[str]) -> None:
    (d / "mods_owned.json").write_text(json.dumps(sorted(owned), ensure_ascii=False), encoding="utf-8")


def load_mastered(d: Path) -> set[str]:
    f = d / "mastered.json"
    try:
        return set(json.loads(f.read_text(encoding="utf-8-sig"))) if f.exists() else set()
    except ValueError:
        return set()


def save_mastered(d: Path, done: set[str]) -> None:
    (d / "mastered.json").write_text(json.dumps(sorted(done), ensure_ascii=False, indent=0), encoding="utf-8")


# arcanes_owned.json: {"英語名(小文字)": ランク}。キーがあれば所持、値が今のランク(0〜最大ランク)
def load_arcanes_owned(d: Path) -> dict[str, int]:
    f = d / "arcanes_owned.json"
    try:
        raw = json.loads(f.read_text(encoding="utf-8-sig")) if f.exists() else {}
    except ValueError:
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(k).lower(): v for k, v in raw.items() if isinstance(v, int) and not isinstance(v, bool) and v >= 0}


def save_arcanes_owned(d: Path, owned: dict[str, int]) -> None:
    (d / "arcanes_owned.json").write_text(json.dumps(dict(sorted(owned.items())), ensure_ascii=False, indent=0),
                                          encoding="utf-8")


def load_builds(d: Path) -> list[dict]:
    f = d / "builds.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []


def save_builds(d: Path, builds: list[dict]) -> None:
    (d / "builds.json").write_text(json.dumps(builds, ensure_ascii=False, indent=2), encoding="utf-8")


# duviri_adjust.json: デュヴィリのローテーションの手動調整 {"normal": {"id": 2, "week": "2026-10-19", "set_at": 秒}, ...}
#   無いモードは同梱の data/duviri/rotate.json を使う。中身の検査は core.duviri で行う
def load_duviri_adjust(d: Path) -> dict:
    f = d / "duviri_adjust.json"
    try:
        raw = json.loads(f.read_text(encoding="utf-8-sig")) if f.exists() else {}
    except ValueError:
        return {}
    return raw if isinstance(raw, dict) else {}


def save_duviri_adjust(d: Path, adjust: dict) -> None:
    (d / "duviri_adjust.json").write_text(json.dumps(adjust, ensure_ascii=False), encoding="utf-8")


# invasion_parts.json: 侵略サイクルで取得済みにしたパーツの内部パスのリスト(同梱の data/invasion/parts.json の path)
def load_invasion_parts(d: Path) -> set[str]:
    f = d / "invasion_parts.json"
    try:
        raw = json.loads(f.read_text(encoding="utf-8-sig")) if f.exists() else []
    except ValueError:
        return set()
    return {x for x in raw if isinstance(x, str)} if isinstance(raw, list) else set()


def save_invasion_parts(d: Path, owned: set[str]) -> None:
    (d / "invasion_parts.json").write_text(json.dumps(sorted(owned), ensure_ascii=False, indent=0), encoding="utf-8")
