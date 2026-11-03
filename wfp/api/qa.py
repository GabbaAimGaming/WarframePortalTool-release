"""画面向け API: Q&A(LLM なし版。答えは日本語のみ)"""
from __future__ import annotations

import wfportal_builder as wb
from wfp.api.store import ApiError, Store
from wfp.core.archon import shard_list
from wfp.core.common import DEV_BUILD_SUFFIX, QA_ANSWERS_FILE, QA_INTENTS_FILE, QA_MISS_FILE, txt
from wfp.core.devbuilds import dev_build_list
from wfp.core.helminth import subsume_list
from wfp.core.qa import QaContext, QaIndex, answer, load_qa_data, stop_words
from wfp.core.summons import summon_list
from wfp.store import appdata

QA_QUESTION_MAX = 200  # 質問の文の長さの上限


def qa_context(store: Store) -> QaContext:
    """答えに使うデータ。同梱データは毎回読み(小さい・直せばすぐ反映)、名前の索引はデータが変わったときだけ作り直す"""
    data = load_qa_data(appdata.read_qa(QA_INTENTS_FILE), appdata.read_qa(QA_ANSWERS_FILE), appdata.read_qa(QA_MISS_FILE))
    builder = store._cached(wb.BUILDER_FILE, lambda: wb.load_builder_data(store.d))
    drops, sources, names = store.drops(), store.sources(), store.names()
    items = store.all_items() if drops else []
    subsume = subsume_list(appdata.read_helminth())
    dev = dev_build_list(appdata.read_dev_builds())
    summons = summon_list(appdata.read_summons())
    stops = stop_words(data)
    stamp = (id(builder), id(names), id(items), repr(subsume), repr(dev), repr(summons), repr(sorted(stops)))
    with store._lock:
        hit = store._cache.get("@qa")
    if hit and hit[0] == stamp:
        index = hit[1]
    else:
        index = QaIndex(builder, names, items, subsume, dev, stops, summons)
        with store._lock:
            store._cache["@qa"] = (stamp, index)
    return QaContext(data, index, builder=builder, drops=drops, sources=sources, items=items, subsume=subsume,
                     archon=shard_list(appdata.read_archon()), dev=dev, mod_stats=store.mod_stats())


def ask(store: Store, q: str, name: str | None = None, intent: str | None = None) -> dict:
    """GET /api/qa: 質問(q)に答える。ボタンからは name(索引のキー)と intent(質問の id)で聞く。
    ビルドには、ビルド管理に追加するときの名前の初期値 adopt_name を付ける"""
    q = (q or "").strip()
    if not q and not name:
        raise ApiError(txt("err.qa.empty"))
    if len(q) > QA_QUESTION_MAX:
        raise ApiError(txt("err.qa.long", max=QA_QUESTION_MAX))
    res = answer(qa_context(store), q, name=name or None, intent=intent or None)
    for b in res["builds"]:
        b["adopt_name"] = b["name"] + DEV_BUILD_SUFFIX
    return res


ROUTES = {
    ("GET", "/api/qa"): lambda c: ask(c.store, c.q.get("q", ""), c.q.get("name"), c.q.get("intent")),
}
