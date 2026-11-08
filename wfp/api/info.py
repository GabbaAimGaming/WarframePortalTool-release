"""画面向け API: 情報(サイクル・侵略サイクル・仲裁・バロ吉・Riven 相場・デュヴィリ・MOD 効果検索)"""
from __future__ import annotations

from datetime import datetime

import wfportal_baro as wbaro
import wfportal_worldstate as ws
from wfp.api.store import ApiError, JST, Store, mtime_jst
from wfp.core.arbitration import arbitration_view, update_arbys
from wfp.core.common import ARBYS_FILE, CYCLES, MOD_STATS_FILE, PHASE_ALIASES, error_text, parse_remaining, txt
from wfp.core.cycle import cycle_rows, next_daily_reset, next_weekly_reset, set_manual_cycle
from wfp.core.duviri import clear_duviri_adjust, duviri_view, set_duviri_adjust
from wfp.core.invasion import invasion_view, set_invasion_part
from wfp.core.modstats import parse_groups
from wfp.core.riven import riven_table
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
        raise ApiError(txt("err.cycle.manual"))
    phase = PHASE_ALIASES.get(str(body.get("phase", "")).lower())
    if phase not in [p[0] for p in CYCLES[key]["phases"]]:
        raise ApiError(txt("err.cycle.phase"))
    try:
        remaining = parse_remaining(str(body.get("remaining", "")))
    except ValueError:
        raise ApiError(txt("err.cycle.remaining"))
    try:
        set_manual_cycle(store.d, key, phase, remaining)
    except ValueError as e:
        raise ApiError(error_text(e))
    return cycles(store)


def sync_worldstate(store: Store) -> dict:
    """公式データ(World State)で時刻合わせ。前回から 60 秒以内なら前回の結果を使う"""
    try:
        snap = ws.sync(store.d)
    except ws.WorldStateError as e:
        raise ApiError(txt("err.cycle.fetch", e=str(e)), 502)
    return {**cycles(store), "synced": {"cached": snap["cached"], "offset": snap["offset"], "fetched_at": snap["fetched_at"]}}


def baro_list(store: Store) -> dict:
    return wbaro.baro_view(store.d, store.names())


def run_update_baro(store: Store) -> dict:
    """今回の品物を公式データから取得し、来ていれば来訪を記録する"""
    r = wbaro.update_all(store.d)
    if r["errors"]:
        raise ApiError(r["errors"][0] if len(r["errors"]) == 1 else r["errors"], 502)
    return {**baro_list(store), "update": r}


def set_baro_owned(store: Store, body: dict) -> dict:
    try:
        wbaro.set_manual_owned(store.d, str(body.get("name", "")), bool(body.get("owned")), store.names())
    except ValueError as e:
        raise ApiError(error_text(e))
    return {"ok": True}


def rivens_list(store: Store) -> dict:
    raw = store.rivens()
    if raw is None:
        raise ApiError(txt("err.riven.nodata"), 409)
    return {"rows": riven_table(raw, store.names()), "updated": mtime_jst(store.d / "rivens.json")}


# (メソッド, パス) -> 処理。c はリクエスト(wfp/api/server.py の Request)
def duviri(store: Store) -> dict:
    """デュヴィリサーキットのローテーション(読めないモードは ok: False。エラーにしない)"""
    return duviri_view(store.d)


def set_duviri(store: Store, body: dict) -> dict:
    """今週の ID を手で合わせる(本文 {"mode": "normal", "id": 2})"""
    if not isinstance(body, dict):
        raise ApiError(txt("err.req.object"))
    try:
        set_duviri_adjust(store.d, str(body.get("mode", "")), body.get("id"))
    except ValueError as e:
        raise ApiError(error_text(e))
    return duviri(store)


def reset_duviri(store: Store, body: dict) -> dict:
    """手動調整を消して同梱の設定に戻す(本文 {"mode": "normal"})"""
    if not isinstance(body, dict):
        raise ApiError(txt("err.req.object"))
    try:
        clear_duviri_adjust(store.d, str(body.get("mode", "")))
    except ValueError as e:
        raise ApiError(error_text(e))
    return duviri(store)


