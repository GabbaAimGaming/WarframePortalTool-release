"""Q&A の聞き方(QaQuery)と答えに使うデータ(QaContext)・答えのひな形(new_result)・ヒットしなかったときの答え(miss_answer)"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from wfp.core.qadata import QaData, pick_miss
from wfp.core.qaindex import QaIndex
from wfp.core.qamenu import MenuData
from wfp.core.qatalk import TalkData
from wfp.core.qalore import LoreData


@dataclass
class QaQuery:
    """聞き方(answer の引数をまとめたもの)。空の文字列の指定は None にそろえる(API のクエリ・CLI の引数の空)

    question: 質問の文 / name: 索引のキー / intent: 質問の id / lore: 解説の id / spoil: ネタバレの確認を飛ばす /
    choice: 解説の選択肢の id / only: 解説のその段だけ / menu: 「教えてクロちゃん」の分類の id / talk: 使い方・雑談の話の id
    """
    question: str = ""
    name: str | None = None
    intent: str | None = None
    lore: str | None = None
    spoil: bool = False
    choice: str | None = None
    only: bool = False
    menu: str | None = None
    talk: str | None = None

    def __post_init__(self):
        self.question = self.question or ""
        for key in ("name", "intent", "lore", "choice", "menu", "talk"):  # id の項目
            setattr(self, key, getattr(self, key) or None)

    @property
    def free(self) -> bool:
        """ボタンからの指定が無い(文だけで聞かれた)"""
        return self.lore is None and self.name is None and self.intent is None and self.choice is None

    @property
    def empty(self) -> bool:
        """何も聞いていない(文も、文の代わりになるボタンの指定も無い)"""
        return not self.question.strip() and not (self.name or self.lore or self.menu or self.talk)


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
    menu: MenuData | None = None      # 「教えてクロちゃん」(core.qamenu。無ければ呼びかけに反応しない)
    talk: TalkData | None = None      # ツールの使い方・雑談(core.qatalk。無ければ話に反応しない)
    rng: random.Random | None = None


def new_result(question: str, e: dict | None = None, intent: str | None = None) -> dict:
    return {"q": question, "type": "answer", "name": {"key": e["key"], "en": e["en"], "ja": e["ja"]} if e else None,
            "intent": intent, "text": "", "facts": [], "sources": [], "builds": [], "options": [], "candidates": [],
            "options_title": "", "basis": "", "miss": None, "lore": None, "spoiler": None, "next": None, "menu": None,
            "talk": None}


def miss_answer(ctx: QaContext, res: dict, kind: str, name: str = "") -> dict:
    res.update(type="miss", miss=pick_miss(ctx.data, kind, name, ctx.rng))
    return res
