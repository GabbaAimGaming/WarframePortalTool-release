"""画面向け API: 管理(データの状態・データ更新)"""
from __future__ import annotations

import contextlib
import io

from wfp.api.store import ApiError, Store, mtime_jst
from wfp.core import update
from wfp.core.common import WFCD_EXTRA, app_version, collect_log, error_text, say, txt
from wfp.core.riven import update_rivens
from wfp.fetch import logos


def status(store: Store) -> dict:
    drops, info, src, rivens = store.drops(), store.names_info(), store.sources(), store.rivens()
    f = store.d / "missionRewards.json"
    wfcd = sorted((store.d / "wfcd").glob("*.json")) if (store.d / "wfcd").exists() else []
    return {
        "has_drops": drops is not None,
        "has_names": bool(info),
        "drops_updated": mtime_jst(f) if drops else None,
        "names_updated": info.get("updated"),
        "names_source": info.get("source"),
        "counts": {"items": len(store.all_items()), "nodes": len(drops.node_order),
                   "sources": len(src.rows) if src else 0, "mods": info.get("mods", 0)} if drops else None,
        "extra_updated": max((mtime_jst(x) for x in wfcd), default=None),
        "extra_files": len(wfcd), "extra_total": len(WFCD_EXTRA),
        "rivens_updated": mtime_jst(store.d / "rivens.json") if rivens else None,
        "rivens_count": len(rivens) if rivens else 0,
        "has_logo": logos.find_logos_dir(store.d) is not None,
        "version": app_version(),
    }


def run_update_rivens(store: Store) -> dict:
    """Riven 相場だけ取り直す。log は日本語のログ(標準出力)、lines は同じ行のテキスト指定(画面が表示中の言語で出す)"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), collect_log() as lines:
        ok = update_rivens(store.d)
    return {"ok": ok, "log": buf.getvalue(), "lines": lines, "status": status(store)}


def update_langs(body) -> tuple[str, ...]:
    """データ更新の本文 {"lang": "ko"}(任意)から、日英のほかに名前辞書を取りたい言語を取り出す。

    言語の絞り込み(ja・en・Export に無い言語を外す)は update.lang_targets がする。文字列でなければ 400
    """
    if not isinstance(body, dict):
        raise ApiError(txt("err.req.object"))
    lang = body.get("lang")
    if lang is None:
        return ()
    if not isinstance(lang, str):
        raise ApiError(txt("err.update.lang"))
    return (lang,)


def run_update(store: Store, langs: tuple[str, ...] = ()) -> dict:
    """データ更新。langs は画面で選んでいる言語(update_langs)。返り値は run_update_rivens と同じ形"""
    buf = io.StringIO()
    ok = True
    with contextlib.redirect_stdout(buf), collect_log() as lines:
        try:
            update.update_all(store.d, langs)
        except update.UpdateFailed as e:
            ok = False
            say(error_text(e))
    return {"ok": ok, "log": buf.getvalue(), "lines": lines, "status": status(store)}


# (メソッド, パス) -> 処理。c はリクエスト(wfp/api/server.py の Request)
ROUTES = {
    ("GET", "/api/status"): lambda c: status(c.store),
    ("POST", "/api/update"): lambda c: run_update(c.store, update_langs(c.body())),
    ("POST", "/api/update-rivens"): lambda c: c.empty_body() or run_update_rivens(c.store),
}
