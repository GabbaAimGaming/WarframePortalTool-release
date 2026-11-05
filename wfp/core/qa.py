"""Q&A(LLM なし版): 質問の文から名前と聞きたいことを拾い、ポータルのデータから決まった文の型で答える。**日本語のみ**。

- 名前の索引(QaIndex): フレーム・武器・アビリティ(builder.json)、アイテム(ドロップ表)、吸収一覧のアビリティとフレーム、
  開発者のビルドの名前と対象。英名・和名のどちらでも拾う(norm で比べる。英字は単語の途中では当てない)。長い名前を優先
- 聞きたいこと: data/qa/intents.json のキーワード。名前の部分を除いた文から探す(「Helminth Charger」の helminth を拾わない)
- 答え: data/qa/answers.json の文の型に値を埋める。推測はしない。拾えなかったときは data/qa/miss.json の文をランダムに1つ
- 入手先は drops の find_sources、開発者のビルドは core.devbuilds、Helminth は core.helminth を使う
- 解説(設定・ストーリー・仕組み)は core.qalore(data/qa/lore.json)。判定の順番: ボタンの lore id → 名前 + needs →
  解説の語 →   MOD の名前(聞きたいこと・選択肢の指定なし。system の話があればそれ)→ 名前 + 選択肢の語 →
  名前 + 聞きたいこと → 名前だけ(選択肢を出す)。解説は 0段目から進み具合の段までまとめて出す。クエストの中身は、未完了なら話す前に確認する(spoil で確認を飛ばす)
"""
from __future__ import annotations

import difflib
import random
import re
import unicodedata
from dataclasses import dataclass, field

from wfp.core.common import (QA_CANDIDATE_LIMIT, QA_FORMATS, QA_KINDS, QA_MIN_ASCII, QA_MIN_LABEL, QA_MISS_KINDS,
                             QA_PART_SOURCE_LIMIT, QA_SOURCE_LIMIT, HELMINTH_FRAME, norm, render_ja)
from wfp.core.devbuilds import build_view, builds_for
from wfp.core.helminth import subsume_frame
from wfp.core.qalore import (LoreData, missing_quests, next_stage, pick_line, pick_prefix, pick_stage,
                             topics_about)
from wfp.drops.search import find_sources

_ASCII_ALNUM = re.compile(r"[a-z0-9]")
# 拾えなかったときの候補探し: 英字の語・カタカナの語
_ASCII_WORD_RE = re.compile(r"[a-z][a-z0-9]*")
_KANA_RE = re.compile(r"[ァ-ヶー]{2,}")
# Prime・Umbra は Helminth に食べさせられない(吸収一覧は基本のフレームの名前)
_VARIANT_RE = re.compile(r"\s+(Prime|Umbra)$", re.I)
# 名前の種類の優先(候補の並び)
_KIND_ORDER = {k: i for i, k in enumerate(("frame", "summon", "weapon", "hframe", "ability", "devbuild", "item"))}
# 名前だけで聞きたいことが無いとき、その種類しか無ければこれに答える
_DEFAULT_INTENT = {"ability": "helminth", "hframe": "helminth", "devbuild": "build"}


# --------------------------------------------------------------------------
# 同梱データ(data/qa/)
# --------------------------------------------------------------------------

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
        return _fill(self.text.get(key, ""), values)


def _fill(template: str, values: dict) -> str:
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
             "sources.parts", "build", "helminth.frame", "helminth.prime", "helminth.self", "helminth.ability", "helminth.not",
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
    return {"kind": kind, "id": m.get("id"), "text": _fill(m["ja"], {"name": name})}


# --------------------------------------------------------------------------
# 名前の索引
# --------------------------------------------------------------------------

def _is_ascii(s: str) -> bool:
    return s.isascii()


def spaced(s: str) -> str:
    """英字の照合用: norm と同じく小文字にして記号を除くが、空白(と - _)は1つの空白で残す(「rhino prime armor」の区切りを見るため)"""
    s = unicodedata.normalize("NFKC", s).lower()
    s = re.sub(r"['’,()（）・･]", "", s)
    return re.sub(r"[\s\-_]+", " ", s).strip()


def _key(label: str) -> str:
    """ラベルの照合の形: 英字だけなら spaced、ほかは norm"""
    return spaced(label) if _is_ascii(norm(label)) else norm(label)


