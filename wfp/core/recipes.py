"""要求素材集: 公式 Public Export の ExportRecipes から、作るのに要る素材を部品ごとの入れ子にする(純粋な処理)

- データ更新で make_recipes が recipes.json の中身を作る(設計図と、出てくる内部パスの英名だけ)
- 読むときは check_recipes で形を確かめて Recipes にする
- 部品(内部パスが RECIPE_PART_PREFIXES のどれかで始まり、設計図があるもの。例: Rhino のニューロティック)は下に開き、
  それ以外(素材・Forma・素材に使う武器など)は末端の素材として出す。開く深さは RECIPE_MAX_DEPTH まで・同じ道で同じものは開かない
"""
from __future__ import annotations

import math
import re
from typing import Callable

from wfp.core.const import MASTERY_CATS, RECIPE_EXPORT, RECIPE_MAX_DEPTH, RECIPE_PART_PREFIXES, RECIPE_SOURCE_LAST_MODES
from wfp.core.i18n import name_txt
from wfp.core.names import Names
from wfp.core.text import norm
from wfp.core.common import rank


_TAG = re.compile(r"^<[^>]+>\s*")  # 名前の頭の印(例: "<ARCHWING> Odonata")


def _int(v: object, default: int = 0) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else default


def make_recipes(en_docs: list[dict], source: str, updated: str) -> dict:
    """recipes.json の中身(データ更新で保存する)。

    recipes = [{result: できる物の内部パス, bp: 設計図の内部パス, credits: クレジット, time: 作成時間(秒), num: できる数,
    parts: [{path: 素材の内部パス, count: 数}]}](同じ素材が2行あれば1行にまとめて足す。例: Akimbo の武器2丁)、
    names = {内部パス: 英名}(recipes に出てくるものだけ)
    """
    all_names: dict[str, str] = {}
    raw_recipes: list = []
    for doc in en_docs:
        for key, val in doc.items():
            if not isinstance(val, list):
                continue
            if key == RECIPE_EXPORT:
                raw_recipes.extend(val)
                continue
            for it in val:
                if isinstance(it, dict) and isinstance(it.get("uniqueName"), str) and isinstance(it.get("name"), str):
                    name = _TAG.sub("", it["name"]).strip()
                    if name:
                        all_names.setdefault(it["uniqueName"], name)
    recipes, used = [], set()
    for it in raw_recipes:
        if not isinstance(it, dict) or not isinstance(it.get("resultType"), str) or not isinstance(it.get("uniqueName"), str):
            continue
        parts: dict[str, int] = {}
        for ing in it.get("ingredients") or []:
            if isinstance(ing, dict) and isinstance(ing.get("ItemType"), str) and _int(ing.get("ItemCount")) > 0:
                parts[ing["ItemType"]] = parts.get(ing["ItemType"], 0) + ing["ItemCount"]
        if not parts:
            continue
        recipes.append({"result": it["resultType"], "bp": it["uniqueName"], "credits": _int(it.get("buildPrice")),
                        "time": _int(it.get("buildTime")), "num": _int(it.get("num"), 1) or 1,
                        "parts": [{"path": p, "count": n} for p, n in parts.items()]})
        used.update([it["resultType"], *parts])
    names = {p: all_names[p] for p in sorted(used) if p in all_names}
    return {"source": source, "updated": updated, "recipes": recipes, "names": names}


def check_recipes(raw: object) -> "Recipes":
    """recipes.json の中身を確かめて Recipes にする。形の悪い行は黙って外す(無い・壊れていれば空)"""
    raw = raw if isinstance(raw, dict) else {}
    names = {k: v for k, v in (raw.get("names") or {}).items() if isinstance(k, str) and isinstance(v, str)} \
        if isinstance(raw.get("names"), dict) else {}
    rows = []
    for r in raw.get("recipes") or [] if isinstance(raw.get("recipes"), list) else []:
        if not isinstance(r, dict) or not isinstance(r.get("result"), str) or not isinstance(r.get("parts"), list):
            continue
        parts = [{"path": p["path"], "count": p["count"]} for p in r["parts"]
                 if isinstance(p, dict) and isinstance(p.get("path"), str) and _int(p.get("count")) > 0]
        if parts:
            rows.append({"result": r["result"], "bp": r.get("bp") if isinstance(r.get("bp"), str) else "",
                         "credits": _int(r.get("credits")), "time": _int(r.get("time")), "num": _int(r.get("num"), 1) or 1,
                         "parts": parts})
    return Recipes(rows, names, raw.get("updated") if isinstance(raw.get("updated"), str) else "")


