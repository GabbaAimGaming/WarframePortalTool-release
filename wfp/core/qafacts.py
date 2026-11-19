"""Q&A の項目ごとの答え(数値・性能・アビリティ・パッシブ・入手先・レリック・開発者のビルド・Helminth)。
聞きたいことの id → 関数は HANDLERS(無い id は数値の field_answer)。入手先は drops の find_sources、
開発者のビルドは core.devbuilds、Helminth は core.helminth を使う。推測はしない
"""
from __future__ import annotations

import re

from wfp.core.common import fmt_jst
from wfp.core.i18n import render_ja
from wfp.core.text import norm
from wfp.core.const import QA_PART_SOURCE_LIMIT, QA_RELIC_SOURCE_LIMIT, QA_SOURCE_LIMIT, ERA_JA, HELMINTH_FRAME
from wfp.core.devbuilds import build_view, builds_for
from wfp.core.helminth import subsume_frame
from wfp.core.qacontext import QaContext, miss_answer
from wfp.drops.search import find_sources
from wfp.drops.tables import Vault

# Prime・Umbra は Helminth に食べさせられない(吸収一覧は基本のフレームの名前)
_VARIANT_RE = re.compile(r"\s+(Prime|Umbra)$", re.I)


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


def _builder_basis(ctx: QaContext) -> str:
    return ctx.data.say("basis.builder", updated=str((ctx.builder or {}).get("updated") or "?")[:10])


def _stat_kind(e: dict, it: dict) -> str | None:
    """数値を引く行の種類: フレーム → 呼び出し → 武器 の順で、その質問が答えられるもの。無ければ None"""
    return next((k for k in ("frame", "summon", "weapon") if e[k] and k in it["kinds"]), None)


def _basis_of(ctx: QaContext, kind: str, rec: dict) -> str:
    """出典の文(呼び出しは同梱データの日付、ほかは builder.json の取得日)"""
    return ctx.data.say("basis.summon", as_of=rec.get("as_of") or "?") if kind == "summon" else _builder_basis(ctx)


def field_answer(ctx: QaContext, res: dict, e: dict, it: dict) -> dict:
    """数値の項目1つ(フレームならフレームの値、無ければ武器の値)"""
    spec = ctx.data.fields.get(it["id"])
    if spec is None:
        return miss_answer(ctx, res, "no_hit", e["ja"])
    kind = _stat_kind(e, it)
    rec = e[kind] if kind else None
    if rec is None:
        return miss_answer(ctx, res, "no_data" if not ctx.builder else "no_hit", e["ja"])
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
        return miss_answer(ctx, res, "no_data" if not ctx.builder else "no_hit", e["ja"])
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
        return miss_answer(ctx, res, "no_data" if not ctx.builder else "no_hit", e["ja"])
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
        return miss_answer(ctx, res, "no_data" if not ctx.builder else "no_hit", e["ja"])
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
        if r.get("resurgence"):  # Prime Resurgence で交換できるレリックの行
            where += "(Prime Resurgence)"
        chance = r.get("chance")
        out.append({"cat": r["cat"], "where": where, "qty": r.get("qty") or "",
                    "chance": "" if chance is None else chance_text(chance)})
    return out


def _relic_sources(ctx: QaContext, res: dict, e: dict) -> dict:
    """時代ごとのレリック(Lith など)の入手先。場所(入手先の種類・場所の文)ごとに1行にまとめ、その場所で出るレリックを
    ドロップ表の確率のまま並べる(rows の relics = [{name, chance}]。足し算などはしない)。
    場所の並びはそこで一番高い確率の順、レリックの並びは確率の高い順・名前順"""
    names = ctx.index.names
    relics = sorted({names.split_qty(n)[1] for n in ctx.items if (hit := names.relic_era(n)) and hit[0] == e["relic"]})
    places: dict[tuple, dict] = {}
    for relic in relics:
        label = f"{ERA_JA[e['relic']]} {names.relic_era(relic)[1]}"
        for src in find_sources(relic, ctx.drops, ctx.sources, names, vault=_vault(ctx)):
            row = _source_rows([src], 1)[0]
            place = places.setdefault((row["cat"], row["where"]), {"cat": row["cat"], "where": row["where"], "qty": "",
                                                                   "chance": "", "relics": [], "_best": -1.0})
            place["relics"].append({"name": label + (f" ×{row['qty']}" if row["qty"] else ""), "chance": row["chance"],
                                    "_chance": src.get("chance")})
            place["_best"] = max(place["_best"], src.get("chance") or 0)
    if not places:
        return miss_answer(ctx, res, "no_hit", e["ja"])
    rows = sorted(places.values(), key=lambda p: (-p["_best"], p["where"]))[:QA_RELIC_SOURCE_LIMIT]
    for p in rows:
        p["relics"].sort(key=lambda r: (r["_chance"] is None, -(r["_chance"] or 0), r["name"]))
        p["relics"] = [{"name": r["name"], "chance": r["chance"]} for r in p["relics"]]
        del p["_best"]
    res["sources"].append({"title": "", "rows": rows})
    res["text"] = ctx.data.say("sources.relic", name=e["ja"], n=QA_RELIC_SOURCE_LIMIT) + _resurgence_note(ctx, rows)
    res["basis"] = ctx.data.say("basis.drops")
    return res


