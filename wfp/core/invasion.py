"""侵略サイクル: 今の侵略の一覧と、侵略で獲得できる武器パーツの収集表

- 侵略の一覧は World State の抜き出し結果(worldstate.json の invasions)から作る。取得は画面の「更新」のときだけ
  (World State の取得・保存は wfportal_worldstate。層のルールにより、ここへは API から値で渡す)
- 収集表は同梱の data/invasion/parts.json(手編集)。報酬との照合は名前ではなく内部パスで行う
  (名前の綴りや辞書の有無に左右されないため)。取得済みは利用者のデータ invasion_parts.json にパスで保存する
- 文字は値(陣営・パーツの種類のキー)で返し、画面の I18N で整形する。武器名は英語のまま
"""
from __future__ import annotations

import re
from pathlib import Path

from wfp.core.common import (INVASION_INFESTED, INVASION_PART_KINDS, INVASION_PARTS_FILE, INVASION_WEAPON_PART_PREFIX,
                             PLANETS_JA)
from wfp.core.names import Names
from wfp.store import appdata, gamedata, userdata


# --------------------------------------------------------------------------
# 同梱の収集表(data/invasion/parts.json)
# --------------------------------------------------------------------------

def check_parts(j: object) -> list[dict] | None:
    """収集表の中身を検査して [{name, parts: [{kind, path, aliases}]}] を返す。形が違えば None

    武器名・パス(別名を含む)は重複不可。種類は INVASION_PART_KINDS のどれか。並びはファイルの書き順のまま
    """
    rows = j.get("weapons") if isinstance(j, dict) else None
    if not isinstance(rows, list) or not rows:
        return None
    out, names, paths = [], set(), set()
    for w in rows:
        if not isinstance(w, dict) or not isinstance(w.get("name"), str) or not w["name"].strip():
            return None
        name = w["name"].strip()
        parts = w.get("parts")
        if name in names or not isinstance(parts, list) or not parts:
            return None
        names.add(name)
        got = []
        for p in parts:
            if not isinstance(p, dict) or p.get("kind") not in INVASION_PART_KINDS:
                return None
            aliases = p.get("aliases", [])
            if not isinstance(aliases, list):
                return None
            for path in [p.get("path"), *aliases]:
                if not isinstance(path, str) or not path.startswith("/") or path in paths:
                    return None
                paths.add(path)
            got.append({"kind": p["kind"], "path": p["path"], "aliases": list(aliases)})
        out.append({"name": name, "parts": got})
    return out


def load_parts(src: Path | None = None) -> list[dict] | None:
    """同梱の収集表。読めない・形が違えば None"""
    return check_parts(appdata.read_invasion(INVASION_PARTS_FILE, src))


def part_index(weapons: list[dict]) -> dict[str, dict]:
    """{パス(別名も): {weapon, kind, path(本来のパス)}}"""
    index = {}
    for w in weapons:
        for p in w["parts"]:
            hit = {"weapon": w["name"], "kind": p["kind"], "path": p["path"]}
            for path in [p["path"], *p["aliases"]]:
                index[path] = hit
    return index


# --------------------------------------------------------------------------
# ノード名(公式 Public Export の ExportRegions から「データ更新」で作る)
# --------------------------------------------------------------------------

def regions_from_exports(en_doc: dict, ja_doc: dict) -> dict:
    """{ノードの内部名: {node, node_ja, planet, planet_ja}}。日本語が無ければ英語(惑星は PLANETS_JA も見る)"""
    def rows(doc):
        items = doc.get("ExportRegions") if isinstance(doc, dict) else None
        return {it["uniqueName"]: it for it in items or []
                if isinstance(it, dict) and isinstance(it.get("uniqueName"), str) and isinstance(it.get("name"), str)}
    en, ja = rows(en_doc), rows(ja_doc)
    out = {}
    for uid, it in en.items():
        j = ja.get(uid, {})
        planet = it.get("systemName") if isinstance(it.get("systemName"), str) else ""
        planet_ja = j.get("systemName") if isinstance(j.get("systemName"), str) else ""
        out[uid] = {"node": it["name"], "node_ja": j.get("name") or it["name"],
                    "planet": planet, "planet_ja": planet_ja or PLANETS_JA.get(planet, planet)}
    return out


# --------------------------------------------------------------------------
# 侵略の一覧
# --------------------------------------------------------------------------

def invasion_progress(count, goal, infested: bool) -> float | None:
    """進み具合(0〜1)。通常は攻め側の取り分 (Goal + Count) / (2 × Goal)、
    感染体が攻め側のときは Count が 0 から -Goal へ減るので -Count / Goal。読めなければ None"""
    if not isinstance(count, (int, float)) or not isinstance(goal, (int, float)) or goal <= 0:
        return None
    v = -count / goal if infested else (goal + count) / (2 * goal)
    return min(1.0, max(0.0, v))