def _cut(text: str, needle: str, ascii_word: bool) -> str:
    """text から needle(当たった名前)を1か所だけ「|」に置き換える(聞きたいことを名前の中から拾わないため)"""
    pos = _bounded(text, needle, ascii_word)
    return text if pos < 0 else text[:pos] + "|" + text[pos + len(needle):]


def _bounded(hay: str, needle: str, ascii_word: bool) -> int:
    """hay(norm 済み)の中の needle の位置(英字の語なら前後が英数字でないところだけ)。無ければ -1"""
    start = hay.find(needle)
    while start != -1:
        end = start + len(needle)
        if not ascii_word or ((start == 0 or not _ASCII_ALNUM.match(hay[start - 1]))
                              and (end == len(hay) or not _ASCII_ALNUM.match(hay[end]))):
            return start
        start = hay.find(needle, start + 1)
    return -1


class QaIndex:
    """名前の索引。entities = {キー(norm した英名): {key, en, ja, frame, weapon, summon, item, abilities, hframe, devbuild, mod}}

    frame・weapon は builder.json の行、summon は呼び出しの行(core.summons。フレームと同じ項目名)、
    abilities は [(持ち主の英名, アビリティの行)]、item・hframe・devbuild は真偽、mod は MOD の英名か(names.is_mod。種類ではなく印)。
    lore_names(解説の system と needs のある話の about の名前。core.qalore の index_names)も名前として拾う(ドロップ表に無い MOD など)。
    stop_words(聞きたいことの語)と同じ名前は拾わない(例: Helminth は「Helminth」の質問として扱う)
    """

    def __init__(self, builder: dict | None, names, items: list[str], subsume: list[dict], dev: list[dict],
                 stop_words: set[str] | None = None, summons: list[dict] | None = None, lore_names: list[str] | None = None):
        self.names = names
        self.entities: dict[str, dict] = {}
        self._labels: dict[str, set[str]] = {}  # norm したラベル -> キー
        builder = builder or {}
        for f in builder.get("frames") or []:
            e = self._entity(f["en"], f.get("ja"))
            e["frame"] = f
            for a in f.get("abilities") or []:
                ab = self._entity(a["en"], a.get("ja"))
                ab["abilities"].append((f["en"], a))
        for w in builder.get("weapons") or []:
            e = self._entity(w["en"], w.get("ja"))
            if e["weapon"] is None:
                e["weapon"] = w
        for sm in summons or []:
            self._entity(sm["en"], sm["ja"])["summon"] = sm
            for a in sm["abilities"]:
                self._entity(a["en"], a["ja"])["abilities"].append((sm["en"], a))
        for row in subsume:
            self._entity(row["ability"], None)["subsume"] = True
            fe = self._entity(row["frame"], None)
            if not fe["frame"]:
                fe["hframe"] = True
        for n in items:
            base = names.split_qty(n)[1]
            self._entity(base, names.ja(base))["item"] = True
        for b in dev:
            self._entity(b["name"], None)["devbuild"] = True
            self._entity(b["target"], names.ja(b["target"]))["devbuild"] = True
        for n in lore_names or []:
            self._entity(n, names.ja(n))
        stop = {norm(w) for w in stop_words or ()}
        for key, e in self.entities.items():
            for label in {e["en"], e["ja"]}:
                ln = norm(label)
                if len(ln) < (QA_MIN_ASCII if _is_ascii(ln) else QA_MIN_LABEL) or ln in stop:
                    continue
                self._labels.setdefault(_key(label), set()).add(key)

    def _entity(self, en: str, ja: str | None) -> dict:
        key = norm(en)
        ja = ja if ja and ja != en else self.names.ja(en)  # 和名が無ければ名前辞書から(それも無ければ英名)
        e = self.entities.get(key)
        if e is None:
            e = self.entities[key] = {"key": key, "en": en, "ja": ja, "frame": None, "weapon": None, "summon": None,
                                      "item": False, "abilities": [], "subsume": False, "hframe": False, "devbuild": False,
                                      "mod": self.names.is_mod(en)}
        elif e["ja"] == e["en"] and ja != en:
            e["ja"] = ja
        return e

    @staticmethod
    def kinds(e: dict) -> set[str]:
        """名前の種類(QA_KINDS のうち当てはまるもの)"""
        out = {k for k in ("frame", "weapon", "summon", "item", "hframe", "devbuild") if e[k]}
        if e["abilities"] or e["subsume"]:
            out.add("ability")
        return out

    def find(self, question: str) -> tuple[dict | None, dict]:
        """質問の文から名前を1つ(一番長く当たったもの。同じ長さなら種類の優先順・前にあるもの)。
        (名前, 名前の部分を除いた文 {"norm", "spaced", "hit_len"})。hit_len は当たったラベルの長さ(無ければ 0)。
        英字の名前は spaced の文で、ほかは norm の文で探す"""
        forms = {"norm": norm(question), "spaced": spaced(question)}
        best: tuple | None = None
        for ln, keys in self._labels.items():
            ascii_label = _is_ascii(ln)
            hay = forms["spaced" if ascii_label else "norm"]
            if len(ln) > len(hay) or (best and len(ln) < best[0]):
                continue
            pos = _bounded(hay, ln, ascii_label)
            if pos < 0:
                continue
            for key in keys:
                rank = min((_KIND_ORDER[k] for k in self.kinds(self.entities[key])), default=99)
                cand = (len(ln), -rank, -pos, key, ln)
                if best is None or cand[:4] > best[:4]:
                    best = cand
        if best is None:
            return None, {**forms, "hit_len": 0}
        e, ln = self.entities[best[3]], best[4]
        # 名前の部分を両方の形から除く(英字の名前は norm の形でも除く)
        rest = {"spaced": _cut(forms["spaced"], spaced(e["en"]) if _is_ascii(ln) else ln, _is_ascii(ln)),
                "norm": _cut(forms["norm"], norm(ln), _is_ascii(ln)), "hit_len": best[0]}
        return e, rest

    def candidates(self, question: str, stop_words: set[str] | None = None) -> list[dict]:
        """拾えなかったときの候補(英字の語は近い綴り、カタカナの語は前方一致・部分一致)。種類の優先順・短い名前順"""
        stop = {_key(w) for w in stop_words or ()}
        words = [w for w in _ASCII_WORD_RE.findall(spaced(question)) if w not in stop]
        ascii_tokens = [w for w in words if len(w) >= QA_MIN_ASCII] + [f"{a} {b}" for a, b in zip(words, words[1:])]
        kana_tokens = [t for t in (norm(x) for x in _KANA_RE.findall(norm(question))) if t not in stop]
        hits: set[str] = set()
        ascii_labels = [ln for ln in self._labels if _is_ascii(ln)]
        for tok in ascii_tokens:
            for ln in difflib.get_close_matches(tok, ascii_labels, n=QA_CANDIDATE_LIMIT, cutoff=0.75):
                hits |= self._labels[ln]
        for tok in kana_tokens:
            hits |= {k for ln, keys in self._labels.items() if not _is_ascii(ln) and tok in ln for k in keys}
        ents = [self.entities[k] for k in hits]
        ents.sort(key=lambda e: (min((_KIND_ORDER[k] for k in self.kinds(e)), default=99), len(e["en"]), e["en"]))
        return [{"key": e["key"], "en": e["en"], "ja": e["ja"]} for e in ents[:QA_CANDIDATE_LIMIT]]


