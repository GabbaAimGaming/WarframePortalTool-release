"""画面向け API: シミュレータ(計算は wfportal_builder)"""
from __future__ import annotations

import wfportal_builder as wb
import wfportal_ocr as ocr
import wfportal_rivenscan as rscan
from wfp.api.ocr import need_ocr, run_ocr
from wfp.api.store import ApiError, Store, file_stamp
from wfp.core.i18n import txt
from wfp.core.log import collect_log
from wfp.core.const import RIVEN_WORDS_FILE
from wfp.core import simdata
from wfp.core.riven import dispo_table
from wfp.store import appdata, build_images


def sim_dispo_rows(store: Store) -> list[dict]:
    """シミュレータで武器の Riven の種類(ライフル / ショットガン等)を決めるのに使う(`dispo_table` の判定。相場の武器種を優先)"""
    names = store.names()
    return dispo_table(names, store.rivens()) if names.dispo else []


def run_update_sim(store: Store) -> dict:
    """シミュレータ用データだけ取り直す。lines は進み具合の行のテキスト指定(collect_log。画面が表示中の言語で出す)"""
    with collect_log() as lines:
        ok = simdata.update_builder_data(store.d)
    return {"ok": ok, "lines": lines}


def riven_words(store: Store) -> rscan.WordTable:
    """効果名の辞書(同梱の data/riven/stat_words.json。直せば読み直す)。読めなければ 500(覚えない)"""
    def build() -> rscan.WordTable:
        table = rscan.WordTable(appdata.read_riven_words(), wb.RIVEN_STAT_INDEX)
        if not table.words:
            raise ApiError(txt("err.sim.scan.words"), 500)
        return table
    return store.derived("@rivenwords", file_stamp(appdata.riven_dir() / RIVEN_WORDS_FILE), build)


def scan_riven(store: Store, data: bytes) -> dict:
    """Riven の画像から武器・ランク(推定)・効果の値を読む。グレードは画面が直したあとに /api/builder/riven/grade で出す"""
    need_ocr()
    if not data or build_images.image_ext(data) not in ("png", "jpg"):
        raise ApiError(txt("err.sim.scan.image"), 415)
    table = riven_words(store)
    raw = run_ocr(data, cache_dir=None, langs=ocr.DEFAULT_LANGS)
    builder = store.builder()
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
