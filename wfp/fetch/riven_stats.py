"""Riven 相場(公式の週次統計)の取得と形の統一"""
from __future__ import annotations

from wfp.core.common import RIVENS_URLS
from wfp.fetch import decode, net


def normalize_rivens(raw) -> list[dict]:
    """Riven 相場を [{itemType, compatibility, rerolled, avg, ...}] の形にそろえる。

    公式 weeklyRivensPC.json はこの形の配列。WFCD (api.warframestat.us/pc/rivens) は
    {武器種: {武器名: {"unrolled": {...}, "rerolled": {...}}}} の入れ子で、未開封は "Veiled ○○ Riven Mod"。
    """
    if isinstance(raw, dict):
        for key in ("rivens", "data", "items"):
            if isinstance(raw.get(key), list):
                raw = raw[key]
                break
    if isinstance(raw, list):
        rows = [e for e in raw if isinstance(e, dict) and e.get("itemType")]
    elif isinstance(raw, dict):
        rows = []
        for item_type, weapons in raw.items():
            if not isinstance(weapons, dict):
                continue
            for weapon, kinds in weapons.items():
                if not isinstance(kinds, dict):
                    continue
                for kind, st in kinds.items():
                    if isinstance(st, dict) and kind in ("unrolled", "rerolled"):
                        rows.append({**st, "itemType": st.get("itemType") or item_type,
                                     "compatibility": st.get("compatibility", weapon), "rerolled": kind == "rerolled"})
    else:
        rows = []
    for e in rows:
        c = e.get("compatibility")
        if not c or str(c).lower().startswith("veiled ") or str(c).strip().lower() == "null":
            e["compatibility"] = None
    return rows


def fetch_rivens() -> list[dict]:
    """Riven 相場を取得して形をそろえる(候補 URL を順に試す)"""
    return normalize_rivens(decode.parse_json_bytes(net.fetch_json(RIVENS_URLS, verbose=True)))
