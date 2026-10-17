#!/usr/bin/env python3
"""wfportal_ui - wfportal をブラウザから操作するローカルUI (標準ライブラリのみ)

    python wfportal_ui.py              # http://127.0.0.1:8765 を開く
    python wfportal_ui.py --port 9000 --no-open --data-dir ./data

自分のPCの中だけで動き(127.0.0.1にだけ待ち受け)、データは wfportal.py と同じ場所を使います。
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser
from argparse import Namespace
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import wfportal as wf
import wfportal_builder as wb
import wfportal_ocr as ocr
import wfportal_worldstate as ws
import wfportal_baro as wbaro

HERE = Path(__file__).resolve().parent
JST = timezone(timedelta(hours=9))


# --------------------------------------------------------------------------
# データ層 (ファイルの更新時刻でキャッシュ)
# --------------------------------------------------------------------------

class Store:
    def __init__(self, d: Path):
        self.d = d
        self._cache: dict[str, tuple[int, object]] = {}
        self._lock = threading.Lock()

    def _cached(self, name: str, loader):
        f = self.d / name
        mtime = f.stat().st_mtime_ns if f.exists() else -1
        with self._lock:
            hit = self._cache.get(name)
            if hit and hit[0] == mtime:
                return hit[1]
            obj = loader() if mtime != -1 else None
            self._cache[name] = (mtime, obj)
            return obj

    def drops(self) -> wf.Drops | None:
        return self._cached("missionRewards.json", lambda: wf.Drops.load(self.d))

    def names(self) -> wf.Names:
        return self._cached("names.json", lambda: wf.Names.load(self.d)) or wf.Names()

    def names_info(self) -> dict:
        f = self.d / "names.json"
        if not f.exists():
            return {}
        j = json.loads(f.read_text(encoding="utf-8"))
        return {"updated": j.get("updated"), "source": j.get("source"), "mods": len(j.get("mods") or [])}

    def sources(self) -> wf.Sources | None:
        """敵・バウンティ等 (wfcd/ 以下の複数ファイル)。どれかが更新されたら読み直す"""
        folder = self.d / "wfcd"
        files = sorted(folder.glob("*.json")) if folder.exists() else []
        stamp = tuple((f.name, f.stat().st_mtime_ns) for f in files)
        with self._lock:
            hit = self._cache.get("@sources")
            if hit and hit[0] == stamp:
                return hit[1]
        obj = wf.Sources.load(self.d) if files else None
        with self._lock:
            self._cache["@sources"] = (stamp, obj)
        return obj

    def rivens(self) -> list | None:
        return self._cached("rivens.json", lambda: wf.load_rivens(self.d))

    def all_items(self) -> list[str]:
        drops, src = self.drops(), self.sources()
        key = (id(drops), id(src))
        with self._lock:
            hit = self._cache.get("@items")
            if hit and hit[0] == key:
                return hit[1]
        names = wf.all_item_names(drops, src) if drops else []
        with self._lock:
            self._cache["@items"] = (key, names)
        return names


class ApiError(Exception):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def need_drops(store: Store) -> wf.Drops:
    drops = store.drops()
    if drops is None:
        raise ApiError("データがありません。メニューの「データ更新」から取得してください。", 409)
    return drops


# --------------------------------------------------------------------------
# API 本体
# --------------------------------------------------------------------------

def _mtime(f: Path) -> str | None:
    return datetime.fromtimestamp(f.stat().st_mtime, JST).strftime("%Y-%m-%d %H:%M") if f.exists() else None


def status(store: Store) -> dict:
    drops, info, src, rivens = store.drops(), store.names_info(), store.sources(), store.rivens()
    f = store.d / "missionRewards.json"
    wfcd = sorted((store.d / "wfcd").glob("*.json")) if (store.d / "wfcd").exists() else []
    return {
        "has_drops": drops is not None,
        "has_names": bool(info),
        "drops_updated": _mtime(f) if drops else None,
        "names_updated": info.get("updated"),
        "names_source": info.get("source"),
        "counts": {"items": len(store.all_items()), "nodes": len(drops.node_order),
                   "sources": len(src.rows) if src else 0, "mods": info.get("mods", 0)} if drops else None,
        "extra_updated": max((_mtime(x) for x in wfcd), default=None),
        "extra_files": len(wfcd), "extra_total": len(wf.WFCD_EXTRA),
        "rivens_updated": _mtime(store.d / "rivens.json") if rivens else None,
        "rivens_count": len(rivens) if rivens else 0,
        "has_logo": wf.find_logos_dir(store.d) is not None,
        "version": wf.app_version(),
    }


def suggest_items(store: Store, q: str, materials_only: bool) -> list[dict]:
    need_drops(store)
    names, items = store.names(), store.all_items()
    if q.strip():
        cands = wf.pick_candidates(q, items, names, materials_only)
    else:
        cands = [n for n in items if not materials_only or names.is_resource(n)]
        cands.sort(key=lambda n: wf.norm(names.ja(n)))
    out = []
    for base in wf.group_candidates(cands, names).values():
        out.append({"key": base, "ja": names.ja(base), "en": base})
        if len(out) >= 80:
            break
    return out


def lookup_item(store: Store, key: str, events: bool) -> dict:
    drops, names = need_drops(store), store.names()
    rows = wf.find_sources(key, drops, store.sources(), names, events=events)
    if not rows:
        raise ApiError("該当する入手先がありません。", 404)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["cat"]] = counts.get(r["cat"], 0) + 1
    return {
        "ja": names.ja(key), "en": key, "total": len(rows),
        "cats": [{"key": c, "ja": wf.SOURCE_CATS[c], "n": counts[c]} for c in wf.SOURCE_CATS if c in counts],
        "rows": [{**r, "rarity_key": r["rarity"], "rarity": r["rarity_ja"]} for r in rows],
    }


def mods_list(store: Store) -> dict:
    names = store.names()
    if not names.mods:
        raise ApiError("MOD の情報がありません。「データ更新」で取得してください。", 409)
    rows = wf.mod_table(names, store.drops(), store.sources(), wf.load_owned(store.d))
    return {"mods": rows, "types": wf.MOD_TYPES, "cats": wf.SOURCE_CATS,
            "polarities": dict(wf.POLARITY_EN)}


def set_owned(store: Store, body: dict) -> dict:
    names = store.names()
    valid = {m["en"].lower() for m in names.mods}
    targets = body.get("en")
    targets = [targets] if isinstance(targets, str) else list(targets or [])
    owned = wf.load_owned(store.d)
    for en in targets:
        k = str(en).lower()
        if k not in valid:
            raise ApiError(f"MOD が見つかりません: {en}", 404)
        (owned.add if body.get("owned") else owned.discard)(k)
    wf.save_owned(store.d, owned)
    return {"owned": len(owned)}


def rivens_list(store: Store) -> dict:
    raw = store.rivens()
    if raw is None:
        raise ApiError("Riven 相場のデータがありません。「データ更新」で取得してください。", 409)
    return {"rows": wf.riven_table(raw, store.names()), "updated": _mtime(store.d / "rivens.json")}


def planets(store: Store) -> list[dict]:
    drops = need_drops(store)
    return [{"type": "planet", "key": p, "ja": wf.PLANETS_JA.get(p, p)} for p in drops.planets]


def suggest_areas(store: Store, q: str) -> list[dict]:
    drops = need_drops(store)
    if not q.strip():
        return planets(store)
    out = [p for p in planets(store) if wf.rank(q, [p["key"], p["ja"]]) is not None]
    for planet, node in drops.node_order:
        if wf.rank(q, [node]) is not None:
            out.append({"type": "node", "key": f"{planet}|{node}", "ja": node, "sub": wf.PLANETS_JA.get(planet, planet)})
    return out[:80]


def lookup_area(store: Store, kind: str, key: str, all_items: bool, events: bool) -> dict:
    drops, names = need_drops(store), store.names()
    if kind == "planet":
        targets = [(p, n) for p, n in drops.node_order if p == key]
        title = wf.PLANETS_JA.get(key, key)
    else:
        planet, _, node = key.partition("|")
        targets = [(planet, node)]
        title = f"{wf.PLANETS_JA.get(planet, planet)} / {node}"
    nodes = []
    for planet, node in targets:
        rows = [r for r in drops.rows if r[0] == planet and r[1] == node]
        if not rows or (rows[0][3] and not events):
            continue
        by_rot: dict[str, list] = {}
        for r in rows:
            if all_items or names.is_resource(r[5]):
                by_rot.setdefault(r[4], []).append(r)
        stages = [{"stage": wf.stage_label(rot), "items": [{
            "ja": names.ja(r[5]), "en": r[5], "chance": r[6], "rarity": wf.RARITY_JA.get(r[7], r[7]), "rarity_key": r[7],
        } for r in sorted(lst, key=lambda x: -x[6])]} for rot, lst in sorted(by_rot.items())]
        if stages or kind == "node":
            nodes.append({"planet": wf.PLANETS_JA.get(planet, planet), "node": node,
                          "mode": wf.MODES_JA.get(rows[0][2], rows[0][2]), "event": rows[0][3], "stages": stages})
    return {"title": title, "nodes": nodes}


def cycles(store: Store) -> dict:
    view = wf.cycle_rows(store.d)
    nowdt = datetime.fromtimestamp(view["now"], JST)  # PC の時計のずれは補正済み
    dr, wr = wf.next_daily_reset(nowdt), wf.next_weekly_reset(nowdt)
    return {**view,
            "daily": {"left": (dr - nowdt).total_seconds(), "at": dr.astimezone(JST).strftime("%m/%d %H:%M")},
            "weekly": {"left": (wr - nowdt).total_seconds(), "at": wr.astimezone(JST).strftime("%m/%d %H:%M")}}


def set_cycle(store: Store, body: dict) -> dict:
    key = str(body.get("key", ""))
    if key not in wf.CYCLES or not wf.CYCLES[key]["manual"]:
        raise ApiError("手動で合わせられるのは平原とオーブ峡谷です。")
    phase = wf.PHASE_ALIASES.get(str(body.get("phase", "")).lower())
    if phase not in [p[0] for p in wf.CYCLES[key]["phases"]]:
        raise ApiError("フェーズを選んでください。")
    try:
        remaining = wf.parse_remaining(str(body.get("remaining", "")))
    except ValueError:
        raise ApiError("残り時間は「45:30」または分の数字で入力してください。")
    try:
        wf.set_manual_cycle(store.d, key, phase, remaining)
    except ValueError as e:
        raise ApiError(str(e))
    return cycles(store)


def baro_list(store: Store) -> dict:
    return wbaro.baro_view(store.d, store.names())


def run_update_baro(store: Store) -> dict:
    """今回の品物を公式データから取得し、来ていれば来訪を記録する"""
    r = wbaro.update_all(store.d)
    if r["errors"]:
        raise ApiError(" / ".join(r["errors"]), 502)
    return {**baro_list(store), "update": r}


def set_baro_owned(store: Store, body: dict) -> dict:
    try:
        wbaro.set_manual_owned(store.d, str(body.get("name", "")), bool(body.get("owned")), store.names())
    except ValueError as e:
        raise ApiError(str(e))
    return {"ok": True}


def sync_worldstate(store: Store) -> dict:
    """公式データ(World State)で時刻合わせ。前回から 60 秒以内なら前回の結果を使う"""
    try:
        snap = ws.sync(store.d)
    except ws.WorldStateError as e:
        raise ApiError(f"公式データを取得できませんでした。基準時刻(または前回の同期)からの計算で表示しています。({e})", 502)
    return {**cycles(store), "synced": {"cached": snap["cached"], "offset": snap["offset"], "fetched_at": snap["fetched_at"]}}


def mastery_list(store: Store) -> dict:
    names = store.names()
    if not names.mastery:
        raise ApiError("マスター一覧のデータがありません。「データ更新」で取得してください。", 409)
    rows = wf.mastery_table(names, wf.load_mastered(store.d))
    return {"rows": rows, "cats": wf.MASTERY_CATS, "summary": wf.mastery_summary(rows)}


def set_mastered(store: Store, body: dict) -> dict:
    ids = body.get("ids")
    ids = [ids] if isinstance(ids, str) else list(ids or [])
    valid = {m["id"] for m in store.names().mastery}
    done = wf.load_mastered(store.d)
    for i in ids:
        if i not in valid:
            raise ApiError(f"見つかりません: {i}", 404)
        (done.add if body.get("done") else done.discard)(i)
    wf.save_mastered(store.d, done)
    rows = wf.mastery_table(store.names(), done)
    return {"summary": wf.mastery_summary(rows)}


def arcanes_list(store: Store) -> dict:
    names = store.names()
    if not names.arcane_list:
        raise ApiError("アルケインのデータがありません。「データ更新」で取得し直してください"
                       "(このページを追加する前に取得したデータには含まれていません)。", 409)
    rows = wf.arcane_table(names, wf.load_arcanes_owned(store.d), store.all_items())
    return {"rows": rows, "cats": wf.ARCANE_CATS, "summary": wf.arcane_summary(rows)}


def set_arcanes(store: Store, body: dict) -> dict:
    """body: {"en": 名前 or [名前], "owned": bool, "rank": int (省略可)}"""
    targets = body.get("en")
    targets = [targets] if isinstance(targets, str) else list(targets or [])
    rank = body.get("rank")
    if rank is not None and (isinstance(rank, bool) or not isinstance(rank, int)):
        raise ApiError(f"ランクが正しくありません: {rank}")
    names = store.names()
    owned = wf.load_arcanes_owned(store.d)
    try:
        wf.set_arcanes_owned(names, owned, targets, bool(body.get("owned")), rank, store.all_items())
    except ValueError as e:
        raise ApiError(str(e), 404 if isinstance(e, wf.ArcaneNotFound) else 400)
    wf.save_arcanes_owned(store.d, owned)
    return {"summary": wf.arcane_summary(wf.arcane_table(names, owned, store.all_items()))}


def dispo_list(store: Store) -> dict:
    names = store.names()
    if not names.dispo:
        raise ApiError("Riven 性質のデータがありません。「データ更新」で取得し直してください"
                       "(このページを追加する前に取得したデータには含まれていません)。", 409)
    return {"rows": wf.dispo_table(names, store.rivens()), "cats": wf.DISPO_CATS,
            "updated": (store.names_info().get("updated") or "")[:10]}


# --------------------------------------------------------------------------
# Tips (tips フォルダのメモを表示する。ファイルを直接編集すると内容が変わる)
# --------------------------------------------------------------------------

TIPS_KINDS = {".md": "md", ".markdown": "md", ".txt": "txt", ".csv": "csv"}
TIPS_MAX_BYTES = 2 * 1024 * 1024
_TIPS_PREFIX = re.compile(r"^\d+[\s._\-]*")


def tips_root() -> Path:
    return HERE / "tips"


def _natural(s: str) -> list:
    return [int(x) if x.isdigit() else x.lower() for x in re.split(r"(\d+)", s)]


def _tips_label(stem: str) -> str:
    """ファイル名・フォルダ名から表示名を作る(先頭の並び順用の数字は外す)"""
    return (_TIPS_PREFIX.sub("", stem) or stem).replace("_", " ").strip()


def _read_tip_text(p: Path) -> str:
    data = p.read_bytes()[:TIPS_MAX_BYTES]
    for enc in ("utf-8-sig", "cp932"):  # メモ帳は UTF-8、Excel の CSV は Shift_JIS(cp932)で保存されることが多い
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def _tip_title(p: Path, text: str | None = None) -> str:
    if TIPS_KINDS.get(p.suffix.lower()) == "md":
        try:
            for line in (text if text is not None else _read_tip_text(p)).splitlines()[:30]:
                if m := re.match(r"^#\s+(.+?)\s*#*\s*$", line):
                    return m.group(1)
        except OSError:
            pass
    return _tips_label(p.stem)


def tips_list(root: Path) -> dict:
    """目次: tips 直下のファイルと、1段下のフォルダ(目次の見出しになる)のファイル"""
    items = []
    if root.is_dir():
        files = [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in TIPS_KINDS
                 and not p.name.startswith((".", "~$")) and len(p.relative_to(root).parts) <= 2]
        files.sort(key=lambda p: [_natural(x) for x in p.relative_to(root).parts])
        for p in files:
            parts = p.relative_to(root).parts
            items.append({"path": "/".join(parts), "title": _tip_title(p),
                          "group": _tips_label(parts[0]) if len(parts) == 2 else "",
                          "kind": TIPS_KINDS[p.suffix.lower()]})
    return {"dir": str(root), "exists": root.is_dir(), "items": items}


def tip_path(root: Path, rel: str) -> Path | None:
    """tips フォルダの中にあるファイルだけを返す(../ などで外に出られないようにする)"""
    if not rel or "\x00" in rel:
        return None
    try:
        base = root.resolve()
        p = (base / rel).resolve()
    except (OSError, ValueError):
        return None
    return p if base in p.parents and p.is_file() else None


def tip_file(root: Path, rel: str) -> dict:
    p = tip_path(root, rel)
    if p is None or p.suffix.lower() not in TIPS_KINDS:
        raise ApiError("メモが見つかりません。目次を読み込み直してください。", 404)
    text = _read_tip_text(p)
    kind = TIPS_KINDS[p.suffix.lower()]
    out = {"path": rel, "title": _tip_title(p, text), "kind": kind, "updated": _mtime(p)}
    if kind == "csv":
        sample = text[:4096]
        delim = "\t" if sample.count("\t") > sample.count(",") else ","
        rows = [r for r in csv.reader(io.StringIO(text), delimiter=delim)]
        while rows and not any(c.strip() for c in rows[-1]):
            rows.pop()
        out["rows"] = rows
    else:
        out["text"] = text
    return out


def open_tips_folder(root: Path) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    try:
        if os.name == "nt":
            os.startfile(str(root))  # noqa: S606 (エクスプローラーで開く)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(root)])
        else:
            subprocess.Popen(["xdg-open", str(root)])
    except OSError as e:
        raise ApiError(f"フォルダを開けませんでした: {e}", 500)
    return {"dir": str(root)}


def sim_dispo_rows(store: Store) -> list[dict]:
    """シミュレータで武器の Riven の種類を決めるのに使う(Riven性質と同じ判定。相場の武器種を優先)"""
    names = store.names()
    return wf.dispo_table(names, store.rivens()) if names.dispo else []


def run_update_sim(store: Store) -> dict:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ok = wb.update_builder_data(store.d)
    return {"ok": ok, "log": buf.getvalue()}


def run_update_rivens(store: Store) -> dict:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ok = wf.update_rivens(store.d)
    return {"ok": ok, "log": buf.getvalue(), "status": status(store)}


def run_update(store: Store) -> dict:
    buf = io.StringIO()
    ok = True
    with contextlib.redirect_stdout(buf):
        try:
            wf.cmd_update(Namespace(data_dir=str(store.d)))
        except SystemExit as e:
            ok = False
            print(e.code if isinstance(e.code, str) else "更新に失敗しました。")
    return {"ok": ok, "log": buf.getvalue(), "status": status(store)}


def clean_build(body: dict) -> dict:
    name = str(body.get("name", "")).strip()
    if not name:
        raise ApiError("ビルド名を入力してください。")
    btype = body.get("type") if body.get("type") in wf.BUILD_TYPES else "other"
    try:
        forma = max(0, int(body.get("forma") or 0))
    except (TypeError, ValueError):
        raise ApiError("フォーマの数は数字で入力してください。")
    split = lambda v: [x.strip() for x in re.split(r"[\n,、]", "\n".join(v) if isinstance(v, list) else str(v or "")) if x.strip()]
    images = body.get("images") or []
    return {"name": name, "type": btype, "target": str(body.get("target", "")).strip(), "forma": forma,
            "mods": split(body.get("mods")), "arcanes": split(body.get("arcanes")),
            "tags": split(body.get("tags")), "note": str(body.get("note", "")).strip(),
            "images": [str(x) for x in images if isinstance(x, str) and wf.IMAGE_NAME_RE.match(x)] if isinstance(images, list) else []}


def save_build(store: Store, body: dict) -> list[dict]:
    entry = clean_build(body)
    builds = wf.load_builds(store.d)
    original = str(body.get("original_name") or "")
    same = lambda b, n: wf.norm(b["name"]) == wf.norm(n)
    if original:
        idx = next((i for i, b in enumerate(builds) if same(b, original)), None)
        if idx is None:
            raise ApiError("編集元のビルドが見つかりません。", 404)
        if not same(entry, original) and any(same(b, entry["name"]) for b in builds):
            raise ApiError("同じ名前のビルドがあります。")
        # 画像は「元のビルドに付いていたもの」だけ残せる。外されたものはファイルも消す
        before = builds[idx].get("images", [])
        entry["images"] = [x for x in entry["images"] if x in before]
        removed = [x for x in before if x not in entry["images"]]
        builds[idx] = entry
    else:
        if any(same(b, entry["name"]) for b in builds):
            raise ApiError("同じ名前のビルドがあります。")
        entry["images"], removed = [], []
        builds.append(entry)
    wf.save_builds(store.d, builds)
    wf.delete_build_images(store.d, removed)
    return builds


def add_build_image(store: Store, name: str, data: bytes) -> list[dict]:
    builds = wf.load_builds(store.d)
    b = next((x for x in builds if wf.norm(x["name"]) == wf.norm(name)), None)
    if b is None:
        raise ApiError("ビルドが見つかりません。", 404)
    if len(b.get("images", [])) >= 30:
        raise ApiError("画像は1つのビルドに30枚までです。")
    try:
        fname = wf.save_build_image(store.d, data)
    except ValueError as e:
        raise ApiError(str(e), 415)
    b.setdefault("images", []).append(fname)
    wf.save_builds(store.d, builds)
    return builds


def delete_build(store: Store, name: str) -> list[dict]:
    builds = wf.load_builds(store.d)
    keep = [b for b in builds if wf.norm(b["name"]) != wf.norm(name)]
    if len(keep) == len(builds):
        raise ApiError("ビルドが見つかりません。", 404)
    wf.save_builds(store.d, keep)
    for b in builds:
        if b not in keep:
            wf.delete_build_images(store.d, b.get("images", []))
    return keep


_ocr_info: dict | None = None
_ocr_lock = threading.Lock()


def ocr_info() -> dict:
    """Windows の文字認識が使えるか(初回だけ調べて覚えておく)"""
    global _ocr_info
    with _ocr_lock:
        if _ocr_info is None:
            try:
                langs = ocr.ocr_languages()
                _ocr_info = {"available": bool(langs), "languages": langs,
                             "english": any(x.lower().startswith("en") for x in langs),
                             "reason": "" if langs else "文字認識に使える言語がありません。Windows の設定で言語を追加してください。"}
            except ocr.OcrUnavailable as e:
                _ocr_info = {"available": False, "languages": [], "english": False, "reason": str(e)}
        return _ocr_info


def analyze_build_image(store: Store, image_name: str, data: bytes | None) -> dict:
    """保存済みの画像(image_name)か、送られてきた画像(data)を解析する"""
    info = ocr_info()
    if not info["available"]:
        raise ApiError(info["reason"] or "文字認識が使えません。", 501)
    names = store.names()
    if not names.mods:
        raise ApiError("MOD の情報がありません。「データ更新」で取得してください。", 409)
    if image_name:
        p = wf.build_image_path(store.d, image_name)
        if p is None:
            raise ApiError("画像が見つかりません。", 404)
        data = p.read_bytes()
    if not data or not wf.image_ext(data):
        raise ApiError("PNG / JPEG / GIF / WebP の画像を送ってください。", 415)
    try:
        raw = ocr.run_ocr_bytes(data, cache_dir=store.d / "ocr_cache")
    except ocr.OcrUnavailable as e:
        raise ApiError(str(e), 502)
    with store._lock:
        matcher = store._cache.get("@matcher")
        if not matcher or matcher[0] is not names:
            matcher = (names, ocr.build_matcher(names))
            store._cache["@matcher"] = matcher
    result = ocr.analyze(raw, names, matcher[1])
    result["has_items"] = bool(names.items)
    return result


def scan_mods(store: Store, data: bytes) -> dict:
    """ゲームの MOD 一覧画面(の画像)から MOD 名を読み取る。所持チェックを付けるかは画面側で決める"""
    info = ocr_info()
    if not info["available"]:
        raise ApiError(info["reason"] or "文字認識が使えません。", 501)
    names = store.names()
    if not names.mods:
        raise ApiError("MOD の情報がありません。「データ更新」で取得してください。", 409)
    if not data or not wf.image_ext(data):
        raise ApiError("PNG / JPEG / GIF / WebP の画像を送ってください。", 415)
    try:
        # 何度も読むので、英語だけ・拡大は控えめにして速さを優先する。結果は保存しない
        raw = ocr.run_ocr_bytes(data, cache_dir=None, langs="en-US", scale=1.5)
    except ocr.OcrUnavailable as e:
        raise ApiError(str(e), 502)
    with store._lock:
        cached = store._cache.get("@modmatcher")
        if not cached or cached[0] is not names:
            cached = (names, ocr.NameMatcher([("mod", m["en"], m) for m in names.mods]))
            store._cache["@modmatcher"] = cached
    result = ocr.analyze(raw, names, cached[1])
    owned = wf.load_owned(store.d)
    found, seen = [], set()
    for m in result["mods"]:
        k = m["en"].lower()
        if m["kind"] == "mod" and k not in seen:
            seen.add(k)
            found.append({"en": m["en"], "ja": m["ja"], "score": m["score"], "read": m["read"], "owned": k in owned})
    return {"found": found, "lines": len(result["lines"])}


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

TIPS_IMAGE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}


def make_handler(store: Store, tips_dir: Path | None = None):
    html_path = HERE / "web" / "wfportal_ui.html"
    sim_path = HERE / "web" / "wfportal_builder.html"
    tips = tips_dir or tips_root()

    class Handler(BaseHTTPRequestHandler):
        server_version = "wfportal"

        def log_message(self, fmt, *args):  # 静かにする
            pass

        # -- helpers
        def _send(self, code: int, body: bytes, ctype: str, cache: str = "no-store"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _guard(self) -> bool:
            """DNSリバインディング/他サイトからの操作を防ぐ"""
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
            if host not in ("127.0.0.1", "localhost"):
                self._json({"error": "forbidden"}, 403)
                return False
            origin = self.headers.get("Origin")
            if origin and urlparse(origin).netloc != self.headers.get("Host"):
                self._json({"error": "forbidden"}, 403)
                return False
            return True

        def _body(self) -> dict:
            if "application/json" not in (self.headers.get("Content-Type") or ""):
                raise ApiError("Content-Type は application/json にしてください。", 415)
            n = int(self.headers.get("Content-Length") or 0)
            if n > 1_000_000:
                raise ApiError("リクエストが大きすぎます。", 413)
            try:
                return json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError:
                raise ApiError("JSON を読み取れません。")

        def _raw_image(self) -> bytes:
            if not (self.headers.get("Content-Type") or "").startswith("image/"):
                raise ApiError("画像ファイルを送ってください。", 415)
            n = int(self.headers.get("Content-Length") or 0)
            if n > wf.IMAGE_MAX_BYTES:
                raise ApiError(f"画像が大きすぎます(上限 {wf.IMAGE_MAX_BYTES // 1024 // 1024}MB)。", 413)
            return self.rfile.read(n)

        def _dispatch(self, method: str):
            if not self._guard():
                return
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            flag = lambda k, default=False: q.get(k, "1" if default else "0") == "1"
            try:
                if method == "GET" and u.path in ("/builder", "/simulator"):
                    # シミュレータ(メニューの「シミュレータ」の中に表示する。単独のページとしても開ける)
                    return self._send(200, sim_path.read_bytes(), "text/html; charset=utf-8")
                if method == "GET" and u.path in ("/", "/index.html"):
                    return self._send(200, html_path.read_bytes(), "text/html; charset=utf-8")
                if method == "GET" and u.path == "/logo.png":
                    # 各自の PC に取得した公式ファンキットのロゴ(同梱はしていない)
                    ld = wf.find_logos_dir(store.d)
                    if ld is None:
                        raise ApiError("ロゴ素材が未取得です。", 404)
                    return self._send(200, (ld / "LotusFlower.png").read_bytes(), "image/png", "private, max-age=86400")
                if method == "GET" and u.path.startswith("/api/build-image/"):
                    p = wf.build_image_path(store.d, u.path.rsplit("/", 1)[1])
                    if p is None:
                        raise ApiError("画像が見つかりません。", 404)
                    # ファイル名は毎回ちがう乱数なので、長くキャッシュしてよい
                    return self._send(200, p.read_bytes(), wf.IMAGE_MIME[p.suffix[1:]], "private, max-age=31536000, immutable")
                if method == "GET" and u.path.startswith("/tips/"):
                    # Tips のメモに貼った画像 (tips フォルダの中の画像だけ)
                    p = tip_path(tips, unquote(u.path[len("/tips/"):]))
                    if p is None or p.suffix.lower() not in TIPS_IMAGE_MIME:
                        raise ApiError("画像が見つかりません。", 404)
                    return self._send(200, p.read_bytes(), TIPS_IMAGE_MIME[p.suffix.lower()])
                if method == "GET":
                    routes = {
                        "/api/status": lambda: status(store),
                        "/api/suggest/item": lambda: suggest_items(store, q.get("q", ""), flag("materials", True)),
                        "/api/item": lambda: lookup_item(store, q.get("key", ""), flag("events")),
                        "/api/suggest/area": lambda: suggest_areas(store, q.get("q", "")),
                        "/api/area": lambda: lookup_area(store, q.get("type", "planet"), q.get("key", ""), flag("all"), flag("events")),
                        "/api/cycles": lambda: cycles(store),
                        "/api/builds": lambda: {"builds": wf.load_builds(store.d), "types": wf.BUILD_TYPES,
                                                "arcanes": store.names().arcanes},
                        "/api/mods": lambda: mods_list(store),
                        "/api/rivens": lambda: rivens_list(store),
                        "/api/ocr-info": ocr_info,
                        "/api/mastery": lambda: mastery_list(store),
                        "/api/dispo": lambda: dispo_list(store),
                        "/api/arcanes": lambda: arcanes_list(store),
                        "/api/baro": lambda: baro_list(store),
                        "/api/tips": lambda: tips_list(tips),
                        "/api/tips/file": lambda: tip_file(tips, q.get("path", "")),
                        "/api/builder/data": lambda: wb.api_data(store.d, sim_dispo_rows(store)),
                    }
                    if u.path in routes:
                        return self._json(routes[u.path]())
                elif method == "POST":
                    if u.path == "/api/update":
                        self._body()
                        return self._json(run_update(store))
                    if u.path == "/api/cycles":
                        return self._json(set_cycle(store, self._body()))
                    if u.path == "/api/cycles/sync":
                        self._body()
                        return self._json(sync_worldstate(store))
                    if u.path == "/api/baro/update":
                        self._body()
                        return self._json(run_update_baro(store))
                    if u.path == "/api/baro/owned":
                        return self._json(set_baro_owned(store, self._body()))
                    if u.path == "/api/builds":
                        return self._json({"builds": save_build(store, self._body())})
                    if u.path == "/api/build-image":
                        return self._json({"builds": add_build_image(store, q.get("name", ""), self._raw_image())})
                    if u.path == "/api/build-analyze":
                        image = q.get("image", "")
                        return self._json(analyze_build_image(store, image, None if image else self._raw_image()))
                    if u.path == "/api/mastery":
                        return self._json(set_mastered(store, self._body()))
                    if u.path == "/api/arcanes/owned":
                        return self._json(set_arcanes(store, self._body()))
                    if u.path == "/api/update-rivens":
                        self._body()
                        return self._json(run_update_rivens(store))
                    if u.path == "/api/mods/scan":
                        return self._json(scan_mods(store, self._raw_image()))
                    if u.path == "/api/mods/owned":
                        return self._json(set_owned(store, self._body()))
                    if u.path == "/api/builder/frame":
                        return self._json(wb.api_frame(store.d, self._body()))
                    if u.path == "/api/builder/weapon":
                        return self._json(wb.api_weapon(store.d, self._body(), sim_dispo_rows(store)))
                    if u.path == "/api/builder/riven":
                        return self._json(wb.api_riven(store.d, self._body(), sim_dispo_rows(store)))
                    if u.path == "/api/builder/update":
                        self._body()
                        return self._json(run_update_sim(store))
                    if u.path == "/api/tips/open":
                        self._body()
                        return self._json(open_tips_folder(tips))
                elif method == "DELETE" and u.path == "/api/builds":
                    return self._json({"builds": delete_build(store, q.get("name", ""))})
                self._json({"error": "not found"}, 404)
            except (ApiError, wb.BuilderError) as e:
                self._json({"error": str(e)}, e.status)
            except (BrokenPipeError, ConnectionResetError):
                pass  # ブラウザ側が先に接続を閉じた
            except Exception as e:  # noqa: BLE001
                print(f"[エラー] {method} {self.path}: {e!r}")  # 起動した画面にも残す
                self._json({"error": f"内部エラー: {e}"}, 500)

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def do_DELETE(self):
            self._dispatch("DELETE")

    return Handler


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="wfportal ローカルUI")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--data-dir")
    ap.add_argument("--no-open", action="store_true", help="ブラウザを自動で開かない")
    args = ap.parse_args(argv)

    store = Store(wf.data_dir(args.data_dir))
    server = None
    for port in range(args.port, args.port + 10):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(store))
            break
        except OSError:
            continue
    if server is None:
        raise SystemExit(f"ポート {args.port}〜{args.port + 9} が使用中です。--port で別の番号を指定してください。")
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Warframe Portal v{wf.app_version()}: {url}  (終了は Ctrl+C)\nデータ: {store.d}")
    if not args.no_open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n終了します。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
