"""クエスト一覧(完了のチェックと、前提条件による導線)

- 一覧は「同梱の data/quests/flow.json に書いたクエスト・ジャンクション」+「Export(names.json の quests)にあって flow.json に無いクエスト」
  - flow.json の分は Export に無くても消さない(Prelude to War など、Export に無いクエストもここに書く)
  - Export にしか無いクエストは種類「その他」・前提なしで出す(flow: False。前提をまだ書いていない印)
  - 名前は Export を優先(公式の日本語名)し、無ければ flow.json の en / ja
  - flow.json のクエストに covers(Export の id のリスト)を書くと、その Export のクエストは1件にまとめて出す
    (例: Prologue to Tau = Lua・Vessel・Eris Mortem の3章)。まとめたほうの id を前提に書かない(テストで検査する)
- 前提(requires)の書き方(flow.json):
    {"quest": id} / {"junction": キー}      … 完了のチェックが必要(足りなければ完了にできない)
    {"any": [上の2つの形, ...]}              … どれか1つが完了していればよい
    {"mr": 数}                              … マスタリーランク(案内だけ。チェックはしない)
    {"note": {"ja": 文, "en": 文}}          … そのほかの条件(案内だけ)
  形の合わない前提・一覧に無い id を指す前提は黙って無いものとして扱う(同梱データはテストで検査する)
- 完了にできるのは、チェックの必要な前提が全部完了しているものだけ。外せるのは、ほかの完了済みの前提になっていないものだけ
"""
from __future__ import annotations

import re
from pathlib import Path

from wfp.core.errors import TextError
from wfp.core.i18n import name_txt, txt
from wfp.core.const import QUEST_CATS, QUEST_FLOW_FILE, QUEST_JUNCTION_PREFIX
from wfp.core.names import Names
from wfp.store import appdata

_JUNCTION_KEY = re.compile(r"^[a-z0-9_-]+$")
_FLOW_CATS = ("main", "side", "warframe")  # flow.json のクエストに書ける種類(junction・other は自動で付く)


class QuestNotFound(TextError):
    """一覧に無い id"""


class QuestLocked(TextError):
    """前提が完了していない(完了にできない)、またはほかの完了済みの前提になっている(外せない)"""


def junction_id(key: str) -> str:
    return QUEST_JUNCTION_PREFIX + key


def _note(v: object) -> dict | None:
    if not isinstance(v, dict):
        return None
    by = {c: s.strip() for c, s in v.items() if isinstance(c, str) and isinstance(s, str) and s.strip()}
    return by if "ja" in by and "en" in by else None


def _node_req(r: object) -> str | None:
    """{"quest": id} / {"junction": キー} を id にする。形が違えば None"""
    if not isinstance(r, dict) or len(r) != 1:
        return None
    if isinstance(r.get("quest"), str) and r["quest"].strip():
        return r["quest"].strip()
    if isinstance(r.get("junction"), str) and _JUNCTION_KEY.match(r["junction"]):
        return junction_id(r["junction"])
    return None


def check_requires(raw: object) -> list[dict]:
    """前提のリストを検査してそろえる: {"type": "node", "id"} / {"type": "any", "of": [id]} / {"type": "mr", "n"} / {"type": "note", "text"}"""
    out = []
    for r in raw if isinstance(raw, list) else []:
        node = _node_req(r)
        if node:
            out.append({"type": "node", "id": node})
        elif isinstance(r, dict) and len(r) == 1 and isinstance(r.get("any"), list):
            ids = [i for i in (_node_req(x) for x in r["any"]) if i]
            if ids:
                out.append({"type": "any", "of": ids})
        elif isinstance(r, dict) and len(r) == 1 and isinstance(r.get("mr"), int) and not isinstance(r["mr"], bool) and r["mr"] > 0:
            out.append({"type": "mr", "n": r["mr"]})
        elif isinstance(r, dict) and len(r) == 1 and _note(r.get("note")):
            out.append({"type": "note", "text": {"l": _note(r["note"])}})
    return out