class Recipes:
    """設計図の一覧。by_result = {できる物の内部パス: [設計図…]}(作り方が2通り以上あるものは Export の並び)"""

    def __init__(self, rows: list[dict] | None = None, names: dict[str, str] | None = None, updated: str = ""):
        self.names = names or {}
        self.updated = updated
        self.by_result: dict[str, list[dict]] = {}
        for r in rows or []:
            self.by_result.setdefault(r["result"], []).append(r)

    def __bool__(self) -> bool:
        return bool(self.by_result)

    def name(self, path: str) -> str:
        """内部パスの英名。名前が無ければ内部パスの最後の部分"""
        return self.names.get(path) or path.rsplit("/", 1)[-1]

    def tops(self, names: Names) -> list[dict]:
        """候補にする最上位の物: マスター一覧に載っていて(英名で照合)、設計図があるもの。ja はマスター一覧の和名。

        [{key: 内部パス, en, ja, cat: マスター一覧のカテゴリー}]。同じ英名は最初のものだけ。並びは英名
        """
        known: dict[str, dict] = {}
        for m in names.mastery:
            if isinstance(m, dict) and isinstance(m.get("en"), str) and m.get("cat") in MASTERY_CATS:
                known.setdefault(m["en"].lower(), m)
        out: dict[str, dict] = {}
        for path in self.by_result:
            en = self.names.get(path)
            if en and (m := known.get(en.lower())) and en.lower() not in out:
                out[en.lower()] = {"key": path, "en": en, "ja": m.get("ja") or names.ja(en), "cat": m["cat"]}
        return sorted(out.values(), key=lambda x: x["en"].lower())

    def is_part(self, path: str) -> bool:
        """下に開く部品か(内部パスが RECIPE_PART_PREFIXES のどれかで始まり、設計図があるもの)"""
        return path.startswith(RECIPE_PART_PREFIXES) and path in self.by_result

    def tree(self, recipe: dict, names: Names, sources_of: Callable[[str], object] | None = None, top_ja: str = "") -> dict:
        """1つの設計図から、入れ子の素材の一覧と合計を作る(recipe_view の1つ分)。

        返り値 = {bp_en bp_ja: 設計図の名前, credits, time, num, parts: [節], total: {credits, items: [{en, ja, count, kind}]}}。
        節 = {en, ja, count: この1回の作成に要る数, kind: "part"(部品)/ "item"(末端の素材)}。
        部品は credits time num と下の parts を持つ。末端は sources(sources_of(英名) の返り値。sources_of が無ければ None)。
        合計は末端の素材の数を、部品を作る回数(要る数 ÷ できる数の切り上げ)を掛けて足したもの。クレジットも同じ数え方
        """
        totals: dict[str, int] = {}
        credits = [recipe["credits"]]
        found: dict[str, object] = {}

        def leaf_sources(en: str) -> object:
            if sources_of is None:
                return None
            if en not in found:
                found[en] = sources_of(en)
            return found[en]

        def walk(rec: dict, times: int, depth: int, seen: frozenset) -> list[dict]:
            out = []
            for p in rec["parts"]:
                en = self.name(p["path"])
                node = {"en": en, "ja": names.ja(en), "count": p["count"]}
                if self.is_part(p["path"]) and depth < RECIPE_MAX_DEPTH and p["path"] not in seen:
                    sub = self.by_result[p["path"]][0]
                    crafts = math.ceil(p["count"] / sub["num"]) * times
                    credits.append(sub["credits"] * crafts)
                    node.update(kind="part", credits=sub["credits"], time=sub["time"], num=sub["num"],
                                parts=walk(sub, crafts, depth + 1, seen | {p["path"]}))
                else:
                    totals[en] = totals.get(en, 0) + p["count"] * times
                    node.update(kind="item", sources=leaf_sources(en))
                out.append(node)
            return out

        parts = walk(recipe, 1, 1, frozenset({recipe["result"]}))
        items = [{"en": en, "ja": names.ja(en), "count": n} for en, n in totals.items()]
        items.sort(key=lambda x: (-x["count"], x["en"].lower()))
        top_en = self.name(recipe["result"])
        return {"bp_en": f"{top_en} Blueprint", "bp_ja": f"{top_ja or names.ja(top_en)} 設計図", "credits": recipe["credits"], "time": recipe["time"],
                "num": recipe["num"], "parts": parts, "total": {"credits": sum(credits), "items": items}}

    def view(self, path: str, names: Names, sources_of: Callable[[str], object] | None = None) -> dict | None:
        """要求素材集の表示用。path(できる物の内部パス)に設計図が無ければ None。

        {key, en, ja, cat, recipes: [tree の返り値…]}(作り方が2通り以上あれば全部。Export の並び)。
        ja・cat は候補(tops)にあればそこから(cat は無ければ "")
        """
        recs = self.by_result.get(path)
        if not recs:
            return None
        en = self.name(path)
        top = next((x for x in self.tops(names) if x["key"] == path), None)
        ja = top["ja"] if top else names.ja(en)
        return {"key": path, "en": en, "ja": ja, "cat": top["cat"] if top else "",
                "recipes": [self.tree(r, names, sources_of, ja) for r in recs]}


_LAST_DETAILS = [name_txt("mode.", m) for m in RECIPE_SOURCE_LAST_MODES]


def sort_sources(rows: list[dict]) -> list[dict]:
    """素材の入手先(find_sources の行。確率の高い順)のうち、ミッションの種類が RECIPE_SOURCE_LAST_MODES(コンクラーヴ)の行を後ろに回す。
    ほかの並びはそのまま。後ろに回す行しか無ければそのまま出る"""
    def is_last(r: dict) -> bool:
        return r.get("cat") == "mission" and r.get("detail") in _LAST_DETAILS
    return [r for r in rows if not is_last(r)] + [r for r in rows if is_last(r)]


def pick_tops(query: str, tops: list[dict]) -> list[dict]:
    """候補(Recipes.tops)のうち、名前(英名・日本語名・ひらがな)が query に合うものを合い方の良い順に。query が空なら全部(日本語名の順)"""
    if not query.strip():
        return sorted(tops, key=lambda x: norm(x["ja"]))
    scored = [(r, norm(x["ja"]), i) for i, x in enumerate(tops) if (r := rank(query, [x["en"], x["ja"]])) is not None]
    scored.sort()
    return [tops[i] for _, _, i in scored]
