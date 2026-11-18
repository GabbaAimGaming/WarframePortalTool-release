"""Q&A(LLM なし版)の入口: 質問に答える(answer・answer_query)。**日本語のみ**。

判定は段の関数の並び(_STEPS。前から試して答えを返した段で終わる。段どうしで使う値は _Ask)。中身は役割ごとのファイル:
- 同梱データ(intents・answers・miss)= core.qadata / 名前の索引・聞きたいこと = core.qaindex
- 聞き方と答えの材料(QaQuery・QaContext・答えのひな形)= core.qacontext
- 項目ごとの答え(数値・入手先・ビルド・Helminth)= core.qafacts / 解説と話の選び方 = core.qaloreask
- 判定の順番: ボタンの menu id → talk id → 話の語 → 呼びかけ → ボタンの lore id → 名前 + needs → 解説の語 →
  MOD の名前(聞きたいこと・選択肢の指定なし。system の話があればそれ)→ 名前 + 選択肢の語 → 名前なし(候補)→
  名前だけ(選択肢を出す)→ 名前 + 聞きたいこと。解説は 0段目から進み具合の段までまとめて出す。
  クエストの中身は、未完了なら話す前に確認する(spoil で確認を飛ばす)
"""
from __future__ import annotations

from wfp.core.text import norm
from wfp.core.qacontext import QaContext, QaQuery, miss_answer, new_result
from wfp.core.qafacts import HANDLERS, field_answer, helminth_self
from wfp.core.qaindex import QaIndex, find_intents, options
from wfp.core.qaloreask import (lore_answer, lore_choice, lore_group, lore_needs, lore_options, lore_pick, lore_system,
                                talk_topic)
from wfp.core.qalore import pick_line, pick_stage, topics_about
from wfp.core.devbuilds import dev_frame_buttons
from wfp.core.qamenu import menu_answer, menu_rest
from wfp.core.qatalk import talk_answer

# 名前だけで聞きたいことが無いとき、その種類しか無ければこれに答える
_DEFAULT_INTENT = {"ability": "helminth", "hframe": "helminth", "devbuild": "build"}
# 時代ごとのレリックの名前だけのときに答える聞きたいこと
_RELIC_INTENT = "sources"


def answer(ctx: QaContext, question: str = "", name: str | None = None, intent: str | None = None,
           lore: str | None = None, spoil: bool = False, choice: str | None = None, only: bool = False,
           menu: str | None = None, talk: str | None = None) -> dict:
    """質問に答える。name(索引のキー)・intent(質問の id)を渡すと、文から拾わずにそれで答える(ボタンから)。
    lore(解説の id)・choice(解説の選択肢の id。name と一緒に)もボタンから。spoil はネタバレの確認を飛ばす(「聞く」のボタン)。
    解説は 0段目からその段までをまとめて出す(parts)。only はその段だけ(「続き」のボタン。上の段はもう出ているため)。
    menu(「教えてクロちゃん」の分類の id。QA_MENU_TOP で分類の一覧)・talk(ツールの使い方・雑談の話の id)もボタンから。
    文に話の語が当たれば話(呼びかけより先。「クロちゃんって何者?」)、文が呼びかけの語だけならメニューを出す。

    返り値: {q, type: answer|miss|options(名前だけ)|lore|spoiler_ask|menu|talk, name, intent, text, facts: [{label, value}], sources: [{title, rows}],
            builds: [build_view], options: [{label, name, intent} か {label, name, choice} か {label, lore} か {label, menu} か {label, q} か {label, talk} か {label, page}],
            candidates: [{key, en, ja}], basis, miss: {kind, id, text},
            lore: {id, title, group, stage, parts: [{id, title, stage, prefix, paragraphs}], source, credit, license},
            spoiler: {id, title, quests, ok, ng, declined, only}, next: {id, title, label}, menu: {id, title},
            talk: {id, type, title, paragraphs}}
    """
    return answer_query(ctx, QaQuery(question, name=name, intent=intent, lore=lore, spoil=spoil, choice=choice,
                                     only=only, menu=menu, talk=talk))


def answer_query(ctx: QaContext, query: QaQuery) -> dict:
    """聞き方をまとめた QaQuery で答える(answer の中身。API・CLI はこちらを使う)"""
    ask = _Ask(ctx, query)
    for step in _STEPS:
        out = step(ask)
        if out is not None:
            return out
    raise AssertionError("_STEPS の最後の段は必ず答えを返す")


