"""マスター一覧

- 元は名前辞書(names.json の mastery。Public Export から作る)
- Export に無い項目(プレクサス・アンプ本体。カテゴリーは extra「その他」)は同梱の data/mastery/extra.json から毎回足す。names.json には入れないので、
  データ更新や Export との照合で見つからなくても消えない
- ファウンダー限定品(MASTERY_FOUNDER)はカテゴリーを「ファウンダー」に付け替える。id は元のままなので、
  マスター済みの記録(mastered.json)は付け替えの前後で変わらない
"""
from __future__ import annotations

from pathlib import Path

from wfp.core.common import MASTERY_CATS, MASTERY_EXTRA_FILE, MASTERY_FOUNDER
from wfp.core.names import Names
from wfp.store import appdata


def mastery_label(m: dict) -> str:
    """表示名。Kitgun はプライマリ版とセカンダリ版を区別する"""
    v = {"primary": "プライマリ", "secondary": "セカンダリ"}.get(m.get("variant", ""), "")
    return f"{m['ja']} ({v})" if v else m["ja"]


def check_extra(raw: object) -> list[dict]:
    """extra.json の中身を検査して項目の一覧にする。形の合わない項目は黙って飛ばす(ファイルが無い・壊れていれば空)"""
    items = raw.get("items") if isinstance(raw, dict) else None
    out = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        en, cat, rk, xp = it.get("en"), it.get("cat"), it.get("rank"), it.get("xp")
        if (not isinstance(en, str) or not en.strip() or cat not in MASTERY_CATS or cat == "founder"
                or isinstance(rk, bool) or not isinstance(rk, int) or rk <= 0
                or isinstance(xp, bool) or not isinstance(xp, int) or xp < 0):
            continue
        ja = it.get("ja") if isinstance(it.get("ja"), str) and it["ja"].strip() else en
        out.append({"id": f"{cat}:{en.strip().lower()}", "en": en.strip(), "ja": ja.strip(), "cat": cat,
                    "variant": "", "rank": rk, "xp": xp})
    return out


def mastery_items(names: Names, src: Path | None = None) -> list[dict]:
    """マスター一覧の全項目: 名前辞書の分 + 手で足す分(同じ id は名前辞書を優先)。ファウンダー限定品は付け替える"""
    items = list(names.mastery)
    ids = {m["id"] for m in items}
    items += [m for m in check_extra(appdata.read_mastery(MASTERY_EXTRA_FILE, src)) if m["id"] not in ids]
    items = [{**m, "cat": "founder"} if m["id"] in MASTERY_FOUNDER else m for m in items]
    order = {c: i for i, c in enumerate(MASTERY_CATS)}
    return sorted(items, key=lambda m: (order.get(m["cat"], len(order)), m["en"].lower(), m.get("variant", "")))


def mastery_table(names: Names, done: set[str], src: Path | None = None) -> list[dict]:
    return [{**m, "cat_ja": MASTERY_CATS.get(m["cat"], m["cat"]), "label": mastery_label(m), "done": m["id"] in done}
            for m in mastery_items(names, src)]


def mastery_summary(rows: list[dict]) -> dict:
    out = {}
    for c in MASTERY_CATS:
        rs = [r for r in rows if r["cat"] == c]
        out[c] = {"total": len(rs), "done": sum(r["done"] for r in rs),
                  "xp": sum(r["xp"] for r in rs), "xp_done": sum(r["xp"] for r in rs if r["done"])}
    out["all"] = {k: sum(v[k] for v in out.values()) for k in ("total", "done", "xp", "xp_done")}
    return out