# --------------------------------------------------------------------------
# 聞きたいことの判定
# --------------------------------------------------------------------------

def find_intents(data: QaData, forms: dict) -> list[dict]:
    """文(QaIndex.find の残り {norm, spaced})に語が当たった質問を、priority の大きい順・語の長い順に返す。
    英字の語は spaced の文で単語として、ほかは norm の文で探す"""
    hits: list[tuple] = []
    for it in data.intents:
        best = max((len(_key(w)) for w in it["words"]
                    if _bounded(forms["spaced" if _is_ascii(norm(w)) else "norm"], _key(w), _is_ascii(norm(w))) >= 0), default=0)
        if best:
            hits.append((it["priority"], best, it))
    hits.sort(key=lambda h: (h[0], h[1]), reverse=True)
    return [h[2] for h in hits]


def options(data: QaData, e: dict) -> list[dict]:
    """その名前について聞けること(ボタン)。開発者のビルドは、ある名前だけ。button: false の質問(個別の数値)は出さない"""
    kinds = QaIndex.kinds(e)
    out = []
    for it in data.intents:
        if not it["button"] or not kinds & set(it["kinds"]):
            continue
        if it["id"] == "build" and not e["devbuild"]:
            continue
        if it["id"] == "sources" and not (e["item"] or e["frame"] or e["weapon"]):
            continue
        out.append({"label": it["label"], "name": e["key"], "intent": it["id"]})
    return out


