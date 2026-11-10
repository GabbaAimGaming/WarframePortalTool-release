"""Q&A の Warframe と関係ない話(ツールの使い方・雑談)。**日本語のみ**。文は固定(LLM なし)で、data/qa/talk.json に置く。

- 話の種類は QA_TALK_TYPES: tool(このツールの使い方)/ chat(雑談・遊び。クロちゃんのプロフィール・おみくじ・褒めて など)
- 話は words(当たる語)で引く。返事は replies(返事の候補。1つの返事は段落の一覧)からランダムに1つ(同じ質問でも返事が変わる)
- buttons(任意)はメニューと同じ形(core.qamenu の parse_button)。talk で次の話へ進めるので、ちょっとした会話の流れも書ける。
  page で画面のページを開く(使い方の話のあとにすぐ飛べる)
- 照合(質問の文に words が当たるか)は core.qa が行う。ここはデータの形・検査・答えの組み立てだけ
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from wfp.core.text import norm
from wfp.core.const import QA_TALK_TYPES
from wfp.core.qamenu import check_buttons, parse_button


@dataclass
class TalkData:
    topics: list[dict] = field(default_factory=list)  # [{id, type, title, words, replies: [[段落, …], …], buttons}]

    def __post_init__(self):
        self._by_id = {t["id"]: t for t in self.topics}

    def topic(self, tid: str) -> dict | None:
        return self._by_id.get(tid)

    def words(self) -> list[tuple[str, str]]:
        """照合に使う (語, 話の id)"""
        return [(w, t["id"]) for t in self.topics for w in t["words"]]


def _replies(raw: object) -> list[list[str]]:
    """返事の候補のうち、段落(空でない文字列)が1つ以上あるもの"""
    out = []
    for rep in raw if isinstance(raw, list) else []:
        paras = [x.strip() for x in rep if isinstance(x, str) and x.strip()] if isinstance(rep, list) else []
        if paras:
            out.append(paras)
    return out


def _topic(row: object) -> dict | None:
    """話1つの形を整える(id は「種類.」で始める・返事が1つ以上)。崩れていれば None"""
    if not isinstance(row, dict) or not isinstance(row.get("id"), str) or row.get("type") not in QA_TALK_TYPES:
        return None
    if not row["id"].startswith(row["type"] + ".") or not isinstance(row.get("title"), str) or not row["title"].strip():
        return None
    replies = _replies(row.get("replies"))
    if not replies:
        return None
    words = [w.strip() for w in row.get("words") or [] if isinstance(w, str) and norm(w)]
    buttons = [b for b in (parse_button(x) for x in row.get("buttons") or []) if b]
    return {"id": row["id"], "type": row["type"], "title": row["title"].strip(), "words": words, "replies": replies,
            "buttons": buttons}


def load_talk(raw: object) -> TalkData:
    """data/qa/talk.json から TalkData を作る。形の崩れた話は飛ばす(読めなければ空 = 話に反応しない)"""
    rows = (raw.get("topics") if isinstance(raw, dict) else None) or []
    return TalkData([t for t in (_topic(r) for r in rows) if t])


def check_talk(raw: object, refs: dict[str, set[str]], taken_words: dict[str, str]) -> list[str]:
    """同梱データの検査(テスト用)。refs = ボタンの種類 -> 使える id(lore・menu・page。talk はこのファイルの話から足す)、
    taken_words = ほかで使っている語(norm)-> どこの語か。見つかった問題の一覧(無ければ空)"""
    problems: list[str] = []
    rows = (raw.get("topics") if isinstance(raw, dict) else None) or []
    data = load_talk(raw)
    if len(data.topics) != len(rows):
        problems.append(f"topics に形の崩れた話がある(id は「{' / '.join(QA_TALK_TYPES)}.」で始める・title・replies を確かめる)")
    ids = [t["id"] for t in data.topics]
    problems += [f"topics: id {i} が重複" for i in sorted({i for i in ids if ids.count(i) > 1})]
    seen: dict[str, str] = {}
    for t in data.topics:
        for w in t["words"]:
            key = norm(w)
            if key in taken_words:
                problems.append(f"{t['id']}: 語 {w} が {taken_words[key]} と重なる")
            if key in seen and seen[key] != t["id"]:
                problems.append(f"{t['id']}: 語 {w} が {seen[key]} にもある")
            seen[key] = t["id"]
    refs = {**refs, "talk": set(ids)}
    for row in rows:
        if isinstance(row, dict):
            problems += check_buttons(f"{row.get('id')}.buttons", row.get("buttons"), refs)
    return problems


def talk_answer(data: TalkData, res: dict, tid: str, rng: random.Random | None = None) -> dict | None:
    """話の答え(res を書き換えて返す)。返事は候補からランダムに1つ。知らない id は None。
    返り値の talk = {id, type, title, paragraphs}、options = 話のボタン"""
    t = data.topic(tid)
    if t is None:
        return None
    res.update(type="talk", intent="talk", talk={"id": t["id"], "type": t["type"], "title": t["title"],
                                                  "paragraphs": list((rng or random).choice(t["replies"]))},
               options=[dict(b) for b in t["buttons"]])
    return res