def is_finished(inv: dict) -> bool:
    """完了済みか(Completed のほか、|Count| が Goal に届いたもの)"""
    if inv.get("completed"):
        return True
    count, goal = inv.get("count"), inv.get("goal")
    return isinstance(count, (int, float)) and isinstance(goal, (int, float)) and goal > 0 and abs(count) >= goal


def path_name(path: str, paths: dict) -> str:
    """内部パス → 英語名(item_paths.json)。無ければパスの最後の部分を読みやすくする
    (wfportal_baro の path_name と同じ考え方。層のルールで baro は使えないため、ここに持つ)"""
    for p in (path, path.replace("/StoreItems/", "/", 1)):
        if isinstance(paths.get(p), str):
            return paths[p]
    last = path.rstrip("/").rsplit("/", 1)[-1]
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", last) or path


def _reward(r: dict, paths: dict, names: Names, index: dict, owned: set[str]) -> dict:
    name = path_name(r["path"], paths)
    hit = index.get(r["path"])
    ja = names.ja(name)
    row = {"path": r["path"], "count": r["count"], "name": name, "name_ja": ja if ja != name else None, "part": None}
    if hit:
        row["part"] = {"weapon": hit["weapon"], "kind": hit["kind"], "owned": hit["path"] in owned}
    return row


def _region(node: str, regions: dict) -> dict:
    r = regions.get(node)
    if not isinstance(r, dict):
        return {"node_name": node, "node_ja": node, "planet": "", "planet_ja": ""}
    return {"node_name": r.get("node") or node, "node_ja": r.get("node_ja") or r.get("node") or node,
            "planet": r.get("planet") or "", "planet_ja": r.get("planet_ja") or r.get("planet") or ""}


def build_view(snap: dict | None, paths: dict, names: Names, regions: dict, owned: set[str],
               weapons: list[dict] | None) -> dict:
    """表示用データ(ファイルに触らない)。

    snap: World State の抜き出し結果(無ければ None)。invasions が無い古い保存なら needs_sync
    weapons: 同梱の収集表(読めなければ None → parts_ok: False。侵略の一覧はそのまま出す)
    """
    index = part_index(weapons or [])
    raw = snap.get("invasions") if isinstance(snap, dict) else None
    rows, active, unknown = [], set(), {}
    for inv in raw if isinstance(raw, list) else []:
        if not isinstance(inv, dict) or is_finished(inv):
            continue
        infested = inv.get("attacker") == INVASION_INFESTED
        row = {"id": inv.get("id") or "", "node": inv.get("node") or "", **_region(inv.get("node") or "", regions),
               "attacker": inv.get("attacker") or "", "defender": inv.get("defender") or "", "infested": infested,
               "progress": invasion_progress(inv.get("count"), inv.get("goal"), infested)}
        for side in ("attacker_reward", "defender_reward"):
            row[side] = [_reward(r, paths, names, index, owned) for r in inv.get(side) or []
                         if isinstance(r, dict) and isinstance(r.get("path"), str)]
            for r in row[side]:
                if r["path"] in index:
                    active.add(index[r["path"]]["path"])
                elif r["path"].startswith(INVASION_WEAPON_PART_PREFIX):
                    unknown.setdefault(r["path"], {"path": r["path"], "name": r["name"]})
        rows.append(row)
    cards = []
    for w in weapons or []:
        parts = [{"kind": p["kind"], "path": p["path"], "owned": p["path"] in owned, "active": p["path"] in active}
                 for p in w["parts"]]
        cards.append({"name": w["name"], "parts": parts, "owned": sum(p["owned"] for p in parts), "total": len(parts)})
    return {"ok": True, "has_snapshot": isinstance(snap, dict), "needs_sync": isinstance(snap, dict) and raw is None,
            "fetched_at": snap.get("fetched_at") if isinstance(snap, dict) else None,
            "regions_ok": bool(regions), "invasions": rows,
            "parts_ok": weapons is not None, "weapons": cards, "unknown_parts": list(unknown.values())}


def invasion_view(d: Path, snap: dict | None, paths: dict, names: Names, src: Path | None = None) -> dict:
    """画面用。収集表・ノード名・取得済みはここで読む(src: data/invasion の場所。テスト用)"""
    return build_view(snap, paths, names, gamedata.read_regions(d), userdata.load_invasion_parts(d), load_parts(src))


def set_invasion_part(d: Path, path: str, owned: bool, src: Path | None = None) -> set[str]:
    """パーツの取得済みを付け外しする(path は収集表のパス。別名でもよい)。一覧に無ければ ValueError"""
    weapons = load_parts(src)
    if weapons is None:
        raise ValueError("獲得パーツの一覧(同梱データ)が読めません。")
    hit = part_index(weapons).get(path)
    if hit is None:
        raise ValueError("一覧に無いパーツです。")
    done = userdata.load_invasion_parts(d)
    if owned:
        done.add(hit["path"])
    else:
        done.discard(hit["path"])
    userdata.save_invasion_parts(d, done)
    return done