def invasions(store: Store) -> dict:
    """侵略サイクル: 保存済みの World State から侵略の一覧と収集表を作る(通信しない)"""
    return invasion_view(store.d, ws.load_snapshot(store.d), wbaro.load_item_paths(store.d), store.names())


def sync_invasions(store: Store) -> dict:
    """公式データ(World State)を取り直して侵略の一覧を更新する。前回から 60 秒以内なら前回の結果を使う"""
    try:
        snap = ws.sync(store.d)
    except ws.WorldStateError as e:
        raise ApiError(txt("err.invasion.fetch", e=str(e)), 502)
    return {**invasions(store), "synced": {"cached": snap["cached"], "fetched_at": snap["fetched_at"]}}


def set_invasion_parts(store: Store, body: dict) -> dict:
    """パーツの取得済みを付け外しする(本文 {"path": "/Lotus/…", "owned": true})"""
    if not isinstance(body, dict):
        raise ApiError(txt("err.req.object"))
    try:
        set_invasion_part(store.d, str(body.get("path", "")), bool(body.get("owned")))
    except ValueError as e:
        raise ApiError(error_text(e))
    return invasions(store)


def arbitration(store: Store) -> dict:
    """仲裁: 保存済みのスケジュールから今の枠と次の枠を作る(通信しない)。fetched_at はスケジュールを保存した時刻(UNIX 秒)"""
    f = store.d / ARBYS_FILE
    return {**arbitration_view(store.d, store.arbys()), "fetched_at": f.stat().st_mtime if f.exists() else None}


def sync_arbitration(store: Store) -> dict:
    """仲裁のスケジュールを取り直す。取れなければ 502(保存済みの分はそのまま)"""
    try:
        update_arbys(store.d)
    except Exception as e:  # noqa: BLE001
        raise ApiError(txt("err.arbys.fetch", e=error_text(e)), 502)
    return arbitration(store)


def mod_suggest(store: Store, query: str) -> dict:
    """MOD 効果検索: 影響先の候補(表示名に部分一致)。データが無ければ空で has_data が false(画面は案内を出す)"""
    data = store.mod_stats()
    return {"items": data.suggest(query) if data else [], "has_data": data is not None}


def mod_effects(store: Store, target: str, query: str, groups: str) -> dict:
    """MOD 効果検索: 影響先キー(target)か全文(q)で探す。groups は区分キーのカンマ区切り(空は全部)"""
    data = store.mod_stats()
    if data is None:
        raise ApiError(txt("err.nodata"), 409)
    try:
        return {**data.find(target, query, parse_groups(groups)), "updated": mtime_jst(store.d / MOD_STATS_FILE)}
    except ValueError as e:
        raise ApiError(error_text(e))


ROUTES = {
    ("GET", "/api/cycles"): lambda c: cycles(c.store),
    ("POST", "/api/cycles"): lambda c: set_cycle(c.store, c.body()),
    ("POST", "/api/cycles/sync"): lambda c: c.empty_body() or sync_worldstate(c.store),
    ("GET", "/api/baro"): lambda c: baro_list(c.store),
    ("POST", "/api/baro/update"): lambda c: c.empty_body() or run_update_baro(c.store),
    ("POST", "/api/baro/owned"): lambda c: set_baro_owned(c.store, c.body()),
    ("GET", "/api/rivens"): lambda c: rivens_list(c.store),
    ("GET", "/api/invasions"): lambda c: invasions(c.store),
    ("POST", "/api/invasions/update"): lambda c: c.empty_body() or sync_invasions(c.store),
    ("POST", "/api/invasions/parts"): lambda c: set_invasion_parts(c.store, c.body()),
    ("GET", "/api/arbitration"): lambda c: arbitration(c.store),
    ("POST", "/api/arbitration/update"): lambda c: c.empty_body() or sync_arbitration(c.store),
    ("GET", "/api/duviri"): lambda c: duviri(c.store),
    ("POST", "/api/duviri/adjust"): lambda c: set_duviri(c.store, c.body()),
    ("POST", "/api/duviri/reset"): lambda c: reset_duviri(c.store, c.body()),
    ("GET", "/api/modstats/suggest"): lambda c: mod_suggest(c.store, c.q.get("q", "")),
    ("GET", "/api/modstats"): lambda c: mod_effects(c.store, c.q.get("target", ""), c.q.get("q", ""), c.q.get("groups", "")),
}
