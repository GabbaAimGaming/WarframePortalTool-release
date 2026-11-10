"""Q&A の解説(設定・ストーリー)。**日本語のみ**。文は固定(LLM なし)で、data/qa/lore.json・lore_talk.json に置く。

- 解説の種類は QA_LORE_TYPES: setting(クエストと無縁)/ quest(クエストの中身。requires のクエストが未完了なら、話す前に確認する)/
  system(MOD・ダメージ計算式などゲームの仕組み。requires を持たない。about の MOD 名は Q&A の索引に足す = system_names)
- 同じ話は group / stage で段に分ける。進み具合(クエスト一覧のチェック)で終えている段のうち一番上を出し、上の段があれば「続き」を出す
- 一言(枕詞・ネタバレの確認・続き など)は lore_talk.json の場面ごとの一覧からランダムに1つ
- needs(任意): 語のまとまりの and で引く(例: 「Jade の強いビルド」「武器の強いビルド」)。[[語, …], …] でまとまりの間は and・中は or。
  about があれば名前 + needs(名前の部分を除いた文で探す)、about が空なら名前なしで needs だけ(名前つきの話が当たればそちらが先)。
  まとまりは2つ以上・intents の語を含まないまとまりが1つ以上(普通の「Jade のビルド」を横取りしないため)。
  まとまりには種類の印(QA_NEEDS_MARK + QA_KINDS。例: 「@frame」)も書ける: 拾った名前がその種類なら当たり(「Jade の最強ビルド」)。
  普通の語は、名前の部分を除いた文に当たるか、拾った名前そのもの(英名・和名)なら当たり
- mentions(任意): 話の中に出てくる名前(英名)。索引だけで needs は絞らない(about との違い)。その名前だけで聞かれたときの選択肢・
  MOD の名前で直行に使い、Q&A の索引にも足す(index_names)
- shared(任意): words のうち、ほかの話(group が違う)と重ねてよい語。重ねる側の話の全部に書く。当たったら話のタイトルのボタンで選ぶ
  (例: 「Vox Solaris」= シンジケートとクエストのあらすじ)。shared に書いていない重なりは検査で落とす
- 照合(質問の文に words / needs が当たるか)は core.qa が行う。ここはデータの形・検査・段の選び方だけ
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from wfp.core.text import norm
from wfp.core.const import QA_KINDS, QA_LORE_LINES, QA_LORE_TYPES, QA_NEEDS_MARK
from wfp.core.quests import check_flow

NEEDS_MIN_GROUPS = 2  # needs のまとまりの最小数(1つなら words で足りる)


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

    def needs_topics(self) -> list[dict]:
        """needs のある話(ファイルの並び)"""
        return [t for t in self.topics if t["needs"]]

    def words(self) -> list[tuple[str, str]]:
        """照合に使う語: [(語, group)]。group のどの段に書いた語でも group として当たる"""
        return [(w, t["group"]) for t in self.topics for w in t["words"]]


def _lines(raw: object) -> list[dict]:
    return [m for m in raw if isinstance(m, dict) and isinstance(m.get("ja"), str) and m["ja"].strip()] if isinstance(raw, list) else []


def _strs(raw: object) -> list[str]:
    return [s.strip() for s in raw if isinstance(s, str) and s.strip()] if isinstance(raw, list) else []


def _needs(raw: object) -> list[list[str]]:
    """needs を [[語, …], …] にそろえる。形が違えば空(検査で落とす)"""
    if not isinstance(raw, list):
        return []
    groups = [_strs(g) if isinstance(g, list) else [] for g in raw]
    return groups if groups and all(groups) else []


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
    return {"id": tid.strip(), "type": typ, "about": _strs(row.get("about")),
            "mentions": _strs(row.get("mentions")), "title": title.strip(), "words": _strs(row.get("words")),
            "shared": _strs(row.get("shared")), "needs": _needs(row.get("needs")),
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


def needs_kind(word: str) -> str | None:
    """needs の語が種類の印(「@frame」)なら印の後ろ(「frame」)、普通の語なら None。後ろが QA_KINDS に無くても返す(検査で落とす)"""
    return word[len(QA_NEEDS_MARK):].strip() if word.startswith(QA_NEEDS_MARK) else None


def _check_needs(tid: str, raw: object, t: dict, intent_words, problems: list[str]) -> None:
    """needs の検査(形・まとまりの数・intents の語だけのまとまりにしない・種類の印が QA_KINDS にある)。about は空でもよい(名前なしで引く)"""
    groups = _needs(raw)
    if not groups or len(groups) != len(raw):
        problems.append(f"lore: {tid} の needs の形が違う([[語, …], …] で、空のまとまりは書かない)")
        return
    if len(groups) < NEEDS_MIN_GROUPS:
        problems.append(f"lore: {tid} の needs はまとまりを {NEEDS_MIN_GROUPS} つ以上書く(1つなら words に書く)")
    intents = {norm(w) for w in intent_words}
    if intents and all(any(norm(w) in intents for w in g) for g in groups):
        problems.append(f"lore: {tid} の needs に intents.json の語を含まないまとまりが無い(普通の質問を横取りする)")
    for w in sorted({w for g in groups for w in g if needs_kind(w) is not None and needs_kind(w) not in QA_KINDS}):
        problems.append(f"lore: {tid} の needs の種類の印 {w} が違う({QA_NEEDS_MARK} の後ろは {' / '.join(QA_KINDS)})")


def _check_shared(data: LoreData, problems: list[str]) -> None:
    """words の group どうしの重なりの検査。重ねてよいのは、その語を持つ話の全部が shared に書いた語だけ。
    shared の語は自分の words にあり、ほかの group の words と重なっていること(重ならないなら書かない)"""
    by_word: dict[str, list[tuple[dict, str]]] = {}
    for t in data.topics:
        for w in dict.fromkeys(t["words"]):
            by_word.setdefault(norm(w), []).append((t, w))
    for t in data.topics:
        words = {norm(w) for w in t["words"]}
        for w in t["shared"]:
            if norm(w) not in words:
                problems.append(f"lore: {t['id']} の shared の語 {w} が words に無い")
            elif len({o["group"] for o, _ in by_word[norm(w)]}) < 2:
                problems.append(f"lore: {t['id']} の shared の語 {w} はほかの話と重なっていない(shared は要らない)")
    for rows in by_word.values():
        groups = list(dict.fromkeys(t["group"] for t, _ in rows))
        if len(groups) < 2:
            continue
        loose = [t["id"] for t, w in rows if norm(w) not in {norm(x) for x in t["shared"]}]
        if loose:
            problems.append(f"lore: 語 {rows[0][1]} が {' と '.join(groups)} の両方にある"
                            f"(重ねるなら {' ・ '.join(loose)} の shared にも書く)")


def check_lore(lore_raw: object, talk_raw: object, flow_raw: object, intent_words: set[str] | list[str] = ()) -> list[str]:
    """同梱データの検査。見つかった問題の一覧(無ければ空)。

    needs の形(_check_needs)・id の重なりと頭(setting. / quest. / system.)・quest 以外は requires を持たない・quest は requires を持つ・requires が flow.json にあり
    covers でまとめられていない・group の stage が 0 から抜けなく続き、上の段の requires が下の段の分を全部含む・
    words が group どうし(shared に書いた語を除く)/intents/choices と重ならない・shared が words にあり、ほかの group と重なっている・words も about も無い話が無い・prefix のグループがある・一言の場面の文
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
        if t["type"] != "quest" and isinstance(raw, dict) and _strs(raw.get("requires")):
            problems.append(f"lore: {tid} は {t['type']} なので requires を書かない(クエストに関わるなら quest にする)")
        if t["type"] == "quest" and not t["requires"]:
            problems.append(f"lore: {tid} は quest なのに requires が無い")
        for q in t["requires"]:
            if q in covered:
                problems.append(f"lore: {tid} の requires {q} は covers でまとめられている(まとめた側の id を書く)")
            elif q not in quest_ids:
                problems.append(f"lore: {tid} の requires {q} が flow.json に無い")
        if isinstance(raw, dict) and "needs" in raw:
            _check_needs(tid, raw["needs"], t, intent_words, problems)
        if not t["words"] and not t["about"] and not t["needs"] and not t["mentions"]:
            problems.append(f"lore: {tid} は words も about も needs も mentions も無い(拾えない)")
        if t["prefix"] is not None and t["prefix"] not in data.prefix:
            problems.append(f"lore: {tid} の prefix {t['prefix']} が lore_talk.json に無い")
    for g in data.groups():
        rows = data.stages(g)
        if [t["stage"] for t in rows] != list(range(len(rows))):
            problems.append(f"lore: group {g} の stage が 0 から続いていない")
        for lo, hi in zip(rows, rows[1:]):
            if not set(lo["requires"]) <= set(hi["requires"]):
                problems.append(f"lore: {hi['id']} の requires が下の段 {lo['id']} の分を含んでいない")
    _check_shared(data, problems)
    intents = {norm(w) for w in intent_words}
    choice_words = {norm(w): c["id"] for c in data.choices for w in c["words"]}
    for w, g in data.words():
        key = norm(w)
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
    """about か mentions にその名前(英名)がある話の 0段目(group ごとに1つ。ファイルの並び)"""
    key = norm(en)
    return [data.stages(g)[0] for g in data.groups() if any(norm(a) == key for t in data.stages(g) for a in t["about"] + t["mentions"])]


def system_names(data: LoreData | None) -> list[str]:
    """system の話の about に書いた名前(英名。重なりを除いてファイルの並び)。Q&A の索引に足す(ドロップ表に無い MOD も拾える)"""
    out: dict[str, str] = {}
    for t in data.topics if data else []:
        if t["type"] == "system":
            for a in t["about"]:
                out.setdefault(norm(a), a)
    return list(out.values())


def needs_names(data: LoreData | None) -> list[str]:
    """needs のある話の about に書いた名前(英名。重なりを除いてファイルの並び)"""
    out: dict[str, str] = {}
    for t in data.needs_topics() if data else []:
        for a in t["about"]:
            out.setdefault(norm(a), a)
    return list(out.values())


def index_names(data: LoreData | None) -> list[str]:
    """Q&A の索引に足す名前: system の about(system_names)+ needs のある話の about(needs_names)+ 全部の話の mentions。重なりを除く"""
    out: dict[str, str] = {}
    mentions = [a for t in data.topics for a in t["mentions"]] if data else []
    for a in system_names(data) + needs_names(data) + mentions:
        out.setdefault(norm(a), a)
    return list(out.values())


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
