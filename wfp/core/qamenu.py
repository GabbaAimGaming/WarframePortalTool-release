"""Q&A の「教えてクロちゃん」(話題のメニュー)。**日本語のみ**。文は固定(LLM なし)で、data/qa/menu.json に置く。

- 呼びかけの語(words)だけで聞かれたら、最初の一言(lines)と話題の分類のボタンを出す(1段目)
- 分類のボタンを押すと、その分類の一言と中身のボタンを出す(2段目)。中身のボタンは parse_button の形(BUTTON_KINDS:
  例文で聞く q・解説 lore・メニューの分類 menu・ツールの使い方や雑談の話 talk(core.qatalk)・画面のページを開く page)。
  talk.json の話のボタンも同じ形
- 2段目には分類の一覧へ戻るボタン(back。メニューの id は QA_MENU_TOP)も付ける
- 呼びかけの語のあとに質問が続くとき(「クロちゃん、Rhino のアーマーは?」)は、語を取り除いて普通の質問として答える(menu_rest)
- 照合の前後(名前・聞きたいこと・解説)は core.qa が行う。ここはデータの形・検査・呼びかけの判定・答えの組み立てだけ
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from wfp.core.text import norm
from wfp.core.const import QA_MENU_TOP

# ボタンの種類(1つのボタンにどれか1つ)。q は例文(label は任意。無ければ例文)、ほかは label が要る。
# lore = 解説の id・menu = メニューの分類の id(QA_MENU_TOP で分類の一覧)・talk = talk.json の話の id・page = 画面のページの id
BUTTON_KINDS = ("q", "lore", "menu", "talk", "page")

# 呼びかけの語を取り除いたあと、これしか残らなければ「呼びかけだけ」とみなす(句読点・記号・伸ばし棒)
_MENU_FILLER = re.compile(r"[\s、。,.!?！？~〜ー…♪「」『』]+")


@dataclass
class MenuData:
    words: list[str] = field(default_factory=list)    # 呼びかけの語(長い順)
    lines: list[dict] = field(default_factory=list)   # 1段目の一言 [{id, ja}]
    title: str = ""                                   # 1段目の見出し(画面の「あなた:」の横。ボタンから聞いたとき)
    back: str = ""                                    # 分類の一覧へ戻るボタンの文字
    topics: list[dict] = field(default_factory=list)  # [{id, label, lines: [{id, ja}], items: [ボタン(parse_button)]}]

    def topic(self, mid: str) -> dict | None:
        return next((t for t in self.topics if t["id"] == mid), None)


def _lines(raw: object) -> list[dict]:
    return [m for m in raw or [] if isinstance(m, dict) and isinstance(m.get("ja"), str) and m["ja"].strip()] \
        if isinstance(raw, list) else []


def parse_button(raw: object) -> dict | None:
    """ボタン1つの形を整える({label, <種類>: 値})。種類(BUTTON_KINDS)はちょうど1つ・値は空でない文字列。
    label は q なら任意(無ければ例文)、ほかは必須。崩れていれば None"""
    if not isinstance(raw, dict):
        return None
    kinds = [k for k in BUTTON_KINDS if k in raw]
    if len(kinds) != 1 or not isinstance(raw[kinds[0]], str) or not raw[kinds[0]].strip():
        return None
    kind, value = kinds[0], raw[kinds[0]].strip()
    label = raw.get("label")
    if not (isinstance(label, str) and label.strip()):
        if kind != "q":
            return None
        label = value
    return {"label": label.strip(), kind: value}


def check_buttons(where: str, raws: object, refs: dict[str, set[str]]) -> list[str]:
    """ボタンの一覧の検査。refs = 種類 -> その種類で使える id(書いていない種類は id を見ない)"""
    if raws is None:
        return []
    if not isinstance(raws, list):
        return [f"{where} はボタンの一覧にする"]
    problems = []
    for raw in raws:
        b = parse_button(raw)
        if b is None:
            problems.append(f"{where} に形の崩れたボタンがある({' / '.join(BUTTON_KINDS)} のどれか1つ。q 以外は label も): {raw}")
            continue
        kind = next(k for k in BUTTON_KINDS if k in b)
        if kind in refs and b[kind] not in refs[kind]:
            problems.append(f"{where}: {kind} の {b[kind]} が無い")
    return problems


def load_menu(raw: object) -> MenuData:
    """data/qa/menu.json から MenuData を作る。形の崩れた行は飛ばす(読めなければ空 = 呼びかけに反応しない)"""
    src = raw if isinstance(raw, dict) else {}
    raw_words = src.get("words") if isinstance(src.get("words"), list) else []
    words = sorted({w.strip() for w in raw_words if isinstance(w, str) and _menu_key(w)}, key=lambda w: -len(_menu_key(w)))
    topics = []
    for row in src.get("topics") or []:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not isinstance(row.get("label"), str):
            continue
        items = [it for it in (parse_button(x) for x in row.get("items") or []) if it]
        if row["id"] != QA_MENU_TOP and items:
            topics.append({"id": row["id"], "label": row["label"], "lines": _lines(row.get("lines")), "items": items})
    return MenuData(words, _lines(src.get("lines")), str(src.get("title") or (words[0] if words else "")),
                    str(src.get("back") or ""), topics)


def check_menu(raw: object, refs: dict[str, set[str]], taken_words: dict[str, str]) -> list[str]:
    """同梱データの検査(テスト用)。refs = ボタンの種類 -> 使える id(lore・talk・page。menu はこのファイルの分類から足す)、
    taken_words = ほかで使っている語(norm したもの)-> どこの語か。見つかった問題の一覧(無ければ空)"""
    problems: list[str] = []
    src = raw if isinstance(raw, dict) else {}
    menu = load_menu(raw)
    if not menu.words:
        problems.append("words が無い")
    for w in menu.words:
        if norm(w) in taken_words:
            problems.append(f"words: 語 {w} が {taken_words[norm(w)]} と重なる")
    if "words" in src and not isinstance(src["words"], list):
        problems.append("words は語の一覧にする")
    for where, rows in [("lines", src.get("lines"))] + [(f"topics.{t.get('id')}.lines", t.get("lines"))
                                                         for t in src.get("topics") or [] if isinstance(t, dict)]:
        problems += _check_lines(where, rows)
    if not menu.back:
        problems.append("back(分類の一覧へ戻るボタンの文字)が無い")
    raw_topics = src.get("topics") or []
    if len(menu.topics) != len(raw_topics):
        problems.append(f"topics に形の崩れた行がある(id・label・items を確かめる。id に {QA_MENU_TOP} は使えない)")
    ids = [t["id"] for t in menu.topics]
    problems += [f"topics: id {i} が重複" for i in sorted({i for i in ids if ids.count(i) > 1})]
    refs = {**refs, "menu": set(ids) | {QA_MENU_TOP}}
    for row in raw_topics:
        if isinstance(row, dict):
            problems += check_buttons(f"topics.{row.get('id')}.items", row.get("items") or [], refs)
    return problems


def _check_lines(where: str, rows: object) -> list[str]:
    good = _lines(rows)
    if not good:
        return [f"{where} の一言が無い"]
    mids = [m.get("id") for m in good]
    if len(good) != len(rows) or any(not isinstance(i, int) or isinstance(i, bool) for i in mids):
        return [f"{where} に形の崩れた行がある(id は整数・ja は文)"]
    return [f"{where} の id が重複"] if len(mids) != len(set(mids)) else []


def menu_rest(menu: MenuData | None, question: str) -> str | None:
    """質問の文に呼びかけの語があれば、語を取り除いた残りの文(呼びかけだけなら空の文)。語が無ければ None。
    語は長い順に1つだけ取り除く(「教えてクロちゃん」を「クロちゃん」より先に)"""
    if not menu or not question:
        return None
    for w in menu.words:
        hit = _find(question, w)
        if hit is not None:
            rest = question[:hit[0]] + " " + question[hit[1]:]
            return "" if not _MENU_FILLER.sub("", rest) else rest.strip()
    return None


def _menu_key(s: str) -> str:
    """呼びかけの照合に使う形(norm したうえで句読点・記号も除く。「教えて、クロちゃん!」も当たる)"""
    return _MENU_FILLER.sub("", norm(s))


def _find(question: str, word: str) -> tuple[int, int] | None:
    """question の中で _menu_key にして word に当たる範囲(元の文の位置)。無ければ None"""
    key = _menu_key(word)
    for start in range(len(question)):
        if not _menu_key(question[start]):  # 句読点・空白からは始めない
            continue
        for end in range(start + 1, len(question) + 1):
            got = _menu_key(question[start:end])
            if got == key:
                return start, end
            if not key.startswith(got):
                break
    return None


def menu_answer(menu: MenuData, res: dict, mid: str = QA_MENU_TOP, rng: random.Random | None = None) -> dict | None:
    """メニューの答え(res を書き換えて返す)。mid = QA_MENU_TOP なら分類の一覧、分類の id ならその中身。知らない id は None。
    返り値の menu = {id, title}(ボタンから聞いたときの見出し)、options は {label, menu} か {label, q} か {label, lore}"""
    rng = rng or random
    if mid == QA_MENU_TOP:
        res.update(type="menu", intent="menu", menu={"id": QA_MENU_TOP, "title": menu.title},
                   text=rng.choice(menu.lines)["ja"] if menu.lines else "",
                   options=[{"label": t["label"], "menu": t["id"]} for t in menu.topics])
        return res
    t = menu.topic(mid)
    if t is None:
        return None
    res.update(type="menu", intent="menu", menu={"id": t["id"], "title": t["label"]},
               text=rng.choice(t["lines"])["ja"] if t["lines"] else "",
               options=[dict(it) for it in t["items"]] + ([{"label": menu.back, "menu": QA_MENU_TOP}] if menu.back else []))
    return res
