"""Q&A の同梱データ(data/qa/ の intents.json・answers.json・miss.json): 読み込み・検査・ヒットしなかったときの文・名前にしない語。**日本語のみ**"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from wfp.core.text import norm
from wfp.core.const import QA_FORMATS, QA_KINDS, QA_MISS_KINDS


@dataclass
class QaData:
    intents: list[dict] = field(default_factory=list)  # [{id, kinds, label, words, priority}]
    fields: dict = field(default_factory=dict)          # 数値の項目 {key: {label, label_melee?, fmt}}
    order: dict = field(default_factory=dict)           # {"frame": [...], "weapon": [...]} 基本の数値で出す並び
    text: dict = field(default_factory=dict)            # 文の型
    miss: dict = field(default_factory=dict)            # {場面: [{id, ja}]}

    def intent(self, iid: str) -> dict | None:
        return next((i for i in self.intents if i["id"] == iid), None)

    def say(self, key: str, **values) -> str:
        """文の型に値を埋める(無い型は空。知らない差し込みはそのまま残す)"""
        return fill_text(self.text.get(key, ""), values)


def fill_text(template: str, values: dict) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), template)


def load_qa_data(intents_raw: object, answers_raw: object, miss_raw: object) -> QaData:
    """data/qa/ の3つの JSON から QaData を作る。形の崩れた行は飛ばす(読めなければ空)"""
    intents: list[dict] = []
    for row in (intents_raw.get("intents") if isinstance(intents_raw, dict) else None) or []:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            continue
        words = [w for w in row.get("words") or [] if isinstance(w, str) and w.strip()]
        kinds = [k for k in row.get("kinds") or [] if k in QA_KINDS]
        if words and kinds:
            prio = row.get("priority", 0)
            intents.append({"id": row["id"], "kinds": kinds, "words": words, "label": str(row.get("label") or row["id"]),
                            "priority": prio if isinstance(prio, int) and not isinstance(prio, bool) else 0,
                            "button": row.get("button") is not False})
    ans = answers_raw if isinstance(answers_raw, dict) else {}
    fields = {k: v for k, v in (ans.get("fields") or {}).items()
              if isinstance(v, dict) and isinstance(v.get("label"), str) and v.get("fmt") in QA_FORMATS}
    order = {kind: [k for k in ans.get(kind) or [] if k in fields] for kind in ("frame", "weapon")}
    text = {k: v for k, v in (ans.get("text") or {}).items() if isinstance(v, str)}
    miss_src = (miss_raw.get("miss") if isinstance(miss_raw, dict) else None) or {}
    miss = {kind: [m for m in miss_src.get(kind) or [] if isinstance(m, dict) and isinstance(m.get("ja"), str) and m["ja"].strip()]
            for kind in QA_MISS_KINDS}
    return QaData(intents, fields, order, text, miss)


# 答えで使う文の型(check_qa_data が有無を検査する)
TEXT_KEYS = ("field.frame", "field.weapon", "field.summon", "field.none", "stats.frame", "stats.weapon", "stats.summon", "abilities",
             "passive", "sources",
             "sources.parts", "sources.relic", "build", "helminth.frame", "helminth.prime", "helminth.self", "helminth.ability", "helminth.not",
             "basis.builder", "basis.drops", "basis.dev", "basis.helminth", "basis.summon", "options")


def check_qa_data(intents_raw: object, answers_raw: object, miss_raw: object) -> list[str]:
    """同梱データの検査(テスト用)。見つかった問題の一覧(無ければ空)"""
    problems: list[str] = []
    data = load_qa_data(intents_raw, answers_raw, miss_raw)
    raw_intents = (intents_raw.get("intents") if isinstance(intents_raw, dict) else None) or []
    if len(data.intents) != len(raw_intents):
        problems.append("intents に形の崩れた行がある(id・kinds・words を確かめる)")
    ids = [i["id"] for i in data.intents]
    problems += [f"intents: id {i} が重複" for i in sorted({i for i in ids if ids.count(i) > 1})]
    seen: dict[str, str] = {}
    for it in data.intents:
        for w in it["words"]:
            key = norm(w)
            if key in seen and seen[key] != it["id"]:
                problems.append(f"intents: 語 {w} が {seen[key]} と {it['id']} の両方にある")
            seen[key] = it["id"]
        if it["id"] in data.fields and not set(it["kinds"]) <= {"frame", "weapon", "summon"}:
            problems.append(f"intents: 数値の項目 {it['id']} の kinds は frame / weapon / summon だけ")
    for kind in ("frame", "weapon"):
        problems += [f"answers: {kind} の {k} が fields に無い"
                     for k in ((answers_raw or {}).get(kind) or []) if k not in data.fields] if isinstance(answers_raw, dict) else []
    problems += [f"answers: 数値の項目 {k} の質問が intents に無い" for k in data.fields if k not in ids]
    problems += [f"answers: 文の型 {k} が無い" for k in TEXT_KEYS if k not in data.text]
    for kind in QA_MISS_KINDS:
        rows = data.miss.get(kind) or []
        if not rows:
            problems.append(f"miss: {kind} の文が無い")
        mids = [m.get("id") for m in rows]
        if any(not isinstance(i, int) or isinstance(i, bool) for i in mids):
            problems.append(f"miss: {kind} に id が整数でない行がある")
        elif len(mids) != len(set(mids)):
            problems.append(f"miss: {kind} の id が重複")
    return problems


def pick_miss(data: QaData, kind: str, name: str = "", rng: random.Random | None = None) -> dict:
    """ヒットしなかったときの文を場面の一覧からランダムに1つ。{kind, id, text}(一覧が空なら id は None・文は空)"""
    rows = data.miss.get(kind) or []
    if not rows:
        return {"kind": kind, "id": None, "text": ""}
    m = (rng or random).choice(rows)
    return {"kind": kind, "id": m.get("id"), "text": fill_text(m["ja"], {"name": name})}



def stop_words(data: QaData) -> set[str]:
    """名前として拾わない語(聞きたいことの語)"""
    return {w for it in data.intents for w in it["words"]}
