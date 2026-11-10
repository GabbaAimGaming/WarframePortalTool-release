"""画面の文字(テキスト指定)と日本語の文: txt name_txt・render_txt render_ja・ja_text(web/i18n/ja.json を読む ja_table)・表示名の表 JA_TABLES。

API は日本語の文を作らず、テキスト指定を返して画面が web/i18n の表で文にする。CLI・API のエラー文は同じ ja.json で日本語にする。
2026-11-10 に core/common から分けた(D2)。import してよい wfp は core.const だけ
"""
from __future__ import annotations

import json
import re

from wfp.core import const
from wfp.core.const import (
    ARCANE_CATS, AREA_KINDS, BARO_CHECK_BY, BARO_KINDS, BOUNTY_JA, BUILD_TYPES, CAMBION, CLAN_LABS, COMPAT_JA,
    CYCLES, CYCLE_SOURCES, ERA_JA, EXPORT_SRC_GITHUB, EXPORT_SRC_OFFICIAL, FACTIONS_JA, MASTERY_CATS, MODES_JA,
    MOD_GROUPS, MOD_TYPES, PLANETS_JA, QUEST_CATS, QUEST_STATES, RARITY_JA, RELIC_STATE_JA, RIVEN_TYPES_JA,
    SIM_CATS, SIM_DAMAGE_TYPES, SIM_RIVEN_GROUPS, SIM_STATS, SOURCE_CATS,
)


# ---------- 画面の文字(テキスト指定) ----------
# API は日本語の文を作らず、「テキスト指定」を返して画面(web/i18n の表)で文にする。形は次のどれか:
#   文字列            そのまま出す(敵の名前・ノード名などの固有名詞)
#   リスト            各要素を文にして list.sep でつなぐ
#   {"k", "v", "d"}  表のキー k の文の {名前} を v の値(テキスト指定)で置き換える。k が表に無ければ d(無ければ k)
#   {"l": {言語: 文}} 同梱データに言語ごとに書いた文(クエスト名など)。表示中の言語、無ければ ja、en の順
# CLI・API のエラー文は日本語で出すので、テキスト指定を render_ja で文にする。日本語の文は画面と同じ web/i18n/ja.json を読む(ja_text)。
# 表示名の表(JA_TABLES。惑星・ミッションの種類など)は core/const の表がもとで、Python でもキーの並び・CLI・名前の検索に使うので残し、
# web/i18n/ja.json と一致することを tests/test_i18n_text.py が確かめる(どちらかだけ直すと落ちる)
_JA_CACHE: dict = {}  # ja.json のパス -> {キー: 文}(読めたときだけ覚える)


def ja_table() -> dict[str, str]:
    """画面の文字の日本語の表(web/i18n/ja.json)。最初の1回だけ読んで覚える。読めなければ空(キーやそのままの文で出る。止めない)"""
    path = const.APP_DIR / const.WEB_DIR / const.I18N_DIR / f"{const.I18N_BASE}.json"
    table = _JA_CACHE.get(path)
    if table is None:
        try:
            table = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(table, dict):
            return {}
        _JA_CACHE[path] = table
    return table


# キーの頭 -> {キーの残り: 日本語}。表示名の表をそのまま画面の文字として使う
JA_TABLES = {
    "planet.": PLANETS_JA, "mode.": MODES_JA, "faction.": FACTIONS_JA, "rarity.": RARITY_JA, "src.cat.": SOURCE_CATS, "area.kind.": AREA_KINDS, "bounty.": BOUNTY_JA,
    "relic.era.": ERA_JA, "relic.state.": RELIC_STATE_JA, "clan.lab.": {k: v[1] for k, v in CLAN_LABS.items()},
    "mod.type.": MOD_TYPES, "mod.compat.": COMPAT_JA, "mod.group.": MOD_GROUPS, "mastery.cat.": MASTERY_CATS, "arcane.cat.": ARCANE_CATS,
    "quest.cat.": QUEST_CATS, "quest.state.": QUEST_STATES,
    "mastery.variant.": {"primary": "プライマリ", "secondary": "セカンダリ"},
    "baro.kind.": BARO_KINDS, "baro.check.": BARO_CHECK_BY,
    "riven.type.": RIVEN_TYPES_JA, "build.type.": BUILD_TYPES,
    "cycle.name.": {k: c["name"] for k, c in CYCLES.items()},
    "cycle.phase.": {p[0]: p[1] for c in CYCLES.values() for p in c["phases"]},
    "cycle.cambion.": CAMBION, "cycle.src.": CYCLE_SOURCES,
    "export.src.": {EXPORT_SRC_GITHUB: EXPORT_SRC_GITHUB, EXPORT_SRC_OFFICIAL: EXPORT_SRC_OFFICIAL},
    "sim.dmg.": SIM_DAMAGE_TYPES, "sim.cat.": SIM_CATS, "sim.group.": SIM_RIVEN_GROUPS, "sim.stat.": SIM_STATS,
}


def txt(key: str, default: str | None = None, **values) -> dict:
    """テキスト指定 {"k", "v", "d"} を作る(値はテキスト指定。数は書式を決めた文字列で渡す)"""
    out: dict = {"k": key}
    if values:
        out["v"] = values
    if default is not None:
        out["d"] = default
    return out


def name_txt(prefix: str, key: str) -> dict | str:
    """表示名の表にある名前(惑星・ミッションの種類など)のテキスト指定。表に無い名前はそのまま出す"""
    return txt(prefix + key, key) if key else ""


def ja_text(key: str) -> str | None:
    """キーの日本語(web/i18n/ja.json・JA_TABLES)。無ければ None"""
    text = ja_table().get(key)
    if isinstance(text, str):
        return text
    for head, table in JA_TABLES.items():
        if key.startswith(head) and key[len(head):] in table:
            return table[key[len(head):]]
    return None


def render_txt(x, lookup=ja_text, lang: str = "ja") -> str:
    """テキスト指定を文にする(lookup はキー -> 文。既定は日本語)。画面の renderTxt と同じ決まり"""
    if x is None:
        return ""
    if isinstance(x, str):
        return x
    if isinstance(x, (int, float)):
        return f"{x:g}"
    if isinstance(x, list):
        return (lookup("list.sep") or ", ").join(render_txt(e, lookup, lang) for e in x)
    if isinstance(x, dict) and isinstance(x.get("l"), dict):
        by = x["l"]
        return next((by[c] for c in (lang, "ja", "en") if isinstance(by.get(c), str) and by[c]), "")
    if isinstance(x, dict) and isinstance(x.get("k"), str):
        tmpl = lookup(x["k"])
        if tmpl is None:
            return x["d"] if isinstance(x.get("d"), str) else x["k"]
        vals = x.get("v") or {}
        return re.sub(r"\{(\w+)\}", lambda m: render_txt(vals[m.group(1)], lookup, lang) if m.group(1) in vals else m.group(0), tmpl)
    return str(x)


def render_ja(x) -> str:
    """テキスト指定を日本語の文にする(CLI・並べ替え用)"""
    return render_txt(x)