# --------------------------------------------------------------------------
# 答えの組み立て
# --------------------------------------------------------------------------

@dataclass
class QaContext:
    """答えに使うデータ(API・CLI が読んで渡す。builder.json は wfp の外の機能なので core では読まない)"""
    data: QaData
    index: QaIndex
    builder: dict | None = None
    drops: object = None              # drops.tables.Drops(無ければ None)
    sources: object = None            # drops.tables.Sources
    items: list[str] = field(default_factory=list)
    subsume: list[dict] = field(default_factory=list)
    archon: dict = field(default_factory=lambda: {"tauforged_rate": 1.5, "colors": []})
    dev: list[dict] = field(default_factory=list)
    mod_stats: object = None          # core.modstats.ModStats(ビルドの MOD の効果。無ければ名前だけ)
    lore: LoreData | None = None      # 解説(core.qalore。無ければ解説は出さない)
    done: set = field(default_factory=set)              # クエスト一覧で終えたクエストの id(quests_done.json)
    quest_names: dict = field(default_factory=dict)     # クエストの id -> 和名(ネタバレの確認の文に使う)
    rng: random.Random | None = None


def format_value(value: float, fmt: str) -> str:
    """数値の表示(QA_FORMATS)。整数なら小数点を付けない"""
    trim = lambda x: f"{round(x, 2):g}"
    if fmt == "pct":
        return f"{trim(value * 100)}%"
    if fmt == "mult":
        return f"x{trim(value)}"
    if fmt == "sec":
        return f"{trim(value)}秒"
    return trim(value)


def _result(question: str, e: dict | None = None, intent: str | None = None) -> dict:
    return {"q": question, "type": "answer", "name": {"key": e["key"], "en": e["en"], "ja": e["ja"]} if e else None,
            "intent": intent, "text": "", "facts": [], "sources": [], "builds": [], "options": [], "candidates": [],
            "options_title": "", "basis": "", "miss": None, "lore": None, "spoiler": None, "next": None}


def _miss(ctx: QaContext, res: dict, kind: str, name: str = "") -> dict:
    res.update(type="miss", miss=pick_miss(ctx.data, kind, name, ctx.rng))
    return res


