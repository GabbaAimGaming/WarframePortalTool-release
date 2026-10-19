#!/usr/bin/env python3
"""wfportal_baro - バロ吉入手一覧: Void 商人 (Baro Ki'Teer) の品物と、自分の所持の照合 (標準ライブラリのみ)

- 今回の品物: 公式 World State (wfportal_worldstate) の VoidTraders。品物は内部パスなので、
  「データ更新」のときに Public Export から作るパス → 英語名の辞書 (item_paths.json) で名前にする。
- 履歴リスト(これまでに持ってきた品物)= ① 初期リスト + ② この PC で記録した来訪
    ① 初期リスト: 公式データ(names.json)から作る。バロだけが持ってくる(ほぼバロだけの)品物
         - 名前が "Prisma " で始まるマスター対象(武器・コンパニオン・アークウイング系)
         - 名前が "Primed " で始まるレジェンダリーの MOD(data/baro_rules.json の primed_exclude を除く)
         - data/baro_rules.json の include(Primed Chamber など、上の条件に当てはまらないもの)
    ② 来訪の記録 (baro_seen.json): 「バロ情報を更新」でバロが来ている品物を取得したとき、来訪日と品物を記録する。
       履歴リストに無い品物は追加され、ある品物は「最後に来た日」「回数」が更新される。
       過去の日付は分からないので、回数・最後に来た日はこの PC で記録した来訪だけで数える。
- 所持の照合は種類で振り分ける:
    MOD         → MOD入手一覧の所持チェック (mods_owned.json)
    武器        → マスター一覧のマスター済み (mastered.json)。マスター済み = 入手したことがある、とみなす
    消耗品など  → 何度でも買えるので照合しない
    それ以外    → このページの手動チェック (baro_owned.json)
  名前が " Skin" で終わるものは、パスや初期リストの分け方によらず装飾・外装として扱う。

非公式のファンツールです。Digital Extremes Ltd. とは関係ありません。
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from wfp.core import common
from wfp.core.cycle import clock_offset
from wfp.core.loader import load_names
from wfp.core.names import Names
from wfp.store import userdata

SEEN_FILE = "baro_seen.json"      # この PC で記録した来訪
OWNED_FILE = "baro_owned.json"    # このページの手動チェック
PATHS_FILE = "item_paths.json"    # 内部パス → 英語名(「データ更新」で作る)
RULES_FILE = common.APP_DIR / "data" / "baro_rules.json"  # 初期リストの除外・追加(ツールに同梱。編集してよい)

# 照合の種類
KINDS = {"mod": "MOD", "weapon": "武器", "manual": "装飾・外装など", "repeat": "消耗品など"}
CHECK_BY = {"mod": "MOD入手一覧の所持", "weapon": "マスター一覧のマスター済み", "manual": "このページのチェック", "repeat": "照合しない"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TENNOCON_NODES = {"TennoConHUB2"}  # TennoCon は過去の品物がすべて並ぶ特別な来訪なので、記録しない


# --------------------------------------------------------------------------
# 種類の判定
# --------------------------------------------------------------------------

def kind_of_path(path: str) -> str:
    """内部パスから照合の種類を推定する。武器スキンのパス (/Upgrades/Skins/Weapons/...) は武器ではない"""
    if "/Upgrades/Skins/" in path:
        return "manual"
    if "/Upgrades/Mods/" in path or "/SentinelPrecepts/" in path:
        return "mod"
    if "/Weapons/" in path:
        return "weapon"
    if any(s in path for s in ("/BoosterPacks/", "/Boosters/", "/Projections/", "/Restoratives/")):
        return "repeat"
    return "manual"


def fix_kind(name: str, kind: str) -> str:
    """名前が " Skin" で終わるもの(武器スキンなど)は装飾・外装として扱う"""
    return "manual" if name.rstrip().lower().endswith(" skin") else kind


# --------------------------------------------------------------------------
# ① 初期リスト (公式データから作る)
# --------------------------------------------------------------------------

def load_rules(path: Path | None = None) -> dict:
    """data/baro_rules.json を読む。無い・壊れているときは空(除外なし・追加なし)"""
    f = path or RULES_FILE
    try:
        j = json.loads(f.read_text(encoding="utf-8-sig")) if f.exists() else {}
    except ValueError:
        j = {}
    j = j if isinstance(j, dict) else {}
    as_list = lambda v: [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []  # noqa: E731
    return {"primed_exclude": {x.lower() for x in as_list(j.get("primed_exclude"))}, "include": as_list(j.get("include"))}


def seed_items(names: Names, rules: dict) -> list[dict]:
    """初期リスト [{name, kind}]。名前データが無ければ空"""
    out: dict[str, dict] = {}
    for m in names.mastery:  # Kitgun はプライマリ版・セカンダリ版で2件あるが、名前で1つにまとめる
        if m["en"].startswith("Prisma "):
            out.setdefault(m["en"].lower(), {"name": m["en"], "kind": "weapon"})
    for m in names.mods:
        if m["en"].startswith("Primed ") and m.get("rarity") == "Legendary" and m["en"].lower() not in rules["primed_exclude"]:
            out.setdefault(m["en"].lower(), {"name": m["en"], "kind": "mod"})
    mods = {m["en"].lower(): m["en"] for m in names.mods}
    weapons = {m["en"].lower(): m["en"] for m in names.mastery}
    for name in rules["include"]:
        k = name.lower()
        if k in mods:
            out.setdefault(k, {"name": mods[k], "kind": "mod"})
        elif k in weapons:
            out.setdefault(k, {"name": weapons[k], "kind": "weapon"})
        else:
            out.setdefault(k, {"name": name, "kind": "manual"})
    for r in out.values():
        r["kind"] = fix_kind(r["name"], r["kind"])
    return sorted(out.values(), key=lambda r: r["name"].lower())


# --------------------------------------------------------------------------
# ② この PC で記録した来訪
# --------------------------------------------------------------------------
# baro_seen.json: {"visits": {"2026-10-16": {"recorded_at": 時刻, "node": "PlutoHUB",
#                                           "items": {英語名: {"kind": 種類, "ducats": 数, "credits": 数}}}}}
# 来訪日は到着の UTC の日付(バロは金曜 13:00 UTC ごろに来る)

def visit_date(activation: float) -> str:
    return datetime.fromtimestamp(activation, timezone.utc).strftime("%Y-%m-%d")


def load_seen(d: Path) -> dict:
    f = d / SEEN_FILE
    try:
        j = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except ValueError:
        return {}
    visits = j.get("visits") if isinstance(j, dict) else None
    if not isinstance(visits, dict):
        return {}
    return {k: v for k, v in visits.items()
            if DATE_RE.match(str(k)) and isinstance(v, dict) and isinstance(v.get("items"), dict)}


def save_seen(d: Path, visits: dict) -> None:
    (d / SEEN_FILE).write_text(json.dumps({"visits": visits}, ensure_ascii=False), encoding="utf-8")


def record_visit(d: Path, snap: dict | None, paths: dict, now: float) -> str | None:
    """保存済みの World State に、いま来ているバロの品物があれば記録する。記録した来訪日を返す。

    名前が分からない品物(「データ更新」前の新しい品物)は記録しない(あとで名前が分かったときに別の品物にならないように)。
    同じ来訪で何度記録しても、品物が増えるだけで回数は増えない。
    """
    t = pick_trader((snap or {}).get("traders") or [], now)
    if not t or not t["items"] or not t["activation"] <= now < t["expiry"] or t["node"] in TENNOCON_NODES:
        return None
    items = {}
    for it in t["items"]:
        en, found = path_name(it["path"], paths)
        if found:
            items[en] = {"kind": kind_of_path(it["path"]), "ducats": it["ducats"], "credits": it["credits"]}
    if not items:
        return None
    date = visit_date(t["activation"])
    visits = load_seen(d)
    prev = visits.get(date, {})
    visits[date] = {"recorded_at": now, "node": t["node"], "items": {**prev.get("items", {}), **items}}
    save_seen(d, visits)
    return date


def history_items(seeds: list[dict], visits: dict) -> list[dict]:
    """履歴リスト = 初期リスト + 記録した来訪。記録に出てきた品物は追加し、日付・値段を更新する"""
    by = {r["name"].lower(): {"name": r["name"], "kind": r["kind"], "ducats": None, "credits": None,
                              "dates": [], "seed": True} for r in seeds}
    for date in sorted(visits):
        for name, info in visits[date]["items"].items():
            r = by.get(name.lower())
            if r is None:
                kind = info.get("kind") if info.get("kind") in KINDS else "manual"
                r = by[name.lower()] = {"name": name, "kind": kind, "ducats": None, "credits": None, "dates": [], "seed": False}
            if date not in r["dates"]:
                r["dates"].append(date)
            r["ducats"], r["credits"] = info.get("ducats"), info.get("credits")  # 新しい来訪の値段で上書き
    for r in by.values():
        r["dates"].sort()
        r["last"], r["count"] = (r["dates"][-1] if r["dates"] else None), len(r["dates"])
        r["kind"] = fix_kind(r["name"], r["kind"])
    return sorted(by.values(), key=lambda r: r["name"].lower())


def load_history_items(d: Path, names: Names) -> list[dict]:
    return history_items(seed_items(names, load_rules()), load_seen(d))


# --------------------------------------------------------------------------
# 内部パス → 名前 (「データ更新」のときに Public Export から作る)
# --------------------------------------------------------------------------

def item_paths_from_exports(en_docs: list[dict]) -> dict:
    """{内部パス: 英語名}。設計図 (ExportRecipes) は「作れるものの名前 + Blueprint」"""
    names, recipes = {}, {}
    for doc in en_docs:
        for key, val in doc.items():
            if not isinstance(val, list):
                continue
            for it in val:
                if not isinstance(it, dict) or not isinstance(it.get("uniqueName"), str):
                    continue
                if it.get("name"):
                    names.setdefault(it["uniqueName"], it["name"])
                elif key == "ExportRecipes" and isinstance(it.get("resultType"), str):
                    recipes[it["uniqueName"]] = it["resultType"]
    for uid, result in recipes.items():
        if result in names:
            names.setdefault(uid, f"{names[result]} Blueprint")
    return names


def save_item_paths(d: Path, paths: dict) -> None:
    (d / PATHS_FILE).write_text(json.dumps(paths, ensure_ascii=False), encoding="utf-8")


def load_item_paths(d: Path) -> dict:
    f = d / PATHS_FILE
    try:
        j = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except ValueError:
        return {}
    return j if isinstance(j, dict) else {}


def path_name(path: str, paths: dict) -> tuple[str, bool]:
    """(英語名, 辞書で見つかったか)。World State は /StoreItems/ 付きのパスで、Export には付かないものが多い"""
    for p in (path, path.replace("/StoreItems/", "/", 1)):
        if p in paths:
            return paths[p], True
    # 見つからないときは、パスの最後の部分を読みやすくして出す(例: PlushyBaroEvil → Plushy Baro Evil)
    last = path.rstrip("/").rsplit("/", 1)[-1]
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", last) or path, False


# --------------------------------------------------------------------------
# 所持の照合
# --------------------------------------------------------------------------

def load_manual_owned(d: Path) -> set[str]:
    f = d / OWNED_FILE
    try:
        j = json.loads(f.read_text(encoding="utf-8-sig")) if f.exists() else []
    except ValueError:
        return set()
    return {str(x).lower() for x in j} if isinstance(j, list) else set()


def set_manual_owned(d: Path, name: str, owned: bool, names: Names | None = None) -> set[str]:
    """手動チェックを付け外しする(装飾・外装など、ほかの一覧で照合できないものだけ)"""
    key = name.strip().lower()
    if not key:
        raise ValueError("名前がありません。")
    known = {r["name"].lower(): r["kind"] for r in load_history_items(d, names or load_names(d))}
    if known.get(key, fix_kind(key, "manual")) != "manual":
        raise ValueError(f"{name} は {CHECK_BY[known[key]]} で照合します(このページではチェックしません)。")
    s = load_manual_owned(d)
    (s.add if owned else s.discard)(key)
    (d / OWNED_FILE).write_text(json.dumps(sorted(s), ensure_ascii=False, indent=0), encoding="utf-8")
    return s


class Owned:
    """照合に使う所持データ(MOD・マスター・手動)をまとめたもの"""

    def __init__(self, d: Path, names: Names):
        self.mods = userdata.load_owned(d)
        done = userdata.load_mastered(d)
        self.mastered = {m["en"].lower() for m in names.mastery if m["id"] in done}
        self.manual = load_manual_owned(d)

    def status(self, name: str, kind: str) -> bool | None:
        """所持していれば True、していなければ False、照合しないものは None"""
        k = name.lower()
        if kind == "mod":
            return k in self.mods
        if kind == "weapon":
            return k in self.mastered
        if kind == "manual":
            return k in self.manual
        return None


def row(name: str, kind: str, names: Names, owned: Owned) -> dict:
    return {"name": name, "ja": names.ja(name), "kind": kind, "kind_ja": KINDS[kind], "check_by": CHECK_BY[kind],
            "owned": owned.status(name, kind)}


def history_rows(items: list[dict], names: Names, owned: Owned) -> list[dict]:
    """履歴リストの照合表"""
    return [{**row(r["name"], r["kind"], names, owned), "ducats": r["ducats"], "credits": r["credits"],
             "last": r["last"], "count": r["count"], "seed": r["seed"]} for r in items]


def pick_trader(traders: list[dict], now: float) -> dict | None:
    """いま来ているバロ(品物ありを優先)。いなければ次に来るバロ。どちらも無ければ最後に来ていたもの"""
    active = [t for t in traders if t["activation"] <= now < t["expiry"]]
    if active:
        return max(active, key=lambda t: len(t["items"]))
    future = [t for t in traders if t["activation"] > now]
    if future:
        return min(future, key=lambda t: t["activation"])
    return max(traders, key=lambda t: t["expiry"]) if traders else None


def current_trader(snap: dict | None, items_hist: list[dict], paths: dict, names: Names, owned: Owned,
                   now: float) -> dict | None:
    """保存済みの World State から、いま(または次)のバロと品物の照合結果を作る。回数は記録した来訪で数える"""
    import wfportal_worldstate as ws
    t = pick_trader((snap or {}).get("traders") or [], now)
    if t is None:
        return None
    by_name = {r["name"].lower(): r for r in items_hist}
    items = []
    for it in t["items"]:
        en, found = path_name(it["path"], paths)
        h = by_name.get(en.lower())
        kind = h["kind"] if h else fix_kind(en, kind_of_path(it["path"]))
        items.append({**row(en, kind, names, owned), "path": it["path"], "named": found, "ducats": it["ducats"],
                      "credits": it["credits"], "limit": it["limit"], "in_history": bool(h),
                      "count": h["count"] if h else 0})
    state = "here" if t["activation"] <= now < t["expiry"] else ("coming" if t["activation"] > now else "gone")
    return {"character": t["character"], "node": t["node"], "relay": ws.relay_label(t["node"]),
            "activation": t["activation"], "expiry": t["expiry"], "state": state, "items": items,
            "fetched_at": (snap or {}).get("fetched_at")}


def summary(rows: list[dict]) -> dict:
    out = {k: {"total": 0, "owned": 0} for k in KINDS}
    for r in rows:
        o = out[r["kind"]]
        o["total"] += 1
        o["owned"] += bool(r["owned"])
    checkable = [r for r in rows if r["owned"] is not None]
    out["all"] = {"total": len(checkable), "owned": sum(bool(r["owned"]) for r in checkable)}
    return out


def baro_view(d: Path, names: Names, now: float | None = None) -> dict:
    """画面・コマンド共通: 履歴リストの照合表と、いま(次)のバロ"""
    import wfportal_worldstate as ws
    now = time.time() if now is None else now
    visits = load_seen(d)
    items = history_items(seed_items(names, load_rules()), visits)
    owned = Owned(d, names)
    rows = history_rows(items, names, owned)
    offset = clock_offset(userdata.load_cycles(d))
    return {"rows": rows, "summary": summary(rows), "kinds": KINDS,
            "visits": {"count": len(visits), "latest": max(visits, default=None)},
            "current": current_trader(ws.load_snapshot(d), items, load_item_paths(d), names, owned, now + offset),
            "has_names": bool(names.mastery or names.mods), "has_paths": (d / PATHS_FILE).exists(), "now": now + offset}


def update_all(d: Path, force: bool = False, verbose: bool = False) -> dict:
    """バロ情報を更新: 今回の品物を公式 World State から取得し、来ていれば来訪を記録する"""
    import wfportal_worldstate as ws
    result = {"worldstate": None, "recorded": None, "errors": []}
    try:
        snap = ws.sync(d, force=force, verbose=verbose)
        result["worldstate"] = "cached" if snap["cached"] else "fetched"
        now = time.time() + clock_offset(userdata.load_cycles(d))
        result["recorded"] = record_visit(d, snap, load_item_paths(d), now)
    except ws.WorldStateError as e:
        result["errors"].append(f"今回の品物(公式データ)を取得できませんでした: {e}")
    return result
