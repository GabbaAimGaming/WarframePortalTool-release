"""Q&A の解説(設定・ストーリー・仕組み。core.qalore)と話(ツールの使い方・雑談。core.qatalk)の選び方と答えの組み立て。
質問の文に語・needs が当たるかを見て、どの話のどの段を出すかを決める(データの形・段の選び方は core.qalore)
"""
from __future__ import annotations

from wfp.core.text import norm, spaced
from wfp.core.qadata import fill_text
from wfp.core.qaindex import QaIndex, word_hit
from wfp.core.qacontext import QaContext
from wfp.core.qalore import LoreData, missing_quests, needs_kind, next_stage, pick_line, pick_prefix, pick_stage


# --------------------------------------------------------------------------
# 話(ツールの使い方・雑談。core.qatalk)
# --------------------------------------------------------------------------

def talk_topic(ctx: QaContext, question: str) -> str | None:
    """話の語が当たった話の id(一番長く当たった語。同じ長さならファイルの並びで先のもの)。名前(QaIndex.find)が話の語より長く
    当たったときは名前を優先する(解説の lore_group と同じ考え方)。無ければ None"""
    forms = {"norm": norm(question), "spaced": spaced(question)}
    hits = [(word_hit(forms, w), tid) for w, tid in ctx.talk.words()]
    best = max((n for n, _ in hits), default=0)
    if not best:
        return None
    _, rest = ctx.index.find(question)
    if rest.get("hit_len", 0) > best:
        return None
    return next(tid for n, tid in hits if n == best)


# --------------------------------------------------------------------------
# 解説(設定・ストーリー。core.qalore)
# --------------------------------------------------------------------------

def _lore_word(lore: LoreData, forms: dict) -> tuple[int, list[str]]:
    """解説の語が当たった (語の長さ, [group])(一番長く当たった語の group。shared の語なら2つ以上・ファイルの並び)。無ければ (0, [])"""
    hits = [(word_hit(forms, w), g) for w, g in lore.words()]
    best = max((n for n, _ in hits), default=0)
    return (best, list(dict.fromkeys(g for n, g in hits if n == best))) if best else (0, [])


def lore_group(lore: LoreData, question: str, rest: dict) -> list[str]:
    """解説の語で答える group(2つ以上なら選ぶボタン。shared の語)。名前(QaIndex.find)が解説の語より長く当たったときは、
    名前の部分を除いた文で探し直す(例: 「オロキンセル」は名前 6 文字 > 解説の語「オロキン」4 文字なので、名前として答える)。
    同じ長さなら解説が先(名前と同じ語を解説に書いた場合)"""
    hit_len, groups = _lore_word(lore, {"norm": norm(question), "spaced": spaced(question)})
    if groups and rest.get("hit_len", 0) > hit_len:
        groups = _lore_word(lore, rest)[1]
    return groups


def lore_choice(lore: LoreData, rest: dict) -> dict | None:
    """名前を除いた文に当たった選択肢(一番長く当たった語)。無ければ None"""
    best = max(((word_hit(rest, w), -i, c["id"]) for i, c in enumerate(lore.choices) for w in c["words"]),
               default=(0, 0, None))
    return lore.choice(best[2]) if best[0] else None


def _needs_hit(rest: dict, e: dict | None, word: str) -> bool:
    """needs の語が当たるか。種類の印(「@frame」)は拾った名前がその種類なら当たり。
    普通の語は名前の部分を除いた文に当たるか、拾った名前そのもの(英名・和名)なら当たり(名前は文から除かれているため)"""
    kind = needs_kind(word)
    if kind is not None:
        return e is not None and kind in QaIndex.kinds(e)
    return bool(word_hit(rest, word)) or (e is not None and norm(word) in {norm(e["en"]), norm(e["ja"] or "")})


def lore_needs(ctx: QaContext, res: dict, e: dict | None, rest: dict, spoil: bool) -> dict | None:
    """needs のまとまりが全部当たった話(group ごと)。文は名前の部分を除いたもの(名前が無ければ文全体)。
    about に拾った名前がある話(名前つき)が当たればそれだけ、無ければ about が空の話(名前なし)から選ぶ。
    語の当たり方は _needs_hit(種類の印「@frame」なども)。
    まとまりの数が一番多い話を出す。同じ数が2つ以上ならタイトルのボタン。当たらなければ None"""
    key = norm(e["en"]) if e else None
    named: dict[str, tuple[int, dict]] = {}
    free: dict[str, tuple[int, dict]] = {}
    for t in ctx.lore.needs_topics():
        if t["about"] and not any(norm(a) == key for a in t["about"]):
            continue
        if all(any(_needs_hit(rest, e, w) for w in g) for g in t["needs"]):
            hits = named if t["about"] else free
            if t["group"] not in hits or len(t["needs"]) > hits[t["group"]][0]:
                hits[t["group"]] = (len(t["needs"]), t)
    hits = named or free
    if not hits:
        return None
    most = max(n for n, _ in hits.values())
    best = [t for n, t in hits.values() if n == most]
    if len(best) == 1:
        return lore_answer(ctx, res, pick_stage(ctx.lore, best[0]["group"], ctx.done), spoil)
    return lore_pick(ctx, res, best)


