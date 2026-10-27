"""画面向け API: シミュレータ(計算は wfportal_builder)"""
from __future__ import annotations

import contextlib
import io

import wfportal_builder as wb
from wfp.api.store import Store
from wfp.core.common import collect_log
from wfp.core.riven import dispo_table


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


# (メソッド, パス) -> 処理。c はリクエスト(wfp/api/server.py の Request)
ROUTES = {
    ("GET", "/api/builder/data"): lambda c: wb.api_data(c.store.d, sim_dispo_rows(c.store)),
    ("POST", "/api/builder/frame"): lambda c: wb.api_frame(c.store.d, c.body()),
    ("POST", "/api/builder/weapon"): lambda c: wb.api_weapon(c.store.d, c.body(), sim_dispo_rows(c.store)),
    ("POST", "/api/builder/riven"): lambda c: wb.api_riven(c.store.d, c.body(), sim_dispo_rows(c.store)),
    ("POST", "/api/builder/update"): lambda c: c.empty_body() or run_update_sim(c.store),
}
