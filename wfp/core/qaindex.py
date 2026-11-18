"""Q&A の名前の索引(QaIndex)と聞きたいことの判定(find_intents・options)・語の当たり(word_hit)。

- 名前の索引: フレーム・武器・アビリティ(builder.json)、アイテム(ドロップ表)、吸収一覧のアビリティとフレーム、
  開発者のビルドの名前と対象。英名・和名のどちらでも拾う(norm で比べる。英字は単語の途中では当てない)。長い名前を優先
- 聞きたいこと: data/qa/intents.json のキーワード。名前の部分を除いた文から探す(「Helminth Charger」の helminth を拾わない)
"""
from __future__ import annotations

import difflib
import re

from wfp.core.text import norm, spaced
from wfp.core.const import QA_CANDIDATE_LIMIT, QA_MIN_ASCII, QA_MIN_LABEL, QA_RELIC_WORDS, ERA_JA
from wfp.core.devbuilds import variant_base
from wfp.core.qadata import QaData

_ASCII_ALNUM = re.compile(r"[a-z0-9]")
# 拾えなかったときの候補探し: 英字の語・カタカナの語
_ASCII_WORD_RE = re.compile(r"[a-z][a-z0-9]*")
_KANA_RE = re.compile(r"[ァ-ヶー]{2,}")
# 名前の種類の優先(候補の並び)
_KIND_ORDER = {k: i for i, k in enumerate(("frame", "summon", "weapon", "hframe", "ability", "devbuild", "item"))}


# --------------------------------------------------------------------------
# 名前の索引
# --------------------------------------------------------------------------

def _is_ascii(s: str) -> bool:
    return s.isascii()


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
    レリックは1個ずつ(Lith A1 Relic)ではなく時代ごとの名前(Lith Relic。relic = 時代のキー)にまとめ、時代の名前だけ(Lith)も別名(aliases)で拾う。
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
        self._relic_keys: list[str] = []  # 時代ごとのレリックのキー(ERA_JA の並び。候補に出す)
        for n in items:
            base = names.split_qty(n)[1]
            if era_code := names.relic_era(base):
                self._relic_entity(era_code[0])
                continue
            self._entity(base, names.ja(base))["item"] = True
        self._relic_keys.sort(key=lambda k: list(ERA_JA).index(self.entities[k]["relic"]))
        for b in dev:
            self._entity(b["name"], None)["devbuild"] = True
            self._entity(b["target"], names.ja(b["target"]))["devbuild"] = True
            if base := variant_base(b["target"]):  # 基本の名前(Ash)でも派生(Ash Prime)のビルドを聞ける
                self._entity(base, names.ja(base))["devbuild"] = True
        for n in lore_names or []:
            self._entity(n, names.ja(n))
        stop = {norm(w) for w in stop_words or ()}
        for key, e in self.entities.items():
            for label in {e["en"], e["ja"], *e["aliases"]}:
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
                                      "mod": self.names.is_mod(en), "relic": None, "aliases": []}
        elif e["ja"] == e["en"] and ja != en:
            e["ja"] = ja
        return e

    def _relic_entity(self, era: str) -> dict:
        """時代ごとのレリックの名前(英名「Lith Relic」・和名「Lith レリック」・別名「Lith」)。種類は item"""
        e = self._entity(f"{era} Relic", f"{ERA_JA[era]} レリック")
        if e["relic"] is None:
            e.update(item=True, relic=era, aliases=sorted({era, ERA_JA[era]}))
            self._relic_keys.append(e["key"])
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
        # 「レリック」だけで時代が無ければ、時代ごとのレリックを先に(Lith → Meso → Neo → Axi …)
        forms = {"norm": norm(question), "spaced": spaced(question)}
        if any(_bounded(forms["spaced" if _is_ascii(w) else "norm"], norm(w), _is_ascii(w)) >= 0 for w in QA_RELIC_WORDS):
            relics = [self.entities[k] for k in self._relic_keys]
            ents = relics + [e for e in ents if not e["relic"]]
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


def word_hit(forms: dict, word: str) -> int:
    """文(norm・spaced の形)に語が当たれば語の長さ、当たらなければ 0(英字の語は spaced の文で単語として)"""
    ascii_word = _is_ascii(norm(word))
    return len(_key(word)) if _bounded(forms["spaced" if ascii_word else "norm"], _key(word), ascii_word) >= 0 else 0
