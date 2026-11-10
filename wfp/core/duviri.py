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

from wfp.core.errors import TextError
from wfp.core.i18n import txt
from wfp.core.const import DUVIRI_BASE_FILE, DUVIRI_MODES
from wfp.core.cycle import clock_offset
from wfp.core.rotation import check_base, check_rows, rotation_id, week_start, weeks_since
from wfp.store import appdata, userdata


def _items(v: object) -> list[str] | None:
    """デュヴィリの1件の中身: 空でない文字列の配列(前後の空白を除く)"""
    if not isinstance(v, list) or not all(isinstance(i, str) and i.strip() for i in v):
        return None
    return [i.strip() for i in v]


def check_rotation(j: object) -> list[dict] | None:
    """ローテーションのファイルの中身を検査し、ID 順の [{id, items}] を返す。形が違えば None

    ID は 1〜件数の連番(並びは問わない)、items は空でない文字列の配列。
    """
    return check_rows(j, "items", _items)


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
    with userdata.editing(d, "duviri_adjust") as adjust:
        adjust[mode] = {"id": rid, "week": week_start(datetime.fromtimestamp(t, timezone.utc)).isoformat(), "set_at": int(t)}


def clear_duviri_adjust(d: Path, mode: str) -> None:
    """そのモードの手動調整を消す(同梱の設定に戻す)。調整が無くてもエラーにしない"""
    if mode not in DUVIRI_MODES:
        raise TextError(txt("err.duviri.mode"))
    if mode not in userdata.load_duviri_adjust(d):  # 調整が無ければ書かない(バックアップの差分を増やさない)
        return
    with userdata.editing(d, "duviri_adjust") as adjust:
        adjust.pop(mode, None)


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
