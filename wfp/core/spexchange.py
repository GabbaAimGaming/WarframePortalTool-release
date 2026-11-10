"""鋼の道のり交換(スティール・エッセンス交換)のローテーション(今週の報酬と今後の並び)

デュヴィリサーキットと同じ仕組み: 今の週はファイルに書き込まず、毎回「同梱の基準の週 + 経過週数」で計算する。
週の切り替わりはウィークリーリセット(月曜 0:00 UTC)。手動調整は無い(ズレたら開発側が spex_rotate.json を直して配る)。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from wfp.core.const import SPEX_BASE_FILE, SPEX_MODE, SPEX_ROTATION_FILE
from wfp.core.rotation import check_base, check_rows, rotation_id, week_start, weeks_since
from wfp.store import appdata


def _item(v: object) -> str | None:
    """交換の1件の中身: 空でない文字列(デュヴィリと違って配列ではない)"""
    return v.strip() if isinstance(v, str) and v.strip() else None


def check_spex_rotation(j: object) -> list[dict] | None:
    """ローテーションのファイルの中身を検査し、ID 順の [{id, item}] を返す。形が違えば None

    ID は 1〜件数の連番(並びは問わない)、items は空でない文字列(デュヴィリと違って配列ではない)。
    """
    return check_rows(j, "item", _item)


def _row(rot: list[dict], rid: int, day) -> dict:
    return {"id": rid, "date": day.isoformat(), "item": rot[rid - 1]["item"]}


def spex_view(now: float, src: Path | None = None) -> dict:
    """表示用データ。ローテーションか基準が読めなければ ok: False(サイクルの表示は止めない)

    now: 時計のずれを補正済みの時刻(サイクルの表示と同じ瞬間で計算する)、src: data/spexchange の場所(テスト用)
    upcoming は今週を除いた今後の週(件数 - 1 週分)
    """
    rot = check_spex_rotation(appdata.read_spexchange(SPEX_ROTATION_FILE, src))
    base = check_base(appdata.read_spexchange(SPEX_BASE_FILE, src), SPEX_MODE, len(rot)) if rot else None
    if rot is None or base is None:
        return {"ok": False, "current": None, "upcoming": []}
    nowdt = datetime.fromtimestamp(now, timezone.utc)
    count = len(rot)
    cur = rotation_id(base["id"], weeks_since(base["week"], nowdt), count)
    monday = week_start(nowdt)
    return {"ok": True, "current": _row(rot, cur, monday),
            "upcoming": [_row(rot, rotation_id(cur, k, count), monday + timedelta(days=7 * k)) for k in range(1, count)]}
