"""公式由来のデータ(ドロップ表・入手先・名前辞書・Riven 相場・ノード名)のファイル読み書き"""
from __future__ import annotations

import json
from pathlib import Path

from wfp.core.common import REGIONS_FILE, WFCD_EXTRA


def read_names(d: Path) -> dict | None:
    """names.json の中身。無ければ None"""
    f = d / "names.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def read_drops(d: Path) -> dict | None:
    """missionRewards.json の中身。無ければ None"""
    f = d / "missionRewards.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def read_wfcd(d: Path) -> dict[str, dict]:
    """wfcd/ 以下の各 JSON({ファイル名: 中身})。無い・読めないファイルは飛ばす"""
    files = {}
    for name in WFCD_EXTRA:
        f = d / "wfcd" / f"{name}.json"
        if f.exists():
            try:
                files[name] = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
    return files


def read_rivens(d: Path):
    """rivens.json の中身(形はそろえていない)。無い・読めなければ None"""
    f = d / "rivens.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def save_rivens(d: Path, rows: list[dict]) -> None:
    (d / "rivens.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")


def read_regions(d: Path) -> dict:
    """regions.json(ノードの内部名 -> 名前)。無い・読めなければ空"""
    f = d / REGIONS_FILE
    try:
        j = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except (OSError, ValueError):
        return {}
    return j if isinstance(j, dict) else {}


def save_regions(d: Path, regions: dict) -> None:
    (d / REGIONS_FILE).write_text(json.dumps(regions, ensure_ascii=False), encoding="utf-8")
