"""公式由来のデータ(ドロップ表・入手先・名前辞書・日英のほかの言語の名前辞書・Riven 相場・ノード名)のファイル読み書き。

書くときは datadir.write_atomic(一時ファイル + os.replace)で、途中で落ちても前のファイルを残す
"""
from __future__ import annotations

import json
from pathlib import Path

from wfp.core.errors import TextError
from wfp.core.i18n import txt
from wfp.core.const import (
    ARBYS_FILE, BUILDER_FILE, DROPS_FILE, EXPORT_EXTRA_LANGS, ITEM_PATHS_FILE, LANG_NAMES_FILE, MOD_STATS_FILE, NAMES_FILE,
    RECIPES_FILE, REGIONS_FILE, RIVENS_FILE, WFCD_DIR, WFCD_EXTRA, WORLDSTATE_FILE,
)
from wfp.store import datadir


def _write_json(f: Path, obj) -> None:
    """JSON を途中で壊さずに書く(datadir.write_atomic)"""
    datadir.write_atomic(f, json.dumps(obj, ensure_ascii=False))


def save_drops(d: Path, raw: bytes) -> None:
    """ドロップ表(missionRewards.json)を取得したまま書く(JSON として読めるかは取得側で確かめる)"""
    datadir.write_atomic(d / DROPS_FILE, raw)


def save_wfcd(d: Path, name: str, raw: bytes) -> None:
    """ドロップ表のほかの入手先(wfcd/<名前>.json)を取得したまま書く。名前は WFCD_EXTRA にあるものだけ(ファイル名に任意の文字を入れない)"""
    if name not in WFCD_EXTRA:
        raise TextError(txt("err.update.wfcd_unknown", name=name))
    (d / WFCD_DIR).mkdir(exist_ok=True)
    datadir.write_atomic(d / WFCD_DIR / f"{name}.json", raw)


def save_names(d: Path, names: dict) -> None:
    """名前辞書(names.json)を書く"""
    _write_json(d / NAMES_FILE, names)


def read_names(d: Path) -> dict | None:
    """names.json の中身。無ければ None"""
    f = d / NAMES_FILE
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def read_drops(d: Path) -> dict | None:
    """missionRewards.json の中身。無ければ None"""
    f = d / DROPS_FILE
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def read_wfcd(d: Path) -> dict[str, dict]:
    """wfcd/ 以下の各 JSON({ファイル名: 中身})。無い・読めないファイルは飛ばす"""
    files = {}
    for name in WFCD_EXTRA:
        f = d / WFCD_DIR / f"{name}.json"
        if f.exists():
            try:
                files[name] = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
    return files


def read_rivens(d: Path):
    """rivens.json の中身(形はそろえていない)。無い・読めなければ None"""
    f = d / RIVENS_FILE
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def save_rivens(d: Path, rows: list[dict]) -> None:
    _write_json(d / RIVENS_FILE, rows)


def read_regions(d: Path) -> dict:
    """regions.json(ノードの内部名 -> 名前)。無い・読めなければ空"""
    f = d / REGIONS_FILE
    try:
        j = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except (OSError, ValueError):
        return {}
    return j if isinstance(j, dict) else {}


def save_regions(d: Path, regions: dict) -> None:
    _write_json(d / REGIONS_FILE, regions)


def read_arbys(d: Path) -> str | None:
    """arbys.txt(仲裁のスケジュール。取得したまま)。無い・読めなければ None(行の検査は core.arbitration で行う)"""
    try:
        return (d / ARBYS_FILE).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None


def save_arbys(d: Path, text: str) -> None:
    datadir.write_atomic(d / ARBYS_FILE, text, newline="\n")


def read_mod_stats(d: Path) -> dict | None:
    """mod_stats.json(MOD 効果検索用。データ更新で Export から作る)。無い・読めなければ None(形の検査は core.modstats で行う)"""
    try:
        j = json.loads((d / MOD_STATS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return j if isinstance(j, dict) else None


def save_mod_stats(d: Path, data: dict) -> None:
    _write_json(d / MOD_STATS_FILE, data)


def read_recipes(d: Path) -> dict | None:
    """recipes.json(要求素材集用。データ更新で Export の ExportRecipes から作る)。無い・読めなければ None(形の検査は core.recipes で行う)"""
    try:
        j = json.loads((d / RECIPES_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return j if isinstance(j, dict) else None


def save_recipes(d: Path, data: dict) -> None:
    _write_json(d / RECIPES_FILE, data)


def _lang_names_path(d: Path, lang: str) -> Path:
    """names_<言語>.json の場所。言語が EXPORT_EXTRA_LANGS に無ければ TextError(ファイル名に任意の文字を入れない)"""
    if lang not in EXPORT_EXTRA_LANGS:
        raise TextError(txt("err.update.lang_unknown", lang=lang))
    return d / LANG_NAMES_FILE.format(lang=lang)


def save_lang_names(d: Path, lang: str, names: dict[str, str], source: str, updated: str) -> None:
    """日英のほかの言語の名前辞書を names_<言語>.json に書く。中身は {lang, source, updated, names: {英名: 名前}}"""
    body = {"lang": lang, "source": source, "updated": updated, "names": names}
    _write_json(_lang_names_path(d, lang), body)


def read_lang_names(d: Path, lang: str) -> dict | None:
    """names_<言語>.json の中身。無い・読めない・形が違う・取れない言語なら None"""
    if lang not in EXPORT_EXTRA_LANGS:
        return None
    f = _lang_names_path(d, lang)
    try:
        body = json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
    except (OSError, ValueError):
        return None
    return body if isinstance(body, dict) and isinstance(body.get("names"), dict) else None


def held_lang_names(d: Path) -> list[str]:
    """手元に名前辞書がある日英のほかの言語(EXPORT_EXTRA_LANGS の並び)。中身が壊れていても、ファイルがあれば取り直す対象に入れる"""
    return [lang for lang in EXPORT_EXTRA_LANGS if (d / LANG_NAMES_FILE.format(lang=lang)).is_file()]


def read_builder(d: Path) -> dict | None:
    """builder.json(シミュレータ用のフレーム・武器の性能)。無い・読めない・形が違えば None"""
    f = d / BUILDER_FILE
    if not f.exists():
        return None
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("frames") is not None else None


def save_builder(d: Path, data: dict) -> None:
    _write_json(d / BUILDER_FILE, data)


def read_item_paths(d: Path) -> dict:
    """item_paths.json(内部パス -> 英語名)。無い・読めなければ空"""
    f = d / ITEM_PATHS_FILE
    try:
        j = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except ValueError:
        return {}
    return j if isinstance(j, dict) else {}


def has_item_paths(d: Path) -> bool:
    return (d / ITEM_PATHS_FILE).exists()


def save_item_paths(d: Path, paths: dict) -> None:
    _write_json(d / ITEM_PATHS_FILE, paths)


def read_worldstate(d: Path) -> dict | None:
    """worldstate.json(World State から取り出した結果と取得した時刻)。無い・読めない・形が違えば None"""
    f = d / WORLDSTATE_FILE
    try:
        j = json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
    except ValueError:
        return None
    return j if isinstance(j, dict) and isinstance(j.get("fetched_at"), (int, float)) else None


def save_worldstate(d: Path, snap: dict) -> None:
    _write_json(d / WORLDSTATE_FILE, snap)