def check_flow(raw: object) -> list[dict]:
    """flow.json の中身を検査して、ジャンクション → クエストの順(ファイルの並び)の項目にする。形の合わない項目は黙って飛ばす

    項目: {id, kind: "quest" | "junction", cat, en, ja(クエスト), covers(クエスト), from, to(ジャンクション), requires, verified}
    """
    out: list[dict] = []
    raw = raw if isinstance(raw, dict) else {}
    junctions, quests = raw.get("junctions"), raw.get("quests")
    for key, v in (junctions.items() if isinstance(junctions, dict) else []):
        if not _JUNCTION_KEY.match(key) or not isinstance(v, dict):
            continue
        fr, to = v.get("from"), v.get("to")
        if not isinstance(fr, str) or not fr.strip() or not isinstance(to, str) or not to.strip():
            continue
        out.append({"id": junction_id(key), "kind": "junction", "cat": "junction", "from": fr.strip(), "to": to.strip(),
                    "requires": check_requires(v.get("requires")), "verified": v.get("verified") is not False})
    for qid, v in (quests.items() if isinstance(quests, dict) else []):
        if not qid.strip() or qid.startswith(QUEST_JUNCTION_PREFIX) or not isinstance(v, dict):
            continue
        en, cat = v.get("en"), v.get("cat")
        if not isinstance(en, str) or not en.strip() or cat not in _FLOW_CATS:
            continue
        ja = v.get("ja") if isinstance(v.get("ja"), str) and v["ja"].strip() else en
        raw_covers = v.get("covers") if isinstance(v.get("covers"), list) else []
        covers = [c.strip() for c in raw_covers if isinstance(c, str) and c.strip()]
        out.append({"id": qid.strip(), "kind": "quest", "cat": cat, "en": en.strip(), "ja": ja.strip(), "covers": covers,
                    "requires": check_requires(v.get("requires")), "verified": v.get("verified") is not False})
    return out


def quest_items(names: Names, src: Path | None = None) -> list[dict]:
    """一覧の全項目(並びは種類 → flow.json の並び → Export にしか無いものは英名順)。前提は一覧にある id だけを残す"""
    flow = check_flow(appdata.read_quests(QUEST_FLOW_FILE, src))
    exported = {q["id"]: q for q in names.quests if isinstance(q, dict) and isinstance(q.get("id"), str)}
    covered = {c for it in flow if it["kind"] == "quest" for c in it["covers"]}  # 1件にまとめて出す Export のクエスト
    items, seen = [], set()
    for it in flow:
        if it["id"] in seen:
            continue
        seen.add(it["id"])
        ex = exported.get(it["id"])
        if ex:  # 名前は公式のもの(Export)を優先
            it = {**it, "en": ex.get("en") or it["en"], "ja": ex.get("ja") or ex.get("en") or it["ja"]}
        items.append({**it, "flow": True})
    for q in exported.values():
        if q["id"] not in seen and q["id"] not in covered and isinstance(q.get("en"), str):
            seen.add(q["id"])
            items.append({"id": q["id"], "kind": "quest", "cat": "other", "en": q["en"], "ja": q.get("ja") or q["en"],
                          "requires": [], "verified": False, "flow": False})
    for it in items:
        reqs = []
        for r in it["requires"]:
            if r["type"] == "node" and r["id"] not in seen:
                continue
            if r["type"] == "any":
                of = [i for i in r["of"] if i in seen]
                if not of:
                    continue
                r = {**r, "of": of}
            reqs.append(r)
        it["requires"] = reqs
    order = {c: i for i, c in enumerate(QUEST_CATS)}
    return [it for _i, it in sorted(enumerate(items), key=lambda p: (order[p[1]["cat"]], p[1]["en"].lower() if not p[1]["flow"] else "", p[0]))]


def unmet(item: dict, done: set[str]) -> list[dict]:
    """チェックの必要な前提のうち、完了していないもの(node / any の形のまま)"""
    out = []
    for r in item["requires"]:
        if r["type"] == "node" and r["id"] not in done:
            out.append(r)
        elif r["type"] == "any" and not any(i in done for i in r["of"]):
            out.append(r)
    return out


