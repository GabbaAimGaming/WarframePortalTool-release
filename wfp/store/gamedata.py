"""公式由来のデータ(ドロップ表・入手先・名前辞書・日英のほかの言語の名前辞書・Riven 相場・ノード名)のファイル読み書き"""
from __future__ import annotations

import json
from pathlib import Path

from wfp.core.common import EXPORT_EXTRA_LANGS, LANG_NAMES_FILE, REGIONS_FILE, WFCD_EXTRA, TextError, txt


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


def _lang_names_path(d: Path, lang: str) -> Path:
    """names_<言語>.json の場所。言語が EXPORT_EXTRA_LANGS に無ければ TextError(ファイル名に任意の文字を入れない)"""
    if lang not in EXPORT_EXTRA_LANGS:
        raise TextError(txt("err.update.lang_unknown", lang=lang))
    return d / LANG_NAMES_FILE.format(lang=lang)


def save_lang_names(d: Path, lang: str, names: dict[str, str], source: str, updated: str) -> None:
    """日英のほかの言語の名前辞書を names_<言語>.json に書く。中身は {lang, source, updated, names: {英名: 名前}}"""
    body = {"lang": lang, "source": source, "updated": updated, "names": names}
    _lang_names_path(d, lang).write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")


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
