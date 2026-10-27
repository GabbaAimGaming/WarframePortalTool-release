#!/usr/bin/env python3
"""wfportal_worldstate - 公式の World State を取得して、必要な分だけ取り出す (標準ライブラリのみ)

World State は、ゲームの「いまの状態」(サイクル・バロ・侵略など)を公式が JSON で公開しているもの。
ドキュメントは公開されておらず、予告なく変わることがあるため、使う項目だけを取り出し、
取れなかった項目は無いものとして扱う(ツール全体は止めない)。

- 取得は利用者が操作したときだけ(サイクルの時刻合わせ・バロ情報の更新・侵略の更新)。常に問い合わせることはしない。
- 公式の CDN は 60 秒ほどキャッシュするため、前回の取得から COOLDOWN 秒以内は前回の結果を使う。
- 本文の Time はキャッシュされた時点の時刻なので、PC の時計のずれは HTTP の Date ヘッダーから求める。
- 保存するのは取り出した結果だけ (worldstate.json)。取得した全文は保存しない。

非公式のファンツールです。Digital Extremes Ltd. とは関係ありません。
"""
from __future__ import annotations

import json
import time
import urllib.request
from email.utils import parsedate_to_datetime
from pathlib import Path

from wfp.core.common import name_txt, render_ja, txt
from wfp.core.cycle import apply_worldstate_cycles, clock_offset
from wfp.fetch import decode, net
from wfp.store import userdata

# 新しい URL を先に試し、だめなら以前の URL。URL にクエリを付けると中身が空で返る(2026-10 時点)ので付けない
WORLDSTATE_URLS = [
    "https://api.warframe.com/cdn/worldState.php",
    "https://content.warframe.com/dynamic/worldState.php",
]
COOLDOWN = 60          # 秒。CDN のキャッシュ (max-age 60) と同じ
CLOCK_TOLERANCE = 2.0  # 秒。Date ヘッダーは 1 秒単位なので、これ未満のずれは 0 とみなす
SNAPSHOT_FILE = "worldstate.json"

# バロ(Void 商人)が来る中継地点
RELAYS = {
    "MercuryHUB": ("Larunda Relay", "Mercury"), "VenusHUB": ("Vesper Relay", "Venus"),
    "EarthHUB": ("Strata Relay", "Earth"), "SaturnHUB": ("Kronia Relay", "Saturn"),
    "ErisHUB": ("Kuiper Relay", "Eris"), "EuropaHUB": ("Leonov Relay", "Europa"),
    "PlutoHUB": ("Orcus Relay", "Pluto"), "TennoConHUB2": ("TennoCon Relay", ""),
}


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
    return 0.0 if abs(off) < CLOCK_TOLERANCE else round(off, 1)


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


def load_snapshot(d: Path) -> dict | None:
    f = d / SNAPSHOT_FILE
    try:
        j = json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
    except ValueError:
        return None
    return j if isinstance(j, dict) and isinstance(j.get("fetched_at"), (int, float)) else None


def sync(d: Path, force: bool = False, verbose: bool = False, fetcher=None, now: float | None = None) -> dict:
    """World State を取得して保存し、サイクルの基準時刻と時計のずれを更新する。

    前回の取得から COOLDOWN 秒以内なら取得せず前回の結果を返す(cached=True)。force=True で必ず取得する。
    取得に失敗したら WorldStateError(保存済みのデータは変えない)。
    """
    now = time.time() if now is None else now
    prev = load_snapshot(d)
    if prev and not force and 0 <= now - prev["fetched_at"] < COOLDOWN:
        return {**prev, "cached": True}
    if verbose:
        print("公式データ(World State)を取得中...")
    snap, offset = fetch(fetcher)
    if offset is None:  # ずれが分からないときは前回の値を使う
        offset = clock_offset(userdata.load_cycles(d))
    snap.update(fetched_at=now, offset=offset)
    (d / SNAPSHOT_FILE).write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    if snap["cetus"]:
        apply_worldstate_cycles(d, snap["cetus"]["expiry"], offset, now)
    elif verbose:
        print("  サイクルの情報が見つかりませんでした(基準時刻からの計算を続けます)")
    if verbose:
        print(f"  取得元: {snap['source']}")
    return {**snap, "cached": False}


def relay_txt(node: str):
    """バロが来るリレーのテキスト指定(「Orcus Relay(冥王星)」。惑星の無いリレー・知らないノードは名前だけ)"""
    name, planet = RELAYS.get(node, (node, ""))
    return txt("baro.relay", name=name, planet=name_txt("planet.", planet)) if planet else name


def relay_label(node: str) -> str:
    """リレーの日本語の表示名(CLI 用)"""
    return render_ja(relay_txt(node))
