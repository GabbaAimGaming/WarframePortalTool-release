"""Q&A の解説(設定・ストーリー)。**日本語のみ**。文は固定(LLM なし)で、data/qa/lore.json・lore_talk.json に置く。

- 解説の種類は QA_LORE_TYPES: setting(クエストと無縁)/ quest(クエストの中身。requires のクエストが未完了なら、話す前に確認する)
- 同じ話は group / stage で段に分ける。進み具合(クエスト一覧のチェック)で終えている段のうち一番上を出し、上の段があれば「続き」を出す
- 一言(枕詞・ネタバレの確認・続き など)は lore_talk.json の場面ごとの一覧からランダムに1つ
- 照合(質問の文に words が当たるか)は core.qa が行う。ここはデータの形・検査・段の選び方だけ
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from wfp.core.common import QA_LORE_LINES, QA_LORE_TYPES, norm
from wfp.core.quests import check_flow

# 解説の項目の並び(読み込み後の形)
_LORE_KEYS = ("id", "type", "about", "title", "words", "requires", "group", "stage", "prefix", "source", "text")


@dataclass
class LoreData:
    topics: list[dict] = field(default_factory=list)   # 形を整えた解説(ファイルの並び)
    talk: dict = field(default_factory=dict)            # {場面: [{id, ja}]}(QA_LORE_LINES)
    prefix: dict = field(default_factory=dict)          # {枕詞のグループ: [{id, ja}]}
    choices: list[dict] = field(default_factory=list)   # [{id, label, words, types}]
    license: str = ""
    credit: str = ""

    def __post_init__(self):
        self._by_id = {t["id"]: t for t in self.topics}
        self._groups: dict[str, list[dict]] = {}
        for t in self.topics:
            self._groups.setdefault(t["group"], []).append(t)
        for rows in self._groups.values():
            rows.sort(key=lambda t: t["stage"])

    def topic(self, tid: str) -> dict | None:
        return self._by_id.get(tid)

    def stages(self, group: str) -> list[dict]:
        """group の段(stage の順)。無ければ空"""
        return self._groups.get(group, [])

    def groups(self) -> list[str]:
        return list(self._groups)

    def choice(self, cid: str) -> dict | None:
        return next((c for c in self.choices if c["id"] == cid), None)

    def words(self) -> list[tuple[str, str]]:
        """照合に使う語: [(語, group)]。group のどの段に書いた語でも group として当たる"""
        return [(w, t["group"]) for t in self.topics for w in t["words"]]


def _lines(raw: object) -> list[dict]:
    return [m for m in raw if isinstance(m, dict) and isinstance(m.get("ja"), str) and m["ja"].strip()] if isinstance(raw, list) else []


def _strs(raw: object) -> list[str]:
    return [s.strip() for s in raw if isinstance(s, str) and s.strip()] if isinstance(raw, list) else []


def _topic(row: object) -> dict | None:
    """lore.json の1行を形を整えて返す。必須の項目が欠けていれば None"""
    if not isinstance(row, dict):
        return None
    tid, typ, title = row.get("id"), row.get("type"), row.get("title")
    text = _strs(row.get("text"))
    if not isinstance(tid, str) or not tid.strip() or typ not in QA_LORE_TYPES or not isinstance(title, str) or not title.strip() or not text:
        return None
    stage = row.get("stage", 0)
    group = row.get("group")
    prefix = row.get("prefix")
    return {"id": tid.strip(), "type": typ, "about": _strs(row.get("about")), "title": title.strip(), "words": _strs(row.get("words")),
            "requires": _strs(row.get("requires")) if typ == "quest" else [],
            "group": group.strip() if isinstance(group, str) and group.strip() else tid.strip(),
            "stage": stage if isinstance(stage, int) and not isinstance(stage, bool) else 0,
            "prefix": prefix if isinstance(prefix, str) and prefix.strip() else None,
            "source": _strs(row.get("source")), "text": text}


def _choices(raw: object) -> list[dict]:
    out = []
    for c in raw if isinstance(raw, list) else []:
        if not isinstance(c, dict) or not isinstance(c.get("id"), str) or not isinstance(c.get("label"), str):
            continue
        types = [t for t in c.get("types") or [] if t in QA_LORE_TYPES]
        words = _strs(c.get("words"))
        if types and words:
            out.append({"id": c["id"], "label": c["label"], "words": words, "types": types})
    return out


def load_lore(lore_raw: object, talk_raw: object) -> LoreData:
    """lore.json・lore_talk.json から LoreData を作る。形の崩れた行は飛ばし、`_` で始まるキーは見ない(読めなければ空)"""
    rows = (lore_raw.get("topics") if isinstance(lore_raw, dict) else None) or []
    topics = [t for t in (_topic(r) for r in rows) if t]
    talk_src = talk_raw if isinstance(talk_raw, dict) else {}
    talk = {k: _lines(talk_src.get(k)) for k in QA_LORE_LINES}
    prefix_src = talk_src.get("prefix") if isinstance(talk_src.get("prefix"), dict) else {}
    prefix = {k: _lines(v) for k, v in prefix_src.items() if not k.startswith("_")}
    meta = lore_raw if isinstance(lore_raw, dict) else {}
    return LoreData(topics, talk, prefix, _choices(talk_src.get("choices")),
                    license=str(meta.get("license") or ""), credit=str(meta.get("credit") or ""))


# --------------------------------------------------------------------------
# 検査(テスト用)
# --------------------------------------------------------------------------

def _check_lines(name: str, rows: object, problems: list[str]) -> None:
    rows = rows if isinstance(rows, list) else []
    good = _lines(rows)
    if not good:
        problems.append(f"lore_talk: {name} の文が無い")
    if len(good) != len(rows):
        problems.append(f"lore_talk: {name} に ja の無い行がある")
    ids = [m.get("id") for m in good]
    if any(not isinstance(i, int) or isinstance(i, bool) for i in ids):
        problems.append(f"lore_talk: {name} に id が整数でない行がある")
    elif len(ids) != len(set(ids)):
        problems.append(f"lore_talk: {name} の id が重複")


def check_lore(lore_raw: object, talk_raw: object, flow_raw: object, intent_words: set[str] | list[str] = ()) -> list[str]:
    """同梱データの検査。見つかった問題の一覧(無ければ空)。

    id の重なりと頭(setting. / quest.)・setting は requires を持たない・quest は requires を持つ・requires が flow.json にあり
    covers でまとめられていない・group の stage が 0 から抜けなく続き、上の段の requires が下の段の分を全部含む・
    words が group どうし/intents/choices と重ならない・words も about も無い話が無い・prefix のグループがある・一言の場面の文
    """
    problems: list[str] = []
    data = load_lore(lore_raw, talk_raw)
    raw_rows = (lore_raw.get("topics") if isinstance(lore_raw, dict) else None) or []
    if len(data.topics) != len(raw_rows):
        problems.append("lore: 形の崩れた行がある(id・type・title・text を確かめる)")
    ids = [t["id"] for t in data.topics]
    problems += [f"lore: id {i} が重複" for i in sorted({i for i in ids if ids.count(i) > 1})]
    flow = check_flow(flow_raw)
    quest_ids = {it["id"] for it in flow if it["kind"] == "quest"}
    covered = {c for it in flow if it["kind"] == "quest" for c in it["covers"]}
    for raw, t in zip(raw_rows, (_topic(r) for r in raw_rows)):
        if t is None:
            continue
        tid = t["id"]
        if not tid.startswith(t["type"] + "."):
            problems.append(f"lore: {tid} の id は {t['type']}. で始める")
        if t["type"] == "setting" and isinstance(raw, dict) and _strs(raw.get("requires")):
            problems.append(f"lore: {tid} は setting なので requires を書かない(クエストに関わるなら quest にする)")
        if t["type"] == "quest" and not t["requires"]:
            problems.append(f"lore: {tid} は quest なのに requires が無い")
        for q in t["requires"]:
            if q in covered:
                problems.append(f"lore: {tid} の requires {q} は covers でまとめられている(まとめた側の id を書く)")
            elif q not in quest_ids:
                problems.append(f"lore: {tid} の requires {q} が flow.json に無い")
        if not t["words"] and not t["about"]:
            problems.append(f"lore: {tid} は words も about も無い(拾えない)")
        if t["prefix"] is not None and t["prefix"] not in data.prefix:
            problems.append(f"lore: {tid} の prefix {t['prefix']} が lore_talk.json に無い")
    for g in data.groups():
        rows = data.stages(g)
        if [t["stage"] for t in rows] != list(range(len(rows))):
            problems.append(f"lore: group {g} の stage が 0 から続いていない")
        for lo, hi in zip(rows, rows[1:]):
            if not set(lo["requires"]) <= set(hi["requires"]):
                problems.append(f"lore: {hi['id']} の requires が下の段 {lo['id']} の分を含んでいない")
    seen: dict[str, str] = {}
    intents = {norm(w) for w in intent_words}
    choice_words = {norm(w): c["id"] for c in data.choices for w in c["words"]}
    for w, g in data.words():
        key = norm(w)
        if key in seen and seen[key] != g:
            problems.append(f"lore: 語 {w} が {seen[key]} と {g} の両方にある")
        seen[key] = g
        if key in intents:
            problems.append(f"lore: 語 {w} が intents.json と重なる")
        if key in choice_words:
            problems.append(f"lore: 語 {w} が lore_talk.json の choices と重なる")
    problems += [f"lore_talk: choices の語 {w} が intents.json と重なる" for w in choice_words if w in intents]
    talk_src = talk_raw if isinstance(talk_raw, dict) else {}
    for name in QA_LORE_LINES:
        _check_lines(name, talk_src.get(name), problems)
    for name, rows in (talk_src.get("prefix") or {}).items() if isinstance(talk_src.get("prefix"), dict) else []:
        _check_lines(f"prefix.{name}", rows, problems)
    cids = [c["id"] for c in data.choices]
    if len(data.choices) != len(talk_src.get("choices") or []):
        problems.append("lore_talk: choices に形の崩れた行がある(id・label・words・types を確かめる)")
    problems += [f"lore_talk: choices の id {i} が重複" for i in sorted({i for i in cids if cids.count(i) > 1})]
    if data.topics and (not data.license or not data.credit):
        problems.append("lore: license・credit が無い(出典を出せない)")
    return problems


def lore_notes(data: LoreData, entity_keys: set[str], label_keys: set[str]) -> list[str]:
    """注意だけ(手元のデータで変わるので検査の失敗にはしない): about が名前の索引に無い・words が索引の名前と同じ"""
    notes = []
    for t in data.topics:
        notes += [f"{t['id']}: about {a} が名前の索引に無い(選択肢から出せない)" for a in t["about"] if norm(a) not in entity_keys]
        notes += [f"{t['id']}: 語 {w} が名前の索引にもある(解説が先に答える)" for w in t["words"] if norm(w) in label_keys]
    return notes


# --------------------------------------------------------------------------
# 段の選び方・一言
# --------------------------------------------------------------------------

def missing_quests(topic: dict, done: set[str]) -> list[str]:
    """その話の requires のうち、まだ終えていないクエストの id(ファイルの並び)"""
    return [q for q in topic["requires"] if q not in done]


def pick_stage(data: LoreData, group: str, done: set[str]) -> dict | None:
    """group の段のうち、requires を全部終えている一番上の段。どの段も終えていなければ 0段目(話す前に確認する)"""
    rows = data.stages(group)
    if not rows:
        return None
    best = rows[0]
    for t in rows:
        if missing_quests(t, done):
            break  # 上の段の requires は下の段の分を含むので、ここから上はどれも未完了
        best = t
    return best


def next_stage(data: LoreData, topic: dict) -> dict | None:
    """その話の次の段(無ければ None)"""
    rows = data.stages(topic["group"])
    return next((t for t in rows if t["stage"] == topic["stage"] + 1), None)


def topics_about(data: LoreData, en: str) -> list[dict]:
    """about にその名前(英名)がある話の 0段目(group ごとに1つ。ファイルの並び)"""
    key = norm(en)
    return [data.stages(g)[0] for g in data.groups() if any(norm(a) == key for t in data.stages(g) for a in t["about"])]


def _fill(template: str, values: dict) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), template)


def pick_line(data: LoreData, scene: str, rng: random.Random | None = None, **values) -> str:
    """一言を場面(QA_LORE_LINES)の一覧からランダムに1つ(値を埋める)。一覧が空なら空の文"""
    rows = data.talk.get(scene) or []
    return _fill((rng or random).choice(rows)["ja"], values) if rows else ""


def pick_prefix(data: LoreData, topic: dict, rng: random.Random | None = None) -> str:
    """その話の枕詞(prefix のグループからランダムに1つ)。prefix が無ければ空の文"""
    rows = data.prefix.get(topic["prefix"] or "") or []
    return (rng or random).choice(rows)["ja"] if rows else ""
