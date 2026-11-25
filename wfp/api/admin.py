"""画面向け API: 管理(データの状態・データ更新・ツールの手動の更新)"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading

from wfp.api.store import ApiError, Store, file_stamp, mtime_jst
from wfp.core import const, offers, update
from wfp.core.common import app_version
from wfp.core.errors import error_text
from wfp.core.i18n import txt
from wfp.core.log import collect_log, say
from wfp.core.const import (APP_LAUNCHER_BAT, APP_LAUNCHER_ENV, APP_UPDATE_APPLY_TIMEOUT, APP_UPDATE_CHECK_TIMEOUT,
                            APP_UPDATE_SCRIPT, APP_UPDATE_STATES, DROPS_FILE, ITEM_PATHS_FILE, RIVENS_FILE, WFCD_DIR, WFCD_EXTRA)
from wfp.core.riven import update_rivens
from wfp.fetch import logos
from wfp.store import gamedata, userdata


def status(store: Store) -> dict:
    """データの状態(ヘッダーとデータ更新のページ)。names.json・ドロップ表が壊れていても落とさず、broken にファイル名を入れて
    「無い」ときと同じ値を返す(画面は壊れていることとデータ更新での直し方を案内する。更新のあとの状態もこれで返せる)"""
    broken: list[str] = []

    def read(get, empty):
        try:
            return get()
        except gamedata.DataBroken as e:
            broken.append(e.file)
            return empty
    drops, info = read(store.drops, None), read(store.names_info, {})
    src, rivens = store.sources(), store.rivens()
    f = store.d / DROPS_FILE
    wfcd = sorted((store.d / WFCD_DIR).glob("*.json")) if (store.d / WFCD_DIR).exists() else []
    return {
        "has_drops": drops is not None,
        "broken": broken,
        "has_names": bool(info),
        "drops_updated": mtime_jst(f) if drops else None,
        "names_updated": info.get("updated"),
        "names_source": info.get("source"),
        "counts": {"items": len(store.all_items()), "nodes": len(drops.node_order),
                   "sources": len(src.rows) if src else 0, "mods": info.get("mods", 0)} if drops else None,
        "extra_updated": max((mtime_jst(x) for x in wfcd), default=None),
        "extra_files": len(wfcd), "extra_total": len(WFCD_EXTRA),
        "rivens_updated": mtime_jst(store.d / RIVENS_FILE) if rivens else None,
        "rivens_count": len(rivens) if rivens else 0,
        "offers_updated": mtime_jst(gamedata.offers_path(store.d)) if gamedata.offers_path(store.d).exists() else None,
        "offers_count": src.offer_count if src else 0,
        "offers_plus": update.offers_plus(store.d),  # データ更新で Export Plus も取るか(画面のチェックの初期値)
        "has_logo": logos.find_logos_dir(store.d) is not None,
        "version": app_version(),
    }


def run_update_rivens(store: Store) -> dict:
    """Riven 相場だけ取り直す。lines は進み具合の行のテキスト指定(collect_log。画面が表示中の言語で出す)"""
    with collect_log() as lines:
        ok = update_rivens(store.d)
    return {"ok": ok, "lines": lines, "status": status(store)}


def update_langs(body) -> tuple[str, ...]:
    """データ更新の本文 {"lang": "ko"}(任意)から、日英のほかに名前辞書を取りたい言語を取り出す。

    言語の絞り込み(ja・en・Export に無い言語を外す)は update.lang_targets がする。文字列でなければ 400
    """
    lang = body.get("lang")
    if lang is None:
        return ()
    if not isinstance(lang, str):
        raise ApiError(txt("err.update.lang"))
    return (lang,)


def update_plus(body) -> bool | None:
    """データ更新の本文 {"plus": true}(任意)から、Export Plus(シンジケート・クエスト報酬・商人)も取るかを取り出す。
    無ければ None(前に覚えた値を使う。update.resolve_plus)。真偽値でなければ 400"""
    plus = body.get("plus")
    if plus is not None and not isinstance(plus, bool):
        raise ApiError(txt("err.update.plus"))
    return plus


def run_update(store: Store, langs: tuple[str, ...] = (), plus: bool | None = None) -> dict:
    """データ更新。langs は画面で選んでいる言語(update_langs)、plus は Export Plus も取るか(update_plus)。返り値は run_update_rivens と同じ形"""
    ok = True
    with collect_log() as lines:
        try:
            update.update_all(store.d, langs, plus)
        except update.UpdateFailed as e:
            ok = False
            say(error_text(e))
    return {"ok": ok, "lines": lines, "status": status(store)}


# --- ツールの手動の更新(wfportal_update.py を別のプロセスで呼ぶ。確認と更新は同時に1つだけ) ---
_app_update_lock = threading.Lock()


def restart_mode() -> str:
    """更新のあとの起動し直し方。"auto" = bat から起動していて自動で起動し直せる / "manual" = 手で起動し直してもらう"""
    return "auto" if os.environ.get(APP_LAUNCHER_ENV) == APP_LAUNCHER_BAT else "manual"


def run_updater(args: list[str], timeout: int) -> dict:
    """wfportal_update.py --json を呼んで、最後の行の結果(state current remote download delete)を返す。
    呼べない・時間切れ・結果の形が違う → 502"""
    cmd = [sys.executable, str(const.APP_DIR / APP_UPDATE_SCRIPT), "--json", "--dir", str(const.APP_DIR), *args]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout, cwd=const.APP_DIR, env=env)
    except (OSError, subprocess.TimeoutExpired):
        raise ApiError(txt("err.appupd.run"), 502)
    lines = proc.stdout.decode("utf-8", "replace").strip().splitlines()
    try:
        res = json.loads(lines[-1])
    except (IndexError, ValueError):
        raise ApiError(txt("err.appupd.run"), 502)
    if not isinstance(res, dict) or res.get("state") not in APP_UPDATE_STATES:
        raise ApiError(txt("err.appupd.run"), 502)
    return res


def app_update(check_only: bool) -> dict:
    """確認(check_only)か更新。ほかの確認・更新が動いていれば 409。restart は restart_mode"""
    if not _app_update_lock.acquire(blocking=False):
        raise ApiError(txt("err.appupd.busy"), 409)
    try:
        if check_only:
            res = run_updater(["--check"], APP_UPDATE_CHECK_TIMEOUT)
        else:
            res = run_updater([], APP_UPDATE_APPLY_TIMEOUT)
    finally:
        _app_update_lock.release()
    return {**res, "restart": restart_mode()}


def app_restart(c) -> dict:
    """更新のあとに画面のサーバーを起動し直す(bat から起動したときだけ。ほかは 409)。応答を返してから止まる"""
    if restart_mode() != "auto":
        raise ApiError(txt("err.appupd.no_restart"), 409)
    c.restart()
    return {"ok": True}


def _vendor_counts(store: Store) -> dict[str, int]:
    """商人ごとの品物の数(offers.json が無ければ空)。offers.json・item_paths.json が変わったときだけ数え直す"""
    f = gamedata.offers_path(store.d)
    return store.derived("@vendor_counts", file_stamp(f, store.d / ITEM_PATHS_FILE),
                         lambda: offers.vendor_counts(gamedata.read_offers(store.d), gamedata.read_item_paths(store.d)))


def offer_vendors(store: Store) -> dict:
    """GET /api/offers/vendors: 入手先に出す商人の候補と選択。name は名前のテキスト指定、named は名前を手で付けた商人か、
    n は品物の数、on は今オンか、default は初期値。並びは名前のある商人(VENDOR_NAMES の順)→ 名前の無い一覧。offers.json が無ければ空"""
    counts = _vendor_counts(store)
    on = offers.vendors_on(store.offer_choices(), counts)
    return {"vendors": [{"key": k, "name": offers.vendor_place(k), "named": offers.vendor_named(k), "n": n,
                         "on": k in on, "default": offers.vendor_default(k)} for k, n in counts.items()]}


def set_offer_vendor(store: Store, body: dict) -> dict:
    """POST /api/offers/vendors: 本文 {key, on} で商人を入手先に出すかを変える。key が候補に無い・on が真偽値でなければ 400"""
    key, on = body.get("key"), body.get("on")
    if not isinstance(key, str) or key not in _vendor_counts(store):
        raise ApiError(txt("err.offers.vendor"))
    if not isinstance(on, bool):
        raise ApiError(txt("err.offers.on"))
    try:
        with userdata.editing(store.d, "offer_vendors") as chosen:
            chosen[key] = on
    finally:
        store.forget_offer_choices()  # 保存できなかったときも読み直させる(覚えた値と食い違わないように)
    return {"ok": True}


def _run_update(store: Store, body: dict) -> dict:
    """POST /api/update: 本文を先に検査してからデータ更新する"""
    return run_update(store, update_langs(body), update_plus(body))


# (メソッド, パス) -> 処理。c はリクエスト(wfp/api/server.py の Request)
ROUTES = {
    ("GET", "/api/status"): lambda c: status(c.store),
    ("POST", "/api/update"): lambda c: _run_update(c.store, c.body()),
    ("POST", "/api/update-rivens"): lambda c: c.empty_body() or run_update_rivens(c.store),
    ("POST", "/api/app-update/check"): lambda c: c.empty_body() or app_update(check_only=True),
    ("POST", "/api/app-update/apply"): lambda c: c.empty_body() or app_update(check_only=False),
    ("POST", "/api/app-update/restart"): lambda c: c.empty_body() or app_restart(c),
    ("GET", "/api/offers/vendors"): lambda c: offer_vendors(c.store),
    ("POST", "/api/offers/vendors"): lambda c: set_offer_vendor(c.store, c.body()),
}