class _Ask:
    """answer の1回分の入れ物。段(_STEPS)どうしで使い回す値は、初めて使うときに1回だけ作る"""

    def __init__(self, ctx: QaContext, query: QaQuery):
        self.ctx, self.query = ctx, query
        self.question, self.name, self.intent, self.lore = query.question, query.name, query.intent, query.lore
        self.spoil, self.choice, self.only, self.menu, self.talk = query.spoil, query.choice, query.only, query.menu, query.talk
        self.data, self.lore_data = ctx.data, ctx.lore
        self.res = new_result(self.question, None, None)  # 名前を拾う前の答え(段 0〜3)
        self.free = query.free  # ボタンからの指定が無い(文だけで聞かれた)
        self._found = self._named = self._heads = self._picked = self._usable = self._lore_opts = None

    @property
    def found(self) -> tuple[dict | None, dict]:
        """(拾った名前, 名前を除いた文)。ボタンの name があればそれ"""
        if self._found is None:
            if self.name is not None:
                self._found = (self.ctx.index.entities.get(norm(self.name)), {"norm": "", "spaced": "", "hit_len": 0})
            else:
                self._found = self.ctx.index.find(self.question)
        return self._found

    @property
    def e(self) -> dict | None:
        return self.found[0]

    @property
    def rest(self) -> dict:
        return self.found[1]

    @property
    def named(self) -> dict:
        """名前つきの答え(段 4 から。段どうしで同じものを使う)"""
        if self._named is None:
            self._named = new_result(self.question, self.e, None)
        return self._named

    @property
    def heads(self) -> list[dict]:
        """拾った名前の解説の見出し"""
        if self._heads is None:
            self._heads = topics_about(self.lore_data, self.e["en"]) if (self.lore_data and self.e) else []
        return self._heads

    @property
    def picked(self) -> list[dict]:
        """聞きたいこと(ボタンの intent か、名前を除いた文から)"""
        if self._picked is None:
            it = self.data.intent(self.intent) if self.intent else None
            self._picked = [it] if it else find_intents(self.data, self.rest)
        return self._picked

    @property
    def usable(self) -> list:
        """聞きたいことのうち名前の種類に合うもの。聞きたいことが無ければ種類の既定(_DEFAULT_INTENT・レリック)"""
        if self._usable is None:
            e, picked, data = self.e, self.picked, self.data
            kinds = QaIndex.kinds(e)
            usable = [it for it in picked if kinds & set(it["kinds"])]
            if not usable and not picked and len(kinds - {"item"}) == 1 and (only := next(iter(kinds - {"item"}))) in _DEFAULT_INTENT:
                usable = [data.intent(_DEFAULT_INTENT[only])]
            elif not usable and not picked and e["relic"]:  # レリックは入手先しか聞けないので、名前だけでも入手先を答える
                usable = [data.intent(_RELIC_INTENT)]
            self._usable = usable
        return self._usable

    @property
    def lore_opts(self) -> list[dict]:
        if self._lore_opts is None:
            self._lore_opts = lore_options(self.lore_data, self.e, self.heads)
        return self._lore_opts


# 判定の段。前から試し、答え(dict)を返した段で終わる(None なら次の段へ)。地図 §2 の Q&A の判定の順番と同じ並び

def _step_menu_button(a: _Ask) -> dict | None:
    """0. ボタンから(メニューの分類の id。自動のボタン = 開発者のビルドがあるフレーム)"""
    if a.menu is None:
        return None
    ctx = a.ctx
    auto = {"dev_frames": dev_frame_buttons(ctx.dev)}
    return (menu_answer(ctx.menu, a.res, a.menu, ctx.rng, auto) if ctx.menu else None) or miss_answer(ctx, a.res, "no_hit")


def _step_talk_button(a: _Ask) -> dict | None:
    """0. ボタンから(話の id)"""
    if a.talk is None:
        return None
    ctx = a.ctx
    return (talk_answer(ctx.talk, a.res, a.talk, ctx.rng) if ctx.talk else None) or miss_answer(ctx, a.res, "no_hit")


def _step_talk_words(a: _Ask) -> dict | None:
    """0. 話の語(ツールの使い方・雑談。呼びかけより先。「クロちゃんって何者?」)"""
    if not (a.free and a.ctx.talk):
        return None
    tid = talk_topic(a.ctx, a.question)
    return talk_answer(a.ctx.talk, a.res, tid, a.ctx.rng) if tid else None


def _step_call(a: _Ask) -> dict | None:
    """0. 呼びかけ(「教えてクロちゃん」)。語だけならメニュー、後ろに質問が続けば語を除いて答える(q は元の文)"""
    if not a.free:
        return None
    rest_q = menu_rest(a.ctx.menu, a.question)
    if rest_q == "":
        return menu_answer(a.ctx.menu, a.res, rng=a.ctx.rng)
    if rest_q:
        out = answer(a.ctx, rest_q, spoil=a.spoil)
        out["q"] = a.question
        return out
    return None


