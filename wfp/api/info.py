"""画面向け API: 情報(サイクル・侵略サイクル・バロ吉・Riven 相場・Riven 性質・デュヴィリ)"""
from __future__ import annotations

from datetime import datetime

import wfportal_baro as wbaro
import wfportal_worldstate as ws
from wfp.api.store import ApiError, JST, Store, mtime_jst
from wfp.core.common import CYCLES, DISPO_CATS, PHASE_ALIASES, parse_remaining
from wfp.core.cycle import cycle_rows, next_daily_reset, next_weekly_reset, set_manual_cycle
from wfp.core.duviri import clear_duviri_adjust, duviri_view, set_duviri_adjust
from wfp.core.invasion import invasion_view, set_invasion_part
from wfp.core.riven import dispo_table, riven_table
from wfp.core.spexchange import spex_view


def cycles(store: Store) -> dict:
    view = cycle_rows(store.d)
    nowdt = datetime.fromtimestamp(view["now"], JST)  # PC の時計のずれは補正済み
    dr, wr = next_daily_reset(nowdt), next_weekly_reset(nowdt)
    return {**view,
            "sp_exchange": spex_view(view["now"]),
            "daily": {"left": (dr - nowdt).total_seconds(), "at": dr.astimezone(JST).strftime("%m/%d %H:%M")},
            "weekly": {"left": (wr - nowdt).total_seconds(), "at": wr.astimezone(JST).strftime("%m/%d %H:%M")}}


def set_cycle(store: Store, body: dict) -> dict:
    key = str(body.get("key", ""))
    if key not in CYCLES or not CYCLES[key]["manual"]:
        raise ApiError("手動で合わせられるのは平原とオーブ峡谷です。")
    phase = PHASE_ALIASES.get(str(body.get("phase", "")).lower())
    if phase not in [p[0] for p in CYCLES[key]["phases"]]:
        raise ApiError("フェーズを選んでください。")
    try:
        remaining = parse_remaining(str(body.get("remaining", "")))
    except ValueError:
        raise ApiError("残り時間は「45:30」または分の数字で入力してください。")
    try:
        set_manual_cycle(store.d, key, phase, remaining)
    except ValueError as e:
        raise ApiError(str(e))
    return cycles(store)


def sync_worldstate(store: Store) -> dict:
    """公式データ(World State)で時刻合わせ。前回から 60 秒以内なら前回の結果を使う"""
    try:
        snap = ws.sync(store.d)
    except ws.WorldStateError as e:
        raise ApiError(f"公式データを取得できませんでした。基準時刻(または前回の同期)からの計算で表示しています。({e})", 502)
    return {**cycles(store), "synced": {"cached": snap["cached"], "offset": snap["offset"], "fetched_at": snap["fetched_at"]}}


def baro_list(store: Store) -> dict:
    return wbaro.baro_view(store.d, store.names())


def run_update_baro(store: Store) -> dict:
    """今回の品物を公式データから取得し、来ていれば来訪を記録する"""
    r = wbaro.update_all(store.d)
    if r["errors"]:
        raise ApiError(" / ".join(r["errors"]), 502)
    return {**baro_list(store), "update": r}


def set_baro_owned(store: Store, body: dict) -> dict:
    try:
        wbaro.set_manual_owned(store.d, str(body.get("name", "")), bool(body.get("owned")), store.names())
    except ValueError as e:
        raise ApiError(str(e))
    return {"ok": True}


def rivens_list(store: Store) -> dict:
    raw = store.rivens()
    if raw is None:
        raise ApiError("Riven 相場のデータがありません。「データ更新」で取得してください。", 409)
    return {"rows": riven_table(raw, store.names()), "updated": mtime_jst(store.d / "rivens.json")}