def answer(ctx: QaContext, question: str = "", name: str | None = None, intent: str | None = None,
           lore: str | None = None, spoil: bool = False, choice: str | None = None, only: bool = False) -> dict:
    """質問に答える。name(索引のキー)・intent(質問の id)を渡すと、文から拾わずにそれで答える(ボタンから)。
    lore(解説の id)・choice(解説の選択肢の id。name と一緒に)もボタンから。spoil はネタバレの確認を飛ばす(「聞く」のボタン)。
    解説は 0段目からその段までをまとめて出す(parts)。only はその段だけ(「続き」のボタン。上の段はもう出ているため)。

    返り値: {q, type: answer|miss|options(名前だけ)|lore|spoiler_ask, name, intent, text, facts: [{label, value}], sources: [{title, rows}],
            builds: [build_view], options: [{label, name, intent} か {label, name, choice} か {label, lore}],
            candidates: [{key, en, ja}], basis, miss: {kind, id, text},
            lore: {id, title, group, stage, parts: [{id, title, stage, prefix, paragraphs}], source, credit, license},
            spoiler: {id, title, quests, ok, ng, declined, only}, next: {id, title, label}}
    """
    data, lore_data = ctx.data, ctx.lore
    res = _result(question, None, None)
    if lore is not None:  # 1. ボタンから(解説の id)
        t = lore_data.topic(lore) if lore_data else None
        return _lore_answer(ctx, res, t, spoil, only) if t else _miss(ctx, res, "no_hit")
    if name is not None:
        e, rest = ctx.index.entities.get(norm(name)), {"norm": "", "spaced": "", "hit_len": 0}
    else:
        e, rest = ctx.index.find(question)
    if name is None and intent is None and choice is None and lore_data:  # 2. needs(「Jade の強いビルド」「武器の強いビルド」)
        hit = _lore_needs(ctx, _result(question, e, None), e, rest, spoil)
        if hit:
            return hit
    if name is None and intent is None and lore_data:  # 3. 解説の語が当たった
        group = _lore_group(lore_data, question, rest)
        if group:
            return _lore_answer(ctx, res, pick_stage(lore_data, group, ctx.done), spoil)
    stop = {w for it in data.intents for w in it["words"]}
    res = _result(question, e, None)
    heads = topics_about(lore_data, e["en"]) if (lore_data and e) else []
    picked = [data.intent(intent)] if intent and data.intent(intent) else find_intents(data, rest)
    if e and e["mod"] and heads and intent is None and choice is None and not picked:  # 4a. MOD の名前(「Serration」「Serrationとは」)
        hit = _lore_system(ctx, res, heads, spoil)
        if hit:
            return hit
    ch = (lore_data.choice(choice) if choice else None if intent else _lore_choice(lore_data, rest)) if heads else None
    if ch:  # 4. 名前 + 選択肢の語(「Excalibur Umbra の設定」)
        hits = [h for h in heads if h["type"] in ch["types"]]
        if len(hits) == 1:
            return _lore_answer(ctx, res, pick_stage(lore_data, hits[0]["group"], ctx.done), spoil)
        if hits:
            return _lore_pick(ctx, res, hits)
    if e is None:
        if any(it["id"] == "helminth" for it in picked):  # 「Helminth のアビリティは?」(Helminth は名前として拾わない)
            return _helminth_self(ctx, res)
        res["candidates"] = ctx.index.candidates(question, stop)
        if picked:
            res["intent"] = picked[0]["id"]
        return _miss(ctx, res, "no_name")
    kinds = QaIndex.kinds(e)
    usable = [it for it in picked if kinds & set(it["kinds"])]
    if not usable and not picked and len(kinds - {"item"}) == 1 and (only := next(iter(kinds - {"item"}))) in _DEFAULT_INTENT:
        usable = [data.intent(_DEFAULT_INTENT[only])]
    lore_opts = _lore_options(lore_data, e, heads)
    if not usable or usable[0] is None:  # 6. 名前だけ: 解説の選択肢(中身のあるものだけ)+ 聞けること
        res["options"] = lore_opts + options(data, e)
        res["options_title"] = pick_line(lore_data, "ask_what", ctx.rng, name=e["ja"]) if lore_opts else ""
        res["options_title"] = res["options_title"] or data.say("options", name=e["ja"])
        if not picked:  # 名前だけ: 聞けることの見出しだけ出す(ヒットしなかったときの文は重ねない)
            res["type"] = "options"
            return res
        return _miss(ctx, res, "no_intent", e["ja"])  # 聞きたいことが名前の種類に合わない(例: フレームのクリ率)
    it = usable[0]  # 5. 名前 + 聞きたいこと
    res["intent"] = it["id"]
    handler = _HANDLERS.get(it["id"])
    if handler is None:
        handler = _field_answer
    out = handler(ctx, res, e, it)
    out["options"] = lore_opts + [o for o in options(data, e) if o["intent"] != it["id"]]
    if out["options"]:
        out["options_title"] = data.say("options", name=e["ja"])
    return out


# --------------------------------------------------------------------------
# 解説(設定・ストーリー。core.qalore)
# --------------------------------------------------------------------------

def _word_hit(forms: dict, word: str) -> int:
    """文(norm・spaced の形)に語が当たれば語の長さ、当たらなければ 0(英字の語は spaced の文で単語として)"""
    ascii_word = _is_ascii(norm(word))
    return len(_key(word)) if _bounded(forms["spaced" if ascii_word else "norm"], _key(word), ascii_word) >= 0 else 0


def _lore_word(lore: LoreData, forms: dict) -> tuple[int, str | None]:
    """解説の語が当たった (語の長さ, group)(一番長く当たった語。同じ長さならファイルの前のもの)。無ければ (0, None)"""
    best = max(((_word_hit(forms, w), -i, g) for i, (w, g) in enumerate(lore.words())), default=(0, 0, None))
    return (best[0], best[2]) if best[0] else (0, None)