def _vault(ctx: QaContext) -> Vault:
    """Vault 入りの判定。API・CLI が Prime Resurgence も見て作ったもの(ctx.vault)があればそれ"""
    return ctx.vault if ctx.vault is not None else Vault(ctx.drops, ctx.sources)


def _resurgence_note(ctx: QaContext, rows: list[dict]) -> str:
    """答えた行に Prime Resurgence(レリック自体の入手先か、交換できるレリックの行)があれば、期限を添えた一言(無ければ空)"""
    until = _vault(ctx).until
    if until is None or not any(r.get("cat") == "resurgence" or r.get("resurgence") for r in rows):
        return ""
    return "。" + ctx.data.say("sources.resurgence", until=fmt_jst(until))


def _sources(ctx: QaContext, res: dict, e: dict, it: dict) -> dict:
    if ctx.drops is None:
        return miss_answer(ctx, res, "no_data", e["ja"])
    if e["relic"]:
        return _relic_sources(ctx, res, e)
    names = ctx.index.names
    vault = _vault(ctx)  # 入手先が Vault 入りのレリックだけの項目(いま手に入らない)
    rows = find_sources(e["en"], ctx.drops, ctx.sources, names, vault=vault) if e["item"] else []
    if rows:
        res["sources"].append({"title": "", "rows": _source_rows(rows, QA_SOURCE_LIMIT)})
        res["text"] = ctx.data.say("sources", name=e["ja"], n=QA_SOURCE_LIMIT) + _resurgence_note(ctx, rows)
        if vault.unavailable(e["en"]):
            res["text"] += "。" + ctx.data.say("sources.vaulted", name=e["ja"])
    else:
        owners = getattr(ctx.sources, "part_owner", None)
        parts = sorted({names.split_qty(n)[1] for n in ctx.items
                        if (hit := names.part_of(n, owners)) and norm(hit[0]) == e["key"] and norm(names.split_qty(n)[1]) != e["key"]})
        offered: list[dict] = []  # Prime Resurgence の印を見る行(部品ごとに出した行)
        for part in parts:
            prow = find_sources(part, ctx.drops, ctx.sources, names, vault=vault)
            offered += prow[:QA_PART_SOURCE_LIMIT]
            if prow:
                vaulted = vault is not None and vault.unavailable(part)
                title = names.ja(part) + (f"({ctx.data.say('sources.vaulted.parts')})" if vaulted else "")
                res["sources"].append({"title": title, "rows": _source_rows(prow, QA_PART_SOURCE_LIMIT)})
        if not res["sources"]:
            return miss_answer(ctx, res, "no_hit", e["ja"])
        res["text"] = ctx.data.say("sources.parts", name=e["ja"], n=QA_PART_SOURCE_LIMIT) + _resurgence_note(ctx, offered)
    res["basis"] = ctx.data.say("basis.drops")
    return res


def _build(ctx: QaContext, res: dict, e: dict, it: dict) -> dict:
    hits = builds_for(ctx.dev, e["en"])
    if not hits:
        return miss_answer(ctx, res, "no_build", e["ja"])
    res["builds"] = [build_view(b, ctx.index.names, ctx.subsume, ctx.archon, ctx.mod_stats) for b in hits]
    as_of = max((b["as_of"] for b in hits if b.get("as_of")), default="?")
    res["text"] = ctx.data.say("build", as_of=as_of)
    res["basis"] = ctx.data.say("basis.dev", as_of=as_of)
    return res


def helminth_self(ctx: QaContext, res: dict) -> dict:
    own = [r["ability"] for r in ctx.subsume if r["frame"] == HELMINTH_FRAME]
    if not own:
        return miss_answer(ctx, res, "no_hit", HELMINTH_FRAME)
    res.update(intent="helminth", text=ctx.data.say("helminth.self"), basis=ctx.data.say("basis.helminth"),
               facts=[{"label": a, "value": ""} for a in own])
    return res


def _helminth(ctx: QaContext, res: dict, e: dict, it: dict) -> dict:
    data = ctx.data
    res["basis"] = data.say("basis.helminth")
    if e["en"] == HELMINTH_FRAME:
        return helminth_self(ctx, res)
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
    return miss_answer(ctx, res, "no_hit", e["ja"])


HANDLERS = {"stats": _stats, "abilities": _abilities, "passive": _passive, "sources": _sources, "build": _build,
             "helminth": _helminth}
