"""画面向け API: Q&A(LLM なし版。答えは日本語のみ)"""
from __future__ import annotations

from urllib.parse import unquote

from wfp.api.store import ApiError, Raw, Store
from wfp.core.archon import shard_list
from wfp.core.i18n import txt
from wfp.core.const import (
    DEV_BUILD_SUFFIX, QA_ANSWERS_FILE, QA_ICON_CACHE, QA_ICON_MENU, QA_ICON_MIME, QA_ICONS_FILE, QA_INTENTS_FILE,
    QA_LORE_FILE, QA_LORE_TALK_FILE, QA_MENU_FILE, QA_MISS_FILE, QA_TALK_FILE,
)
from wfp.core.devbuilds import dev_build_list
from wfp.core.helminth import subsume_list
from wfp.core.qa import QaContext, QaIndex, answer, load_qa_data, stop_words
from wfp.core.qaicon import icon_ext, icon_view, load_icons, safe_name, scene_of
from wfp.core.qalore import index_names, load_lore
from wfp.core.qamenu import load_menu
from wfp.core.qatalk import load_talk
from wfp.core.quests import check_flow
from wfp.core.summons import summon_list
from wfp.store import appdata, userdata

QA_QUESTION_MAX = 200  # 質問の文の長さの上限


def qa_context(store: Store) -> QaContext:
    """答えに使うデータ。同梱データは毎回読み(小さい・直せばすぐ反映)、名前の索引はデータが変わったときだけ作り直す"""
    data = load_qa_data(appdata.read_qa(QA_INTENTS_FILE), appdata.read_qa(QA_ANSWERS_FILE), appdata.read_qa(QA_MISS_FILE))
    builder = store.builder()
    drops, sources, names = store.drops(), store.sources(), store.names()
    items = store.all_items() if drops else []
    subsume = subsume_list(appdata.read_helminth())
    dev = dev_build_list(appdata.read_dev_builds())
    summons = summon_list(appdata.read_summons())
    stops = stop_words(data)
    lore = load_lore(appdata.read_qa(QA_LORE_FILE), appdata.read_qa(QA_LORE_TALK_FILE))  # 索引より先(system の about を名前に足す)
    lore_names = index_names(lore)
    stamp = (builder, names, items, repr(subsume), repr(dev), repr(summons), repr(sorted(stops)), repr(lore_names))
    index = store.derived("@qa", stamp, lambda: QaIndex(builder, names, items, subsume, dev, stops, summons, lore_names))
    quest_names = {q["id"]: q["ja"] for q in check_flow(appdata.read_quests()) if q["kind"] == "quest"}
    return QaContext(data, index, builder=builder, drops=drops, sources=sources, items=items, subsume=subsume,
                     archon=shard_list(appdata.read_archon()), dev=dev, mod_stats=store.mod_stats(),
                     lore=lore, done=userdata.load_quests_done(store.d), quest_names=quest_names,
                     menu=load_menu(appdata.read_qa(QA_MENU_FILE)), talk=load_talk(appdata.read_qa(QA_TALK_FILE)))


def ask(store: Store, q: str, name: str | None = None, intent: str | None = None, lore: str | None = None,
        spoil: bool = False, choice: str | None = None, only: bool = False, menu: str | None = None,
        talk: str | None = None) -> dict:
    """GET /api/qa: 質問(q)に答える。ボタンからは name(索引のキー)と intent(質問の id)・choice(解説の選択肢の id)、
    または lore(解説の id。spoil=1 でネタバレの確認を飛ばす・only=1 でその段だけ(「続き」))・menu(「教えてクロちゃん」の分類の id)・talk(使い方・雑談の話の id)で聞く。
    ビルドには、ビルド管理に追加するときの名前の初期値 adopt_name を付ける"""
    q = (q or "").strip()
    if not q and not name and not lore and not menu and not talk:
        raise ApiError(txt("err.qa.empty"))
    if len(q) > QA_QUESTION_MAX:
        raise ApiError(txt("err.qa.long", max=QA_QUESTION_MAX))
    res = answer(qa_context(store), q, name=name or None, intent=intent or None, lore=lore or None, spoil=spoil,
                 choice=choice or None, only=only, menu=menu or None,
                 talk=talk or None)
    for b in res["builds"]:
        b["adopt_name"] = b["name"] + DEV_BUILD_SUFFIX
    res["scene"] = scene_of(res)  # アイコンの場面(画面がその場面の画像から選ぶ)
    return res


def qa_icons() -> dict:
    """GET /api/qa/icons: アイコンの姿の一覧(icons.json が無い・壊れていれば空の一覧。Q&A はアイコンなしで動く)"""
    return icon_view(load_icons(appdata.read_qa(QA_ICONS_FILE)))


def qa_icon(rest: str) -> Raw:
    """GET /qa-icon/<姿>/<ファイル>・/qa-icon/menu: アイコンの画像。icons.json に載っているファイルだけ返す(ほかは 404)"""
    data = load_icons(appdata.read_qa(QA_ICONS_FILE))
    if rest == QA_ICON_MENU:
        set_id, name = (data.menu["set"], data.menu["file"]) if data.menu else ("", "")
    else:
        set_id, _, name = rest.partition("/")
    body = (appdata.read_qa_icon(set_id, name)
            if set_id and safe_name(name) and data.listed(set_id, name) else None)
    if body is None:
        raise ApiError(txt("err.image.none"), 404)
    return Raw(body, QA_ICON_MIME[icon_ext(name)], QA_ICON_CACHE)


ROUTES = {
    ("GET", "/api/qa"): lambda c: ask(c.store, c.q.get("q", ""), c.q.get("name"), c.q.get("intent"), c.q.get("lore"),
                                      c.flag("spoil"), c.q.get("choice"), c.flag("only"), c.q.get("menu"),
                                      c.q.get("talk")),
    ("GET", "/api/qa/icons"): lambda c: qa_icons(),
    ("GET", "/qa-icon/"): lambda c: qa_icon(unquote(c.path[len("/qa-icon/"):])),
}