def _lore_group(lore: LoreData, question: str, rest: dict) -> str | None:
    """解説の語で答える group。名前(QaIndex.find)が解説の語より長く当たったときは、名前の部分を除いた文で探し直す
    (例: 「オロキンセル」は名前 6 文字 > 解説の語「オロキン」4 文字なので、名前として答える)。
    同じ長さなら解説が先(名前と同じ語を解説に書いた場合)"""
    hit_len, group = _lore_word(lore, {"norm": norm(question), "spaced": spaced(question)})
    if group and rest.get("hit_len", 0) > hit_len:
        group = _lore_word(lore, rest)[1]
    return group


def _lore_choice(lore: LoreData, rest: dict) -> dict | None:
    """名前を除いた文に当たった選択肢(一番長く当たった語)。無ければ None"""
    best = max(((_word_hit(rest, w), -i, c["id"]) for i, c in enumerate(lore.choices) for w in c["words"]),
               default=(0, 0, None))
    return lore.choice(best[2]) if best[0] else None


def _lore_needs(ctx: QaContext, res: dict, e: dict | None, rest: dict, spoil: bool) -> dict | None:
    """needs のまとまりが全部当たった話(group ごと)。文は名前の部分を除いたもの(名前が無ければ文全体)。
    about に拾った名前がある話(名前つき)が当たればそれだけ、無ければ about が空の話(名前なし)から選ぶ。
    まとまりの数が一番多い話を出す。同じ数が2つ以上ならタイトルのボタン。当たらなければ None"""
    key = norm(e["en"]) if e else None
    named: dict[str, tuple[int, dict]] = {}
    free: dict[str, tuple[int, dict]] = {}
    for t in ctx.lore.needs_topics():
        if t["about"] and not any(norm(a) == key for a in t["about"]):
            continue
        if all(any(_word_hit(rest, w) for w in g) for g in t["needs"]):
            hits = named if t["about"] else free
            if t["group"] not in hits or len(t["needs"]) > hits[t["group"]][0]:
                hits[t["group"]] = (len(t["needs"]), t)
    hits = named or free
    if not hits:
        return None
    most = max(n for n, _ in hits.values())
    best = [t for n, t in hits.values() if n == most]
    if len(best) == 1:
        return _lore_answer(ctx, res, pick_stage(ctx.lore, best[0]["group"], ctx.done), spoil)
    return _lore_pick(ctx, res, best)


def _lore_options(lore: LoreData | None, e: dict, heads: list[dict]) -> list[dict]:
    """名前の解説の選択肢(ボタン)。その種類の話がある選択肢だけ(0段目の type で見る)"""
    if not lore or not heads:
        return []
    types = {h["type"] for h in heads}
    return [{"label": _fill(c["label"], {"name": e["ja"]}), "name": e["key"], "choice": c["id"]}
            for c in lore.choices if types & set(c["types"])]


def _lore_system(ctx: QaContext, res: dict, heads: list[dict], spoil: bool) -> dict | None:
    """MOD の名前で聞かれたとき(「Serration」「Serrationとは」): 選択肢を出さずに system の話へ直行。
    1つならその話・2つ以上(group が違う)なら選ぶボタン。system の話が無ければ None(今どおり選択肢)"""
    systems = [h for h in heads if h["type"] == "system"]
    if not systems:
        return None
    if len(systems) == 1:
        return _lore_answer(ctx, res, pick_stage(ctx.lore, systems[0]["group"], ctx.done), spoil)
    return _lore_pick(ctx, res, systems)


def _lore_pick(ctx: QaContext, res: dict, heads: list[dict]) -> dict:
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


def _lore_answer(ctx: QaContext, res: dict, t: dict, spoil: bool, only: bool = False) -> dict:
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


def _builder_basis(ctx: QaContext) -> str:
    return ctx.data.say("basis.builder", updated=str((ctx.builder or {}).get("updated") or "?")[:10])


def _stat_kind(e: dict, it: dict) -> str | None:
    """数値を引く行の種類: フレーム → 呼び出し → 武器 の順で、その質問が答えられるもの。無ければ None"""
    return next((k for k in ("frame", "summon", "weapon") if e[k] and k in it["kinds"]), None)