def lore_options(lore: LoreData | None, e: dict, heads: list[dict]) -> list[dict]:
    """名前の解説の選択肢(ボタン)。その種類の話がある選択肢だけ(0段目の type で見る)"""
    if not lore or not heads:
        return []
    types = {h["type"] for h in heads}
    return [{"label": fill_text(c["label"], {"name": e["ja"]}), "name": e["key"], "choice": c["id"]}
            for c in lore.choices if types & set(c["types"])]


def lore_system(ctx: QaContext, res: dict, heads: list[dict], spoil: bool) -> dict | None:
    """MOD の名前で聞かれたとき(「Serration」「Serrationとは」): 選択肢を出さずに system の話へ直行。
    1つならその話・2つ以上(group が違う)なら選ぶボタン。system の話が無ければ None(今どおり選択肢)"""
    systems = [h for h in heads if h["type"] == "system"]
    if not systems:
        return None
    if len(systems) == 1:
        return lore_answer(ctx, res, pick_stage(ctx.lore, systems[0]["group"], ctx.done), spoil)
    return lore_pick(ctx, res, systems)


def lore_pick(ctx: QaContext, res: dict, heads: list[dict]) -> dict:
    """当てはまる話が2つ以上: タイトルのボタン(押すと、進み具合で選んだ段の解説)"""
    rows = [pick_stage(ctx.lore, h["group"], ctx.done) for h in heads]
    res.update(intent="lore", text=pick_line(ctx.lore, "pick_topic", ctx.rng),
               options=[{"label": t["title"], "lore": t["id"]} for t in rows])
    return res


def _lore_parts(lore: LoreData, t: dict, only: bool, rng) -> list[dict]:
    """出す段: 0段目から t の段まで(only なら t だけ)。枕詞は前の段と prefix のグループが変わる段だけ(最初の段は必ず)"""
    rows = [t] if only else [r for r in lore.stages(t["group"]) if r["stage"] <= t["stage"]]
    parts, last = [], object()
    for r in rows:
        parts.append({"id": r["id"], "title": r["title"], "stage": r["stage"],
                      "prefix": pick_prefix(lore, r, rng) if r["prefix"] != last else "", "paragraphs": list(r["text"])})
        last = r["prefix"]
    return parts


def lore_answer(ctx: QaContext, res: dict, t: dict, spoil: bool, only: bool = False) -> dict:
    """その話を出す(0段目から t の段まで。only なら t だけ)。クエストの中身で未完了のクエストがあり、spoil でなければ、先に確認する
    (上の段の requires は下の段の分を含むので、確かめるのは t だけでよい)"""
    lore, rng = ctx.lore, ctx.rng
    res["intent"] = "lore"
    missing = missing_quests(t, ctx.done)
    if missing and not spoil:
        quests = [ctx.quest_names.get(q, q) for q in missing]
        res.update(type="spoiler_ask", text=pick_line(lore, "spoiler_ask", rng, quest="・".join(quests), title=t["title"]),
                   spoiler={"id": t["id"], "title": t["title"], "quests": quests, "ok": pick_line(lore, "spoiler_ok", rng),
                            "ng": pick_line(lore, "spoiler_ng", rng), "declined": pick_line(lore, "declined", rng),
                            "only": only})
        return res
    parts = _lore_parts(lore, t, only, rng)
    sources = list(dict.fromkeys(u for p in parts for u in lore.topic(p["id"])["source"]))
    res.update(type="lore", lore={"id": t["id"], "title": t["title"], "group": t["group"], "stage": t["stage"],
                                  "parts": parts, "source": sources, "credit": lore.credit, "license": lore.license})
    nx = next_stage(lore, t)
    if nx:
        res["next"] = {"id": nx["id"], "title": nx["title"], "label": pick_line(lore, "next_stage", rng, title=nx["title"])}
    return res