def dispo_list(store: Store) -> dict:
    names = store.names()
    if not names.dispo:
        raise ApiError("Riven 性質のデータがありません。「データ更新」で取得し直してください"
                       "(このページを追加する前に取得したデータには含まれていません)。", 409)
    return {"rows": dispo_table(names, store.rivens()), "cats": DISPO_CATS,
            "updated": (store.names_info().get("updated") or "")[:10]}


# (メソッド, パス) -> 処理。c はリクエスト(wfp/api/server.py の Request)
def duviri(store: Store) -> dict:
    """デュヴィリサーキットのローテーション(読めないモードは ok: False。エラーにしない)"""
    return duviri_view(store.d)


def set_duviri(store: Store, body: dict) -> dict:
    """今週の ID を手で合わせる(本文 {"mode": "normal", "id": 2})"""
    if not isinstance(body, dict):
        raise ApiError("JSON のオブジェクトで送ってください。")
    try:
        set_duviri_adjust(store.d, str(body.get("mode", "")), body.get("id"))
    except ValueError as e:
        raise ApiError(str(e))
    return duviri(store)


def reset_duviri(store: Store, body: dict) -> dict:
    """手動調整を消して同梱の設定に戻す(本文 {"mode": "normal"})"""
    if not isinstance(body, dict):
        raise ApiError("JSON のオブジェクトで送ってください。")
    try:
        clear_duviri_adjust(store.d, str(body.get("mode", "")))
    except ValueError as e:
        raise ApiError(str(e))
    return duviri(store)


def invasions(store: Store) -> dict:
    """侵略サイクル: 保存済みの World State から侵略の一覧と収集表を作る(通信しない)"""
    return invasion_view(store.d, ws.load_snapshot(store.d), wbaro.load_item_paths(store.d), store.names())


def sync_invasions(store: Store) -> dict:
    """公式データ(World State)を取り直して侵略の一覧を更新する。前回から 60 秒以内なら前回の結果を使う"""
    try:
        snap = ws.sync(store.d)
    except ws.WorldStateError as e:
        raise ApiError(f"公式データを取得できませんでした。前回取得した内容で表示しています。({e})", 502)
    return {**invasions(store), "synced": {"cached": snap["cached"], "fetched_at": snap["fetched_at"]}}


def set_invasion_parts(store: Store, body: dict) -> dict:
    """パーツの取得済みを付け外しする(本文 {"path": "/Lotus/…", "owned": true})"""
    if not isinstance(body, dict):
        raise ApiError("JSON のオブジェクトで送ってください。")
    try:
        set_invasion_part(store.d, str(body.get("path", "")), bool(body.get("owned")))
    except ValueError as e:
        raise ApiError(str(e))
    return invasions(store)


ROUTES = {
    ("GET", "/api/cycles"): lambda c: cycles(c.store),
    ("POST", "/api/cycles"): lambda c: set_cycle(c.store, c.body()),
    ("POST", "/api/cycles/sync"): lambda c: c.empty_body() or sync_worldstate(c.store),
    ("GET", "/api/baro"): lambda c: baro_list(c.store),
    ("POST", "/api/baro/update"): lambda c: c.empty_body() or run_update_baro(c.store),
    ("POST", "/api/baro/owned"): lambda c: set_baro_owned(c.store, c.body()),
    ("GET", "/api/rivens"): lambda c: rivens_list(c.store),
    ("GET", "/api/dispo"): lambda c: dispo_list(c.store),
    ("GET", "/api/invasions"): lambda c: invasions(c.store),
    ("POST", "/api/invasions/update"): lambda c: c.empty_body() or sync_invasions(c.store),
    ("POST", "/api/invasions/parts"): lambda c: set_invasion_parts(c.store, c.body()),
    ("GET", "/api/duviri"): lambda c: duviri(c.store),
    ("POST", "/api/duviri/adjust"): lambda c: set_duviri(c.store, c.body()),
    ("POST", "/api/duviri/reset"): lambda c: reset_duviri(c.store, c.body()),
}