def _basis_of(ctx: QaContext, kind: str, rec: dict) -> str:
    """出典の文(呼び出しは同梱データの日付、ほかは builder.json の取得日)"""
    return ctx.data.say("basis.summon", as_of=rec.get("as_of") or "?") if kind == "summon" else _builder_basis(ctx)


def _field_answer(ctx: QaContext, res: dict, e: dict, it: dict) -> dict:
    """数値の項目1つ(フレームならフレームの値、無ければ武器の値)"""
    spec = ctx.data.fields.get(it["id"])
    if spec is None:
        return _miss(ctx, res, "no_hit", e["ja"])
    kind = _stat_kind(e, it)
    rec = e[kind] if kind else None
    if rec is None:
        return _miss(ctx, res, "no_data" if not ctx.builder else "no_hit", e["ja"])
    label = spec.get("label_melee", spec["label"]) if rec.get("cat") == "melee" else spec["label"]
    value = rec.get(it["id"])
    if not isinstance(value, (int, float)) or (kind == "weapon" and it["id"] in ("magazine", "reload") and not value):
        res["text"] = ctx.data.say("field.none", name=e["ja"], label=label)  # 無いことが答え(例: 近接の装填数)
        res["basis"] = _basis_of(ctx, kind, rec)
        return res
    res["text"] = ctx.data.say(f"field.{kind}", name=e["ja"], label=label, value=format_value(value, spec["fmt"]))
    res["basis"] = _basis_of(ctx, kind, rec)
    return res


def _stats(ctx: QaContext, res: dict, e: dict, it: dict) -> dict:
    kind = _stat_kind(e, it)
    if kind is None:
        return _miss(ctx, res, "no_data" if not ctx.builder else "no_hit", e["ja"])
    rec = e[kind]
    for k in ctx.data.order.get("weapon" if kind == "weapon" else "frame", []):  # 呼び出しはフレームと同じ項目
        spec, value = ctx.data.fields[k], rec.get(k)
        if isinstance(value, (int, float)) and (kind == "frame" or k not in ("magazine", "reload") or value):
            label = spec.get("label_melee", spec["label"]) if rec.get("cat") == "melee" else spec["label"]
            res["facts"].append({"label": label, "value": format_value(value, spec["fmt"])})
    res["text"] = ctx.data.say(f"stats.{kind}", name=e["ja"])
    res["basis"] = _basis_of(ctx, kind, rec)
    return res


def _abilities(ctx: QaContext, res: dict, e: dict, it: dict) -> dict:
    """アビリティの一覧。呼び出しは説明文の後ろに数値の行(「ドレイン: 25」など)を付ける"""
    kind = "frame" if e["frame"] else "summon" if e["summon"] else None
    if kind is None:
        return _miss(ctx, res, "no_data" if not ctx.builder else "no_hit", e["ja"])
    rec = e[kind]
    for a in rec.get("abilities") or []:
        label = a["ja"] if a["ja"] == a["en"] else f"{a['ja']}({a['en']})"
        lines = [a.get("desc") or ""] + [f"{v['label']}: {v['value']}" for v in a.get("values") or []]
        res["facts"].append({"label": label, "value": "\n".join(x for x in lines if x)})
    res["text"] = ctx.data.say("abilities", name=e["ja"])
    res["basis"] = _basis_of(ctx, kind, rec)
    return res


def _passive(ctx: QaContext, res: dict, e: dict, it: dict) -> dict:
    text = (e["frame"] or {}).get("passive")
    if not text:
        return _miss(ctx, res, "no_data" if not ctx.builder else "no_hit", e["ja"])
    res["facts"].append({"label": "", "value": text})
    res["text"] = ctx.data.say("passive", name=e["ja"])
    res["basis"] = _builder_basis(ctx)
    return res


def chance_text(chance: float) -> str:
    """入手先の確率(ドロップ表の値は % の単位)。画面の fmtPct と同じ桁: 1% 以上は小数2桁、0.01% 以上は3桁、それ未満は有効数字2桁"""
    if chance >= 1:
        return f"{chance:.2f}%"
    if chance >= 0.01:
        return f"{chance:.3f}%"
    return f"{chance:.2g}%"


