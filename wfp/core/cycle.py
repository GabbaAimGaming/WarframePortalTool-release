"""サイクル(昼夜など)の計算と時刻合わせ"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from wfp.core.common import CAMBION, CETUS_PERIOD, CYCLES, CYCLE_SOURCES, fmt_dur
from wfp.store import userdata


def cycle_total(key: str) -> float:
    return sum(p[2] for p in CYCLES[key]["phases"])


def cycle_state(key: str, anchor: float, now: float) -> tuple[str, str, float]:
    """いまの段階 (英字キー, 表示名, 残り秒)。anchor は最初の段階が始まった時刻(その前後どの周回でもよい)"""
    pos = (now - anchor) % cycle_total(key)
    start = 0.0
    for k, jp, length in CYCLES[key]["phases"]:
        if pos < start + length:
            return k, jp, start + length - pos
        start += length
    k, jp, _ = CYCLES[key]["phases"][-1]  # 浮動小数の端数でここに来たときは最後の段階の終わり際
    return k, jp, 0.0


def cycle_next(key: str, anchor: float, now: float) -> tuple[str, str]:
    """次の段階 (英字キー, 表示名)"""
    k = cycle_state(key, anchor, now)[0]
    phases = CYCLES[key]["phases"]
    i = [p[0] for p in phases].index(k)
    return phases[(i + 1) % len(phases)][:2]


def cycle_anchor(key: str, phase: str | None, remaining: float, now: float) -> float:
    """「いま phase で残り remaining 秒」から、最初の段階が始まった時刻を逆算する。"""
    phases = CYCLES[key]["phases"]
    keys = [p[0] for p in phases]
    if phase not in keys:
        raise ValueError(f"フェーズは {' / '.join(p[1] for p in phases)} のいずれかを指定してください。")
    i = keys.index(phase)
    length = phases[i][2]
    if not 0 < remaining <= length:
        raise ValueError(f"残り時間が範囲外です(このフェーズは最長 {fmt_dur(length)})。")
    phase_start = now + remaining - length
    return phase_start - sum(p[2] for p in phases[:i])


def anchor_from_cetus_expiry(key: str, expiry: float) -> float:
    """公式 World State の CetusSyndicate の期限(夜明け)から、key の周期の基準時刻を求める。

    Cetus: 期限 = 昼の始まり。Zariman: 期限で勢力が切り替わる。どちらに切り替わるかは World State に無いため、
    基準時刻(ref)から何周目かの偶奇で決める(周期は 8998.874 秒で一定。半周ずれるほどの誤差は出ない)
    """
    if key == "cetus":
        return expiry
    if key == "zariman":
        n = round((expiry - CYCLES[key]["ref"]) / CETUS_PERIOD)
        return expiry if n % 2 == 0 else expiry - CETUS_PERIOD
    raise ValueError(f"{key} は World State から同期できません。")


def clock_offset(store: dict) -> float:
    """公式サーバーの時刻 - PC の時刻(秒)。同期したことが無ければ 0"""
    return float((store.get("_clock") or {}).get("offset", 0.0))


def set_manual_cycle(d: Path, key: str, phase: str | None, remaining: float, now: float | None = None) -> dict:
    """ゲーム内で見た残り時間で時刻合わせして保存する。保存後の cycles.json の中身を返す"""
    if key not in CYCLES or not CYCLES[key]["manual"]:
        raise ValueError(f"手動で合わせられるのは {' / '.join(k for k, c in CYCLES.items() if c['manual'])} です。")
    store = userdata.load_cycles(d)
    now = (time.time() if now is None else now) + clock_offset(store)
    store[key] = {"anchor": cycle_anchor(key, phase, remaining, now), "source": "manual", "synced_at": now}
    userdata.save_cycles(d, store)
    return store


def apply_worldstate_cycles(d: Path, cetus_expiry: float, offset: float, now: float | None = None) -> dict:
    """World State の値で基準時刻と時計のずれを保存する。手動の時刻合わせは公式データで上書きする"""
    store = userdata.load_cycles(d)
    now = time.time() if now is None else now
    for key, c in CYCLES.items():
        if c.get("sync") == "cetus":
            store[key] = {"anchor": anchor_from_cetus_expiry(key, cetus_expiry), "source": "worldstate", "synced_at": now}
    store["_clock"] = {"offset": offset, "synced_at": now}
    userdata.save_cycles(d, store)
    return store


def cycle_rows(d: Path, now: float | None = None) -> dict:
    """画面・コマンド共通のサイクル表示。now は PC の時刻(省略時は現在)。時計のずれは中で補正する"""
    store = userdata.load_cycles(d)
    offset = clock_offset(store)
    t = (time.time() if now is None else now) + offset
    rows = []
    for key, c in CYCLES.items():
        saved = store.get(key)
        anchor, source = (saved["anchor"], saved["source"]) if saved else (c["ref"], "default")
        k, jp, left = cycle_state(key, anchor, t)
        nk, njp = cycle_next(key, anchor, t)
        row = {"key": key, "name": c["name"], "phase_key": k, "phase": jp, "left": left, "next_key": nk, "next": njp,
               "source": source, "source_ja": CYCLE_SOURCES[source], "synced_at": saved.get("synced_at") if saved else None,
               "manual": c["manual"], "phases": [p[1] for p in c["phases"]], "phase_keys": [p[0] for p in c["phases"]],
               "max": {p[1]: p[2] for p in c["phases"]}}
        if key == "cetus":
            row["cambion"] = CAMBION[k]
        rows.append(row)
    return {"now": t, "offset": offset, "clock_synced_at": (store.get("_clock") or {}).get("synced_at"), "cycles": rows}


def next_daily_reset(now: datetime) -> datetime:
    base = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return base + timedelta(days=1)


def next_weekly_reset(now: datetime) -> datetime:
    base = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return base + timedelta(days=7 - base.weekday())  # 次の月曜 0:00 UTC
