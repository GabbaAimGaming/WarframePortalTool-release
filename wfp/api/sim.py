"""画面向け API: シミュレータ(計算は wfportal_builder)"""
from __future__ import annotations

import contextlib
import io

import wfportal_builder as wb
import wfportal_ocr as ocr
import wfportal_rivenscan as rscan
from wfp.api.personal import ocr_info
from wfp.api.store import ApiError, Store
from wfp.core.common import collect_log, error_text, txt
from wfp.core.riven import dispo_table
from wfp.store import appdata, build_images


def sim_dispo_rows(store: Store) -> list[dict]:
    """シミュレータで武器の Riven の種類(ライフル / ショットガン等)を決めるのに使う(`dispo_table` の判定。相場の武器種を優先)"""
    names = store.names()
    return dispo_table(names, store.rivens()) if names.dispo else []


def run_update_sim(store: Store) -> dict:
    """シミュレータ用データだけ取り直す。log は日本語のログ、lines は同じ行のテキスト指定(画面が表示中の言語で出す)"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), collect_log() as lines:
        ok = wb.update_builder_data(store.d)
    return {"ok": ok, "log": buf.getvalue(), "lines": lines}


def riven_words(store: Store) -> rscan.WordTable:
    """効果名の辞書(同梱の data/riven/stat_words.json)。読めなければ 500"""
    with store._lock:
        table = store._cache.get("@rivenwords")
    if table is None:
        table = rscan.WordTable(appdata.read_riven_words())
        if not table.words:
            raise ApiError(txt("err.sim.scan.words"), 500)
        with store._lock:
            store._cache["@rivenwords"] = table
    return table


def scan_riven(store: Store, data: bytes) -> dict:
    """Riven の画像から武器・ランク(推定)・効果の値を読む。グレードは画面が直したあとに /api/builder/riven/grade で出す"""
    info = ocr_info()
    if not info["available"]:
        raise ApiError(info["reason"] or txt("err.ocr.none"), 501)
    if not data or build_images.image_ext(data) not in ("png", "jpg"):
        raise ApiError(txt("err.sim.scan.image"), 415)
    table = riven_words(store)
    try:
        raw = ocr.run_ocr_bytes(data, cache_dir=None, langs=ocr.DEFAULT_LANGS)
    except ocr.OcrUnavailable as err:
        raise ApiError(error_text(err), 502)
    builder = wb.load_builder_data(store.d)
    res = rscan.parse_riven(raw, table, builder["weapons"] if builder else [])
    group = None
    if res["weapon"] and builder:
        w = next((x for x in builder["weapons"] if x["en"] == res["weapon"]["en"] and x.get("cat") == res["weapon"]["cat"]), None)
        group = wb.riven_group(wb.weapon_riven_type(w, sim_dispo_rows(store))) if w else None
    return {**res, "group": group}


# (メソッド, パス) -> 処理。c はリクエスト(wfp/api/server.py の Request)
ROUTES = {
    ("GET", "/api/builder/data"): lambda c: wb.api_data(c.store.d, sim_dispo_rows(c.store)),
    ("POST", "/api/builder/frame"): lambda c: wb.api_frame(c.store.d, c.body()),
    ("POST", "/api/builder/weapon"): lambda c: wb.api_weapon(c.store.d, c.body(), sim_dispo_rows(c.store)),
    ("POST", "/api/builder/riven"): lambda c: wb.api_riven(c.store.d, c.body(), sim_dispo_rows(c.store)),
    ("POST", "/api/builder/riven/grade"): lambda c: wb.api_riven_grade(c.store.d, c.body(), sim_dispo_rows(c.store)),
    ("POST", "/api/builder/riven/scan"): lambda c: scan_riven(c.store, c.image()),
    ("POST", "/api/builder/update"): lambda c: c.empty_body() or run_update_sim(c.store),
}
