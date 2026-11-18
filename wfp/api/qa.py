"""画面向け API: Q&A(LLM なし版。答えは日本語のみ)"""
from __future__ import annotations

from urllib.parse import unquote

from wfp.api.store import ApiError, Raw, Store
from wfp.core.i18n import txt
from wfp.core.const import DEV_BUILD_SUFFIX, QA_ICON_CACHE, QA_ICON_MENU, QA_ICON_MIME, QA_ICONS_FILE, QA_QUESTION_MAX
from wfp.core.qa import answer_query
from wfp.core.qacontext import QaContext, QaQuery
from wfp.core.qabundle import build_context, index_stamp, load_qa_bundle, make_index
from wfp.core.qaicon import icon_ext, icon_view, load_icons, safe_name, scene_of
from wfp.store import appdata, userdata


def qa_context(store: Store) -> QaContext:
    """答えに使うデータ。同梱データは毎回読み(小さい・直せばすぐ反映)、名前の索引はデータが変わったときだけ作り直す"""
    bundle = load_qa_bundle()
    builder, names = store.builder(), store.names()
    drops, sources = store.drops(), store.sources()
    items = store.all_items()  # ドロップ表が無ければ空(キャッシュした同じリスト = 索引を作り直さない)
    stamp = index_stamp(bundle, builder, names, items)
    index = store.derived("@qa", stamp, lambda: make_index(bundle, builder, names, items))
    return build_context(bundle, index, builder=builder, drops=drops, sources=sources, items=items,
                         mod_stats=store.mod_stats(), done=userdata.load_quests_done(store.d))


def qa_query(c) -> QaQuery:
    """GET /api/qa のクエリから聞き方を作る(c は api/server の Request)。q は前後の空白を除く"""
    q = c.q.get
    return QaQuery((q("q") or "").strip(), name=q("name"), intent=q("intent"), lore=q("lore"), spoil=c.flag("spoil"),
                   choice=q("choice"), only=c.flag("only"), menu=q("menu"), talk=q("talk"))


def ask_query(store: Store, query: QaQuery) -> dict:
    """GET /api/qa: 質問(q)に答える。ボタンからは name(索引のキー)と intent(質問の id)・choice(解説の選択肢の id)、
    または lore(解説の id。spoil=1 でネタバレの確認を飛ばす・only=1 でその段だけ(「続き」))・menu(「教えてクロちゃん」の分類の id)・talk(使い方・雑談の話の id)で聞く。
    空・長すぎる質問は 400。ビルドには、ビルド管理に追加するときの名前の初期値 adopt_name を付ける"""
    if query.empty:
        raise ApiError(txt("err.qa.empty"))
    if len(query.question) > QA_QUESTION_MAX:
        raise ApiError(txt("err.qa.long", max=QA_QUESTION_MAX))
    res = answer_query(qa_context(store), query)
    for b in res["builds"]:
        b["adopt_name"] = b["name"] + DEV_BUILD_SUFFIX
    res["scene"] = scene_of(res)  # アイコンの場面(画面がその場面の画像から選ぶ)
    return res


def ask(store: Store, q: str = "", **kw) -> dict:
    """ask_query を文と名前つきの引数で呼ぶ(kw は QaQuery の項目。テスト・ほかの呼び出し用)"""
    return ask_query(store, QaQuery((q or "").strip(), **kw))


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
    ("GET", "/api/qa"): lambda c: ask_query(c.store, qa_query(c)),
    ("GET", "/api/qa/icons"): lambda c: qa_icons(),
    ("GET", "/qa-icon/"): lambda c: qa_icon(unquote(c.path[len("/qa-icon/"):])),
}
