"""画面向け API: 管理(データの状態・データ更新・ツールの手動の更新)"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading

from wfp.api.store import ApiError, Store, mtime_jst
from wfp.core import const, update
from wfp.core.common import app_version
from wfp.core.errors import error_text
from wfp.core.i18n import txt
from wfp.core.log import collect_log, say
from wfp.core.const import (APP_LAUNCHER_BAT, APP_LAUNCHER_ENV, APP_UPDATE_APPLY_TIMEOUT, APP_UPDATE_CHECK_TIMEOUT,
                            APP_UPDATE_SCRIPT, APP_UPDATE_STATES, DROPS_FILE, RIVENS_FILE, WFCD_DIR, WFCD_EXTRA)
from wfp.core.riven import update_rivens
from wfp.fetch import logos
from wfp.store import gamedata


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


def run_update(store: Store, langs: tuple[str, ...] = ()) -> dict:
    """データ更新。langs は画面で選んでいる言語(update_langs)。返り値は run_update_rivens と同じ形"""
    ok = True
    with collect_log() as lines:
        try:
            update.update_all(store.d, langs)
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


# (メソッド, パス) -> 処理。c はリクエスト(wfp/api/server.py の Request)
ROUTES = {
    ("GET", "/api/status"): lambda c: status(c.store),
    ("POST", "/api/update"): lambda c: run_update(c.store, update_langs(c.body())),
    ("POST", "/api/update-rivens"): lambda c: c.empty_body() or run_update_rivens(c.store),
    ("POST", "/api/app-update/check"): lambda c: c.empty_body() or app_update(check_only=True),
    ("POST", "/api/app-update/apply"): lambda c: c.empty_body() or app_update(check_only=False),
    ("POST", "/api/app-update/restart"): lambda c: c.empty_body() or app_restart(c),
}
