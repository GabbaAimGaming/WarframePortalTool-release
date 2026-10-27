"""デュヴィリサーキットのローテーション(今週の報酬と今後の並び)

今の週はファイルに書き込まず、毎回「基準の週 + 経過週数」で計算する。
起動しなかった週・自動更新の巻き戻し・複数の PC でもズレない。週の切り替わりはウィークリーリセット(月曜 0:00 UTC)。

基準は、利用者の手動調整(~/.wfportal/duviri_adjust.json)があればそれ、無ければ同梱の data/duviri/rotate.json。
手動調整は「選んだ ID と、その週の月曜」をそのまま保存するので、同梱側が直っても二重にずれない。
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from wfp.core.common import DUVIRI_BASE_FILE, DUVIRI_MODES, TextError, txt
from wfp.core.cycle import clock_offset, next_weekly_reset
from wfp.store import appdata, userdata


def week_start(now: datetime) -> date:
    """now を含む週の月曜(UTC)の日付"""
    return (next_weekly_reset(now) - timedelta(days=7)).date()


def weeks_since(base: date, now: datetime) -> int:
    """基準の週(月曜の日付)から now までに跨いだ月曜 0:00 UTC の回数。基準より前なら負"""
    return (week_start(now) - base).days // 7


def rotation_id(base_id: int, weeks: int, count: int) -> int:
    """基準の ID から weeks 週進んだ ID(1〜count で折り返す。weeks が負でも正しく折り返す)"""
    return (base_id - 1 + weeks) % count + 1


def check_rotation(j: object) -> list[dict] | None:
    """ローテーションのファイルの中身を検査し、ID 順の [{id, items}] を返す。形が違えば None

    ID は 1〜件数の連番(並びは問わない)、items は空でない文字列の配列。
    """
    rows = j.get("rotation") if isinstance(j, dict) else None
    if not isinstance(rows, list) or not rows:
        return None
    out = []
    for r in rows:
        if not isinstance(r, dict):
            return None
        rid, items = r.get("id"), r.get("items")
        if isinstance(rid, bool) or not isinstance(rid, int):
            return None
        if not isinstance(items, list) or not all(isinstance(i, str) and i.strip() for i in items):
            return None
        out.append({"id": rid, "items": [i.strip() for i in items]})
    out.sort(key=lambda r: r["id"])
    if [r["id"] for r in out] != list(range(1, len(out) + 1)):
        return None
    return out


def check_base(j: object, mode: str, count: int) -> dict | None:
    """rotate.json の mode の基準 {id, week(date)}。id が 1〜count でない・week が月曜の日付でなければ None"""
    v = j.get(mode) if isinstance(j, dict) else None
    if not isinstance(v, dict):
        return None
    bid = v.get("id")
    if isinstance(bid, bool) or not isinstance(bid, int) or not 1 <= bid <= count:
        return None
    try:
        week = date.fromisoformat(str(v.get("week")))
    except ValueError:
        return None
    if week.weekday() != 0:
        return None
    return {"id": bid, "week": week}


def base_of(adjust: dict, bundled: object, mode: str, count: int) -> tuple[dict | None, bool]:
    """そのモードの基準と、手動調整かどうか。手動調整が壊れている・範囲外なら同梱の基準を使う"""
    manual = check_base(adjust, mode, count)
    if manual is not None:
        return manual, True
    return check_base(bundled, mode, count), False


def _now(d: Path, now: float | None) -> float:
    """時計のずれ(World State で合わせた値)を補正した今の時刻"""
    return (time.time() if now is None else now) + clock_offset(userdata.load_cycles(d))


def _rotation(mode: str, src: Path | None) -> list[dict] | None:
    if mode not in DUVIRI_MODES:
        raise TextError(txt("err.duviri.mode"))
    return check_rotation(appdata.read_duviri(DUVIRI_MODES[mode], src))


def set_duviri_adjust(d: Path, mode: str, rid: object, now: float | None = None, src: Path | None = None) -> None:
    """今週の ID を rid に合わせて保存する。モード・ID が正しくなければ ValueError(保存しない)"""
    rot = _rotation(mode, src)
    if rot is None:
        raise TextError(txt("err.duviri.broken"))
    if isinstance(rid, bool) or not isinstance(rid, int) or not 1 <= rid <= len(rot):
        raise TextError(txt("err.duviri.id", max=str(len(rot))))
    t = _now(d, now)
    adjust = userdata.load_duviri_adjust(d)
    adjust[mode] = {"id": rid, "week": week_start(datetime.fromtimestamp(t, timezone.utc)).isoformat(), "set_at": int(t)}
    userdata.save_duviri_adjust(d, adjust)


def clear_duviri_adjust(d: Path, mode: str) -> None:
    """そのモードの手動調整を消す(同梱の設定に戻す)。調整が無くてもエラーにしない"""
    if mode not in DUVIRI_MODES:
        raise TextError(txt("err.duviri.mode"))
    adjust = userdata.load_duviri_adjust(d)
    if mode in adjust:
        del adjust[mode]
        userdata.save_duviri_adjust(d, adjust)


def _row(rot: list[dict], rid: int, day: date) -> dict:
    return {"id": rid, "date": day.isoformat(), "items": list(rot[rid - 1]["items"])}


def mode_view(mode: str, rot: list[dict] | None, base: dict | None, now: datetime, manual: bool = False) -> dict:
    """1つのモードの表示用データ。ローテーションか基準が読めなければ ok: False(ほかのモードには影響しない)

    rotation は手動調整の選択肢(ID とアイテム)、manual は手動調整で計算しているか
    """
    if rot is None or base is None:
        return {"key": mode, "ok": False, "columns": 0, "current": None, "upcoming": [], "manual": False, "rotation": []}
    count = len(rot)
    cur = rotation_id(base["id"], weeks_since(base["week"], now), count)
    monday = week_start(now)
    upcoming = [_row(rot, rotation_id(cur, k, count), monday + timedelta(days=7 * k)) for k in range(1, count)]
    return {"key": mode, "ok": True, "columns": max(len(r["items"]) for r in rot),
            "current": _row(rot, cur, monday), "upcoming": upcoming, "manual": manual,
            "rotation": [{"id": r["id"], "items": list(r["items"])} for r in rot]}


def duviri_view(d: Path, now: float | None = None, src: Path | None = None) -> dict:
    """全モードの表示用データ。時刻は World State で合わせた時計のずれ(clock_offset)で補正する

    d: 利用者のデータ置き場(cycles.json の時計のずれを読む)、src: data/duviri の場所(テスト用。None なら同梱)
    """
    t = _now(d, now)
    nowdt = datetime.fromtimestamp(t, timezone.utc)
    bundled = appdata.read_duviri(DUVIRI_BASE_FILE, src)
    adjust = userdata.load_duviri_adjust(d)
    modes = []
    for mode in DUVIRI_MODES:
        rot = _rotation(mode, src)
        base, manual = base_of(adjust, bundled, mode, len(rot)) if rot else (None, False)
        modes.append(mode_view(mode, rot, base, nowdt, manual))
    return {"now": t, "modes": modes}
