"""公式の World State の取得と、使う項目だけの取り出し(標準ライブラリのみ)。

World State は、ゲームの「いまの状態」(サイクル・バロ・侵略など)を公式が JSON で公開しているもの。
ドキュメントは公開されておらず、予告なく変わることがあるため、使う項目だけを取り出し、
取れなかった項目は無いものとして扱う(ツール全体は止めない)。

- 本文の Time はキャッシュされた時点の時刻なので、PC の時計のずれは HTTP の Date ヘッダーから求める
- 保存・取り直しの間隔・サイクルへの反映は wfp/core/worldstate の sync、保存は wfp/store/gamedata の save_worldstate
- 2026-11-10 に wfportal_worldstate から移した(D4)

非公式のファンツールです。Digital Extremes Ltd. とは関係ありません。
"""
from __future__ import annotations

import time
import urllib.request
from email.utils import parsedate_to_datetime

from wfp.core.const import WORLDSTATE_CLOCK_TOLERANCE, WORLDSTATE_URLS
from wfp.fetch import decode, net


class WorldStateError(RuntimeError):
    pass


def http_get_with_headers(url: str, timeout: int = 30) -> tuple[bytes, dict]:
    """本文と、小文字にしたヘッダーを返す"""
    req = urllib.request.Request(url, headers={"User-Agent": net.USER_AGENT, "Accept": "application/json, */*",
                                               "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
        headers = {k.lower(): v for k, v in r.headers.items()}
    if headers.get("content-encoding", "").lower() == "gzip" or data[:2] == b"\x1f\x8b":
        import gzip
        data = gzip.decompress(data)
    return data, headers


def ms_date(v) -> float | None:
    """World State の日時 {"$date": {"$numberLong": "ミリ秒"}} を秒にする。読めなければ None"""
    try:
        if isinstance(v, dict):
            v = v["$date"]
            if isinstance(v, dict):
                v = v["$numberLong"]
        return int(v) / 1000.0
    except (KeyError, TypeError, ValueError):
        return None


def clock_offset_from_headers(headers: dict, local_mid: float) -> float | None:
    """公式サーバーの時刻 - PC の時刻(秒)。Date ヘッダーが無ければ None(ずれは分からない)"""
    try:
        server = parsedate_to_datetime(headers["date"]).timestamp() + 0.5  # 1 秒未満は切り捨てられているので半分足す
    except (KeyError, TypeError, ValueError):
        return None
    off = server - local_mid
    return 0.0 if abs(off) < WORLDSTATE_CLOCK_TOLERANCE else round(off, 1)


def extract(ws: dict) -> dict:
    """World State から使う項目だけを取り出す(取れない項目は None / 空)"""
    if not isinstance(ws, dict):
        raise WorldStateError("World State の形式が想定と違います。")
    cetus = None
    for s in ws.get("SyndicateMissions") or []:
        if isinstance(s, dict) and s.get("Tag") == "CetusSyndicate":
            act, exp = ms_date(s.get("Activation")), ms_date(s.get("Expiry"))
            if exp is not None:
                cetus = {"activation": act, "expiry": exp}
            break
    traders = []
    for v in ws.get("VoidTraders") or []:
        if not isinstance(v, dict):
            continue
        act, exp = ms_date(v.get("Activation")), ms_date(v.get("Expiry"))
        if act is None or exp is None:
            continue
        items = []
        for m in v.get("Manifest") or []:
            if isinstance(m, dict) and isinstance(m.get("ItemType"), str):
                items.append({"path": m["ItemType"], "ducats": m.get("PrimePrice"), "credits": m.get("RegularPrice"),
                              "limit": m.get("Limit")})
        traders.append({"character": v.get("Character") or "", "node": v.get("Node") or "", "activation": act,
                        "expiry": exp, "items": items})
    return {"server_time": ws.get("Time"), "build": ws.get("BuildLabel"), "cetus": cetus, "traders": traders,
            "invasions": extract_invasions(ws.get("Invasions"))}


def _number(v) -> float | None:
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _oid(v) -> str:
    """{"$oid": "…"} の中身(文字列ならそのまま)。読めなければ空文字"""
    v = v.get("$oid") if isinstance(v, dict) else v
    return v if isinstance(v, str) else ""


def _rewards(v) -> list[dict]:
    """侵略の報酬 {"countedItems": [{"ItemType", "ItemCount"}]} を [{path, count}] にする。

    感染体が攻め側のときは辞書ではなく空の配列 [] で来る。読めない項目(クレジット等の別キー)は無視する。
    """
    items = v.get("countedItems") if isinstance(v, dict) else None
    out = []
    for it in items if isinstance(items, list) else []:
        if isinstance(it, dict) and isinstance(it.get("ItemType"), str):
            n = it.get("ItemCount")
            out.append({"path": it["ItemType"], "count": n if isinstance(n, int) and not isinstance(n, bool) and n > 0 else 1})
    return out


def extract_invasions(raw) -> list[dict]:
    """World State の Invasions から使う項目だけを取り出す(完了済みも残す。除くのは表示側)。ノードが無いものは飛ばす"""
    out = []
    for v in raw if isinstance(raw, list) else []:
        if not isinstance(v, dict) or not isinstance(v.get("Node"), str):
            continue
        out.append({"id": _oid(v.get("_id")), "node": v["Node"],
                    "attacker": v.get("Faction") if isinstance(v.get("Faction"), str) else "",
                    "defender": v.get("DefenderFaction") if isinstance(v.get("DefenderFaction"), str) else "",
                    "count": _number(v.get("Count")), "goal": _number(v.get("Goal")),
                    "completed": v.get("Completed") is True, "activation": ms_date(v.get("Activation")),
                    "loc_tag": v.get("LocTag") if isinstance(v.get("LocTag"), str) else "",
                    "attacker_reward": _rewards(v.get("AttackerReward")),
                    "defender_reward": _rewards(v.get("DefenderReward"))})
    return out


def fetch(fetcher=None) -> tuple[dict, float | None]:
    """World State を取得して (取り出した結果, 時計のずれ) を返す。fetcher はテスト用(url -> (本文, ヘッダー))"""
    fetcher = fetcher or http_get_with_headers
    errors = []
    for url in WORLDSTATE_URLS:
        t0 = time.time()
        try:
            raw, headers = fetcher(url)
            local_mid = (t0 + time.time()) / 2
            snap = extract(decode.parse_json_bytes(raw))
        except Exception as e:  # noqa: BLE001
            errors.append(f"{url} ({e})")
            continue
        snap["source"] = url
        return snap, clock_offset_from_headers(headers, local_mid)
    raise WorldStateError(" / ".join(errors))