def _req_ids(reqs: list[dict]) -> list[str]:
    ids: list[str] = []
    for r in reqs:
        for i in ([r["id"]] if r["type"] == "node" else r["of"] if r["type"] == "any" else []):
            if i not in ids:
                ids.append(i)
    return ids


def route(items: list[dict], done: set[str], target: str) -> list[str]:
    """target を完了にするまでに必要な、未完了の項目の id(前提から順に。target 自身は含まない)。
    「どれか1つ」の前提は、並びで先に書いたほうをたどる。前提の輪があっても止まらない(輪の先はたどらない)"""
    by_id = {it["id"]: it for it in items}
    out: list[str] = []
    visiting: set[str] = set()

    def visit(i: str) -> None:
        if i in done or i in out or i in visiting or i not in by_id:
            return
        visiting.add(i)
        for r in unmet(by_id[i], done):
            visit(r["id"] if r["type"] == "node" else r["of"][0])
        visiting.discard(i)
        out.append(i)

    visit(target)
    return [i for i in out if i != target]


def quest_table(names: Names, done: set[str], src: Path | None = None) -> list[dict]:
    """状態つきの一覧。種類・状態はキーのまま(表示名は画面 / CLI で付ける)

    行: 項目 + {done, state: done / ready / locked, missing: 未完了の前提の id, route: 完了までに必要な未完了の項目の id(前提から順)}
    完了済みでも前提が欠けていれば missing に出る(flow.json を後から直したときなど)
    """
    items = quest_items(names, src)
    rows = []
    for it in items:
        miss = _req_ids(unmet(it, done))
        is_done = it["id"] in done
        rows.append({**it, "done": is_done, "state": "done" if is_done else "locked" if miss else "ready",
                     "missing": miss, "route": [] if is_done or not miss else route(items, done, it["id"])})
    return rows


def quest_summary(rows: list[dict]) -> dict:
    out = {c: {"total": 0, "done": 0, "ready": 0} for c in QUEST_CATS}
    for r in rows:
        out[r["cat"]]["total"] += 1
        out[r["cat"]]["done"] += r["done"]
        out[r["cat"]]["ready"] += r["state"] == "ready"
    out["all"] = {k: sum(v[k] for v in list(out.values())) for k in ("total", "done", "ready")}
    return out


def item_name(it: dict) -> dict:
    """項目の名前のテキスト指定(クエストは en / ja、ジャンクションは「<行き先>ジャンクション」)"""
    if it["kind"] == "junction":
        return txt("quest.junction", to=name_txt("planet.", it["to"]))
    return {"l": {"en": it["en"], "ja": it["ja"]}}


def set_quests_done(items: list[dict], done: set[str], ids: list[str], is_done: bool) -> set[str]:
    """完了の印を付ける / 外した新しい集合を返す(done は変えない)。

    付けるとき: 一緒に付けるものも含めて、チェックの必要な前提が全部完了していること(足りなければ QuestLocked)
    外すとき: 外したことで前提が欠ける完了済みの項目が無いこと(あれば QuestLocked。もともと欠けていたものは問わない)
    """
    by_id = {it["id"]: it for it in items}
    for i in ids:
        if i not in by_id:
            raise QuestNotFound(txt("err.quest.unknown", id=str(i)))
    if is_done:
        new = done | set(ids)
        for i in ids:
            miss = _req_ids(unmet(by_id[i], new))
            if miss:
                raise QuestLocked(txt("err.quest.locked", name=item_name(by_id[i]), need=[item_name(by_id[m]) for m in miss]))
        return new
    new = done - set(ids)
    blocked = [it for it in items if it["id"] in new and len(unmet(it, new)) > len(unmet(it, done))]
    if blocked:
        names_ = [item_name(by_id[i]) for i in ids if any(i in _req_ids(unmet(b, new)) for b in blocked)]
        raise QuestLocked(txt("err.quest.needed", name=names_, by=[item_name(b) for b in blocked]))
    return new
