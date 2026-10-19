"""マスター一覧"""
from __future__ import annotations

from wfp.core.common import MASTERY_CATS
from wfp.core.names import Names


def mastery_label(m: dict) -> str:
    """表示名。Kitgun はプライマリ版とセカンダリ版を区別する"""
    v = {"primary": "プライマリ", "secondary": "セカンダリ"}.get(m.get("variant", ""), "")
    return f"{m['ja']} ({v})" if v else m["ja"]


def mastery_table(names: Names, done: set[str]) -> list[dict]:
    return [{**m, "cat_ja": MASTERY_CATS.get(m["cat"], m["cat"]), "label": mastery_label(m), "done": m["id"] in done}
            for m in names.mastery]


def mastery_summary(rows: list[dict]) -> dict:
    out = {}
    for c in MASTERY_CATS:
        rs = [r for r in rows if r["cat"] == c]
        out[c] = {"total": len(rs), "done": sum(r["done"] for r in rs),
                  "xp": sum(r["xp"] for r in rs), "xp_done": sum(r["xp"] for r in rs if r["done"])}
    out["all"] = {k: sum(v[k] for v in out.values()) for k in ("total", "done", "xp", "xp_done")}
    return out
