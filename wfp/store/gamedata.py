"""公式由来のデータ(ドロップ表・入手先・名前辞書・日英のほかの言語の名前辞書・Riven 相場・ノード名)のファイル読み書き。

書くときは datadir.write_atomic(一時ファイル + os.replace)で、途中で落ちても前のファイルを残す
"""
from __future__ import annotations

import json
from pathlib import Path

from wfp.core.errors import TextError, TextFailure
from wfp.core.i18n import txt
from wfp.core.const import (
    ARBYS_FILE, BUILDER_FILE, DROPS_FILE, EXPORT_EXTRA_LANGS, ITEM_PATHS_FILE, LANG_NAMES_FILE, MOD_STATS_FILE, NAMES_FILE, OFFERS_FILE,
    RECIPES_FILE, REGIONS_FILE, RIVENS_FILE, WFCD_DIR, WFCD_EXTRA, WORLDSTATE_FILE,
)
from wfp.store import datadir


class DataBroken(TextFailure):
    """土台のデータ(names.json・missionRewards.json)があるのに読めない・形が違う。データ更新で取り直せば直る。
    「無い」とは分ける(無いときは None を返し、使う側がデータ更新を案内する)。file は壊れているファイルの名前"""

    def __init__(self, file: str):
        self.file = file
        super().__init__(txt("err.data.broken", file=file))


def _read_dict(f: Path) -> dict | None:
    """JSON のファイルの中身(オブジェクト)。無い・読めない・壊れている・オブジェクトでなければ None"""
    data = datadir.read_json(f)
    return data if isinstance(data, dict) else None


def _read_base(d: Path, name: str, need: str | None = None) -> dict | None:
    """土台のデータ: 無ければ None、あるのに読めない・オブジェクトでない・need のキー(指定したとき)が無ければ DataBroken"""
    f = d / name
    if not f.exists():
        return None
    data = _read_dict(f)
    if data is None or (need is not None and need not in data):
        raise DataBroken(name)
    return data


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
    """names.json の中身。無ければ None、壊れていれば DataBroken"""
    return _read_base(d, NAMES_FILE)


def read_drops(d: Path) -> dict | None:
    """missionRewards.json の中身。無ければ None、壊れていれば DataBroken"""
    return _read_base(d, DROPS_FILE, "missionRewards")


def read_wfcd(d: Path) -> dict[str, dict]:
    """wfcd/ 以下の各 JSON({ファイル名: 中身})。無い・読めないファイルは飛ばす"""
    files = {}
    for name in WFCD_EXTRA:
        data = datadir.read_json(d / WFCD_DIR / f"{name}.json")
        if data is not None:
            files[name] = data
    return files


def read_rivens(d: Path):
    """rivens.json の中身(形はそろえていない)。無い・読めなければ None"""
    return datadir.read_json(d / RIVENS_FILE)


def save_rivens(d: Path, rows: list[dict]) -> None:
    _write_json(d / RIVENS_FILE, rows)


def read_regions(d: Path) -> dict:
    """regions.json(ノードの内部名 -> 名前)。無い・読めなければ空"""
    return _read_dict(d / REGIONS_FILE) or {}


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
    """mod_stats.json(MOD 効果検索用。データ更新で Export から作る)。無い・読めなければ None(形の検査は core.modstats)"""
    return _read_dict(d / MOD_STATS_FILE)


def save_mod_stats(d: Path, data: dict) -> None:
    _write_json(d / MOD_STATS_FILE, data)


def read_recipes(d: Path) -> dict | None:
    """recipes.json(要求素材集用。データ更新で Export の ExportRecipes から作る)。無い・読めなければ None"""
    return _read_dict(d / RECIPES_FILE)


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
    body = _read_dict(_lang_names_path(d, lang))
    return body if body is not None and isinstance(body.get("names"), dict) else None


def held_lang_names(d: Path) -> list[str]:
    """手元に名前辞書がある日英のほかの言語(EXPORT_EXTRA_LANGS の並び)。中身が壊れていても、ファイルがあれば取り直す対象に入れる"""
    return [lang for lang in EXPORT_EXTRA_LANGS if (d / LANG_NAMES_FILE.format(lang=lang)).is_file()]


def read_builder(d: Path) -> dict | None:
    """builder.json(シミュレータ用のフレーム・武器の性能)。無い・読めない・形が違えば None"""
    data = _read_dict(d / BUILDER_FILE)
    return data if data is not None and data.get("frames") is not None else None


def save_builder(d: Path, data: dict) -> None:
    _write_json(d / BUILDER_FILE, data)


def read_item_paths(d: Path) -> dict:
    """item_paths.json(内部パス -> 英語名)。無い・読めなければ空"""
    return _read_dict(d / ITEM_PATHS_FILE) or {}


def has_item_paths(d: Path) -> bool:
    return (d / ITEM_PATHS_FILE).exists()


def save_item_paths(d: Path, paths: dict) -> None:
    _write_json(d / ITEM_PATHS_FILE, paths)


def read_worldstate(d: Path) -> dict | None:
    """worldstate.json(World State から取り出した結果と取得した時刻)。無い・読めない・形が違えば None"""
    snap = _read_dict(d / WORLDSTATE_FILE)
    return snap if snap is not None and isinstance(snap.get("fetched_at"), (int, float)) else None


def save_worldstate(d: Path, snap: dict) -> None:
    _write_json(d / WORLDSTATE_FILE, snap)


def read_offers(d: Path) -> dict | None:
    """offers.json(シンジケート・クエスト報酬・商人。オプション。Export Plus から取り出した内部パスの一覧)。無い・読めなければ None(形の検査は core.offers)"""
    return _read_dict(d / OFFERS_FILE)


def save_offers(d: Path, data: dict) -> None:
    _write_json(d / OFFERS_FILE, data)


def remove_offers(d: Path) -> bool:
    """offers.json を消す(データ更新で Export Plus を取らないとき)。消したら True、もともと無ければ False"""
    try:
        (d / OFFERS_FILE).unlink()
        return True
    except FileNotFoundError:
        return False


def offers_path(d: Path) -> Path:
    """offers.json の場所(API の読み直しの目印に更新日時を見る)"""
    return d / OFFERS_FILE