def _step_lore_button(a: _Ask) -> dict | None:
    """1. ボタンから(解説の id)"""
    if a.lore is None:
        return None
    t = a.lore_data.topic(a.lore) if a.lore_data else None
    return lore_answer(a.ctx, a.res, t, a.spoil, a.only) if t else miss_answer(a.ctx, a.res, "no_hit")


def _step_lore_needs(a: _Ask) -> dict | None:
    """2. needs(「Jade の強いビルド」「武器の強いビルド」)"""
    if not (a.free and a.lore_data):
        return None
    return lore_needs(a.ctx, new_result(a.question, a.e, None), a.e, a.rest, a.spoil) or None


def _step_lore_words(a: _Ask) -> dict | None:
    """3. 解説の語。shared の語で2つ以上の話に当たったらタイトルのボタン(「Vox Solaris」)"""
    if not (a.name is None and a.intent is None and a.lore_data):
        return None
    groups = lore_group(a.lore_data, a.question, a.rest)
    if len(groups) == 1:
        return lore_answer(a.ctx, a.res, pick_stage(a.lore_data, groups[0], a.ctx.done), a.spoil)
    if groups:
        return lore_pick(a.ctx, a.res, [a.lore_data.stages(g)[0] for g in groups])
    return None


def _step_mod_system(a: _Ask) -> dict | None:
    """4a. MOD の名前だけ(「Serration」「Serrationとは」)なら仕組みの解説に直行"""
    if not (a.e and a.e["mod"] and a.heads and a.intent is None and a.choice is None and not a.picked):
        return None
    return lore_system(a.ctx, a.named, a.heads, a.spoil) or None


def _step_lore_choice(a: _Ask) -> dict | None:
    """4. 名前 + 選択肢の語(「Excalibur Umbra の設定」)"""
    if not a.heads:
        return None
    if a.choice:
        ch = a.lore_data.choice(a.choice)
    else:
        ch = None if a.intent else lore_choice(a.lore_data, a.rest)
    if not ch:
        return None
    hits = [h for h in a.heads if h["type"] in ch["types"]]
    if len(hits) == 1:
        return lore_answer(a.ctx, a.named, pick_stage(a.lore_data, hits[0]["group"], a.ctx.done), a.spoil)
    if hits:
        return lore_pick(a.ctx, a.named, hits)
    return None


def _step_no_name(a: _Ask) -> dict | None:
    """名前が無い: 候補を出す(「Helminth のアビリティは?」は Helminth 自身。Helminth は名前として拾わない)"""
    if a.e is not None:
        return None
    res, picked = a.named, a.picked
    if any(it["id"] == "helminth" for it in picked):
        return helminth_self(a.ctx, res)
    stop = {w for it in a.data.intents for w in it["words"]}
    res["candidates"] = a.ctx.index.candidates(a.question, stop)
    if picked:
        res["intent"] = picked[0]["id"]
    return miss_answer(a.ctx, res, "no_name")


def _step_name_only(a: _Ask) -> dict | None:
    """6. 名前だけ: 解説の選択肢(中身のあるものだけ)+ 聞けること。聞きたいことが名前の種類に合わなければヒットなし"""
    if a.usable and a.usable[0] is not None:
        return None
    res, e = a.named, a.e
    res["options"] = a.lore_opts + options(a.data, e)
    res["options_title"] = pick_line(a.lore_data, "ask_what", a.ctx.rng, name=e["ja"]) if a.lore_opts else ""
    res["options_title"] = res["options_title"] or a.data.say("options", name=e["ja"])
    if not a.picked:  # 聞けることの見出しだけ出す(ヒットしなかったときの文は重ねない)
        res["type"] = "options"
        return res
    return miss_answer(a.ctx, res, "no_intent", e["ja"])  # 例: フレームのクリ率


def _step_intent(a: _Ask) -> dict:
    """5. 名前 + 聞きたいこと(項目ごとの HANDLERS。無ければ数値の field_answer)"""
    res, e, it = a.named, a.e, a.usable[0]
    res["intent"] = it["id"]
    out = HANDLERS.get(it["id"], field_answer)(a.ctx, res, e, it)
    out["options"] = a.lore_opts + [o for o in options(a.data, e) if o["intent"] != it["id"]]
    if out["options"]:
        out["options_title"] = a.data.say("options", name=e["ja"])
    return out


_STEPS = (_step_menu_button, _step_talk_button, _step_talk_words, _step_call, _step_lore_button,
          _step_lore_needs, _step_lore_words, _step_mod_system, _step_lore_choice, _step_no_name,
          _step_name_only, _step_intent)
