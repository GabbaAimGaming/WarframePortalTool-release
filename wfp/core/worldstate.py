"""公式の World State: 取得して保存し、サイクルの基準時刻と PC の時計のずれを更新する(sync)・バロが来る中継地の名前(relay_txt)。

- 取得は利用者が操作したときだけ(サイクルの時刻合わせ・バロ情報の更新・侵略の更新)。常に問い合わせることはしない
- 公式の CDN は 60 秒ほどキャッシュするため、前回の取得から WORLDSTATE_COOLDOWN 秒以内は前回の結果を使う
- 取得と取り出しは wfp/fetch/worldstate、保存は wfp/store/gamedata(read_worldstate / save_worldstate)
- 2026-11-10 に wfportal_worldstate から移した(D4)
"""
from __future__ import annotations

import time
from pathlib import Path

from wfp.core.const import BARO_RELAYS, WORLDSTATE_COOLDOWN
from wfp.core.cycle import apply_worldstate_cycles, clock_offset
from wfp.core.i18n import name_txt, txt
from wfp.core.log import say
from wfp.fetch import worldstate as wsfetch
from wfp.store import gamedata, userdata


def sync(d: Path, force: bool = False, verbose: bool = False, fetcher=None, now: float | None = None) -> dict:
    """World State を取得して保存し、サイクルの基準時刻と時計のずれを更新する。

    前回の取得から WORLDSTATE_COOLDOWN 秒以内なら取得せず前回の結果を返す(cached=True)。force=True で必ず取得する。
    取得に失敗したら fetch/worldstate の WorldStateError(保存済みのデータは変えない)。
    """
    now = time.time() if now is None else now
    prev = gamedata.read_worldstate(d)
    if prev and not force and 0 <= now - prev["fetched_at"] < WORLDSTATE_COOLDOWN:
        return {**prev, "cached": True}
    if verbose:
        say(txt("log.ws.fetching"))
    snap, offset = wsfetch.fetch(fetcher)
    if offset is None:  # ずれが分からないときは前回の値を使う
        offset = clock_offset(userdata.load_cycles(d))
    snap.update(fetched_at=now, offset=offset)
    gamedata.save_worldstate(d, snap)
    if snap["cetus"]:
        apply_worldstate_cycles(d, snap["cetus"]["expiry"], offset, now)
    elif verbose:
        say(txt("log.ws.nocycle"), 1)
    if verbose:
        say(txt("log.ws.source", url=snap["source"]), 1)
    return {**snap, "cached": False}


def relay_txt(node: str):
    """バロが来るリレーのテキスト指定(「Orcus Relay(冥王星)」。惑星の無いリレー・知らないノードは名前だけ)"""
    name, planet = BARO_RELAYS.get(node, (node, ""))
    return txt("baro.relay", name=name, planet=name_txt("planet.", planet)) if planet else name
