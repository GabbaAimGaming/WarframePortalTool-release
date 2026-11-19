"""Q&A の答えに使うデータの組み立て(API と CLI で共通)。

同梱データ(data/ の JSON)はここでまとめて読む(毎回読む。小さい・直せばすぐ反映)。
ゲームのデータ(builder.json・ドロップ表・名前辞書・MOD 効果)の読み方と、名前の索引をキャッシュするかは
呼ぶ側が決める(API は Store のキャッシュと Store.derived、CLI はファイルから毎回)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from wfp.core.archon import shard_list
from wfp.core.const import (
    QA_ANSWERS_FILE, QA_INTENTS_FILE, QA_LORE_TALK_FILE, QA_MENU_FILE, QA_MISS_FILE, QA_TALK_FILE,
)
from wfp.core.devbuilds import dev_build_list
from wfp.core.helminth import subsume_list
from wfp.core.qacontext import QaContext
from wfp.core.qadata import QaData, load_qa_data, stop_words
from wfp.core.qaindex import QaIndex
from wfp.core.qalore import LoreData, index_names, load_lore
from wfp.core.qamenu import MenuData, load_menu
from wfp.core.qatalk import TalkData, load_talk
from wfp.core.quests import check_flow
from wfp.core.summons import summon_list
from wfp.store import appdata


@dataclass
class QaBundle:
    """同梱データから作ったもの一式(load_qa_bundle が作る)"""
    data: QaData
    lore: LoreData
    menu: MenuData
    talk: TalkData
    subsume: list[dict] = field(default_factory=list)       # Helminth の吸収一覧(core.helminth)
    dev: list[dict] = field(default_factory=list)           # 開発者のビルド(core.devbuilds)
    summons: list[dict] = field(default_factory=list)       # 呼び出し(core.summons)
    archon: dict = field(default_factory=dict)              # アルコンの欠片(core.archon)
    quest_names: dict = field(default_factory=dict)         # クエストの id -> 和名
    stops: set = field(default_factory=set)                 # 名前として拾わない語(聞きたいことの語)
    lore_names: list = field(default_factory=list)          # 索引に足す解説の名前(core.qalore の index_names)


def load_qa_bundle() -> QaBundle:
    """data/ の同梱データを読んで QaBundle にする。解説は索引に使う名前(lore_names)より先に読む"""
    data = load_qa_data(appdata.read_qa(QA_INTENTS_FILE), appdata.read_qa(QA_ANSWERS_FILE), appdata.read_qa(QA_MISS_FILE))
    lore = load_lore(appdata.read_qa_lore(), appdata.read_qa(QA_LORE_TALK_FILE))
    quests = check_flow(appdata.read_quests())
    return QaBundle(
        data=data, lore=lore,
        menu=load_menu(appdata.read_qa(QA_MENU_FILE)), talk=load_talk(appdata.read_qa(QA_TALK_FILE)),
        subsume=subsume_list(appdata.read_helminth()), dev=dev_build_list(appdata.read_dev_builds()),
        summons=summon_list(appdata.read_summons()), archon=shard_list(appdata.read_archon()),
        quest_names={q["id"]: q["ja"] for q in quests if q["kind"] == "quest"},
        stops=stop_words(data), lore_names=index_names(lore))


def index_stamp(bundle: QaBundle, builder, names, items) -> tuple:
    """名前の索引を作り直すかの印(Store.derived の stamp)。ゲームのデータは同じオブジェクトか、同梱データは中身で比べる"""
    return (builder, names, items, repr(bundle.subsume), repr(bundle.dev), repr(bundle.summons),
            repr(sorted(bundle.stops)), repr(bundle.lore_names))


def make_index(bundle: QaBundle, builder, names, items) -> QaIndex:
    """名前の索引(時間がかかるので API は Store.derived で包む)"""
    return QaIndex(builder, names, items, bundle.subsume, bundle.dev, bundle.stops, bundle.summons, bundle.lore_names)


def build_context(bundle: QaBundle, index: QaIndex, *, builder, drops, sources, items, mod_stats, done, vault=None) -> QaContext:
    """答えに使うデータ。QaContext を作るのはここだけ(API・CLI で項目がずれないように)。
    vault は Vault 入りの判定(drops.tables.Vault。無ければ入手先の答えで入手不可を言わない)"""
    return QaContext(bundle.data, index, builder=builder, drops=drops, sources=sources, vault=vault, items=items,
                     subsume=bundle.subsume, archon=bundle.archon, dev=bundle.dev, mod_stats=mod_stats,
                     lore=bundle.lore, done=done, quest_names=bundle.quest_names, menu=bundle.menu, talk=bundle.talk)
