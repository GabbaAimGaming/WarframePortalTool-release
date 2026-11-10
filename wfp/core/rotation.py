"""週ごとのローテーション(デュヴィリサーキット・鋼の道のり交換)の共通部分: 週の計算・基準の検査・ローテーションの表の検査。

週は月曜 0:00 UTC で切り替わる(core.cycle の next_weekly_reset)。同梱データの形の違い(1件の中身が配列か文字列か)は
check_rows に渡す item で吸収する。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Callable

from wfp.core.cycle import next_weekly_reset


def week_start(now: datetime) -> date:
    """now を含む週の月曜(UTC)の日付"""
    return (next_weekly_reset(now) - timedelta(days=7)).date()


def weeks_since(base: date, now: datetime) -> int:
    """基準の週(月曜の日付)から now までに跨いだ月曜 0:00 UTC の回数。基準より前なら負"""
    return (week_start(now) - base).days // 7


def rotation_id(base_id: int, weeks: int, count: int) -> int:
    """基準の ID から weeks 週進んだ ID(1〜count で折り返す。weeks が負でも正しく折り返す)"""
    return (base_id - 1 + weeks) % count + 1


def check_base(j: object, mode: str, count: int) -> dict | None:
    """基準のファイル(rotate.json など)の mode の基準 {id, week(date)}。id が 1〜count でない・week が月曜の日付でなければ None"""
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


def check_rows(j: object, key: str, item: Callable[[object], object | None]) -> list[dict] | None:
    """ローテーションのファイルの中身 {"rotation": [{id, items}]} を検査し、ID 順の [{id, <key>: item(items)}] を返す。形が違えば None

    ID は 1〜件数の連番(並びは問わない)。item は1件の items を検査してそろえた値を返す(形が違えば None)。
    """
    rows = j.get("rotation") if isinstance(j, dict) else None
    if not isinstance(rows, list) or not rows:
        return None
    out = []
    for r in rows:
        if not isinstance(r, dict):
            return None
        rid = r.get("id")
        if isinstance(rid, bool) or not isinstance(rid, int):
            return None
        val = item(r.get("items"))
        if val is None:
            return None
        out.append({"id": rid, key: val})
    out.sort(key=lambda r: r["id"])
    if [r["id"] for r in out] != list(range(1, len(out) + 1)):
        return None
    return out