def _source_rows(rows: list[dict], limit: int) -> list[dict]:
    out = []
    for r in rows[:limit]:
        where = " ".join(x for x in (render_ja(r["place"]), render_ja(r["detail"]) if r.get("detail") else "",
                                     render_ja(r["stage"]) if r.get("stage") else "") if x)
        chance = r.get("chance")
        out.append({"cat": r["cat"], "where": where, "qty": r.get("qty") or "",
                    "chance": "" if chance is None else chance_text(chance)})
    return out


def _sources(ctx: QaContext, res: dict, e: dict, it: dict) -> dict:
    if ctx.drops is None:
        return _miss(ctx, res, "no_data", e["ja"])
    names = ctx.index.names
    rows = find_sources(e["en"], ctx.drops, ctx.sources, names) if e["item"] else []
    if rows:
        res["sources"].append({"title": "", "rows": _source_rows(rows, QA_SOURCE_LIMIT)})
        res["text"] = ctx.data.say("sources", name=e["ja"], n=QA_SOURCE_LIMIT)
    else:
        owners = getattr(ctx.sources, "part_owner", None)
        parts = sorted({names.split_qty(n)[1] for n in ctx.items
                        if (hit := names.part_of(n, owners)) and norm(hit[0]) == e["key"] and norm(names.split_qty(n)[1]) != e["key"]})
        for part in parts:
            prow = find_sources(part, ctx.drops, ctx.sources, names)
            if prow:
                res["sources"].append({"title": names.ja(part), "rows": _source_rows(prow, QA_PART_SOURCE_LIMIT)})
        if not res["sources"]:
            return _miss(ctx, res, "no_hit", e["ja"])
        res["text"] = ctx.data.say("sources.parts", name=e["ja"], n=QA_PART_SOURCE_LIMIT)
    res["basis"] = ctx.data.say("basis.drops")
    return res


def _build(ctx: QaContext, res: dict, e: dict, it: dict) -> dict:
    hits = builds_for(ctx.dev, e["en"])
    if not hits:
        return _miss(ctx, res, "no_build", e["ja"])
    res["builds"] = [build_view(b, ctx.index.names, ctx.subsume, ctx.archon, ctx.mod_stats) for b in hits]
    as_of = max((b["as_of"] for b in hits if b.get("as_of")), default="?")
    res["text"] = ctx.data.say("build", as_of=as_of)
    res["basis"] = ctx.data.say("basis.dev", as_of=as_of)
    return res


def _helminth_self(ctx: QaContext, res: dict) -> dict:
    own = [r["ability"] for r in ctx.subsume if r["frame"] == HELMINTH_FRAME]
    if not own:
        return _miss(ctx, res, "no_hit", HELMINTH_FRAME)
    res.update(intent="helminth", text=ctx.data.say("helminth.self"), basis=ctx.data.say("basis.helminth"),
               facts=[{"label": a, "value": ""} for a in own])
    return res


def _helminth(ctx: QaContext, res: dict, e: dict, it: dict) -> dict:
    data = ctx.data
    res["basis"] = data.say("basis.helminth")
    if e["en"] == HELMINTH_FRAME:
        return _helminth_self(ctx, res)
    if e["frame"] or e["hframe"]:
        own = next((r["ability"] for r in ctx.subsume if norm(r["frame"]) == e["key"]), None)
        if own:
            res["text"] = data.say("helminth.frame", name=e["ja"], ability=own)
            return res
        base = _VARIANT_RE.sub("", e["en"])
        own = next((r["ability"] for r in ctx.subsume if norm(r["frame"]) == norm(base)), None) if base != e["en"] else None
        if own:
            res["text"] = data.say("helminth.prime", name=e["ja"], base=ctx.index.names.ja(base), ability=own)
            return res
    if e["subsume"] or e["abilities"]:
        owner = subsume_frame(ctx.subsume, e["en"])
        if owner:
            res["text"] = data.say("helminth.ability", ability=e["en"], frame=owner)
            return res
        frame = e["abilities"][0][0] if e["abilities"] else "?"
        res["text"] = data.say("helminth.not", ability=e["en"], frame=frame)
        return res
    return _miss(ctx, res, "no_hit", e["ja"])


_HANDLERS = {"stats": _stats, "abilities": _abilities, "passive": _passive, "sources": _sources, "build": _build,
             "helminth": _helminth}


def stop_words(data: QaData) -> set[str]:
    """名前として拾わない語(聞きたいことの語)"""
    return {w for it in data.intents for w in it["words"]}
