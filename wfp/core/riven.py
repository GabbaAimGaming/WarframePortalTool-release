"""Riven 相場・Riven 性質の一覧と、相場の更新"""
from __future__ import annotations

from pathlib import Path

from wfp.core.common import DISPO_CATS, RIVEN_TYPES_JA, to_float
from wfp.core.names import Names, dispo_dots
from wfp.fetch import riven_stats
from wfp.store import gamedata


def riven_table(raw: list[dict], names: Names) -> list[dict]:
    """武器(と武器種)ごとに、未リロール/リロール済みの統計を1行にまとめる。"""
    rows: dict[tuple, dict] = {}
    for e in raw:
        t, weapon = e.get("itemType") or "", e.get("compatibility")
        key = (t, weapon or "")
        row = rows.setdefault(key, {
            "type": t, "type_ja": RIVEN_TYPES_JA.get(t, t.replace(" Riven Mod", "")),
            "veiled": not weapon, "weapon_en": weapon or "",
            "weapon_ja": names.ja(weapon.title() if weapon and weapon.isupper() else weapon) if weapon else "未開封(ヴェール)",
            "unrolled": None, "rerolled": None})
        row["rerolled" if e.get("rerolled") else "unrolled"] = {
            k: to_float(e.get(k)) for k in ("median", "avg", "min", "max", "stddev", "pop")}
    out = list(rows.values())
    best = lambda r: max((s["median"] for s in (r["unrolled"], r["rerolled"]) if s), default=0)
    out.sort(key=lambda r: (-best(r), r["weapon_en"]))
    return out


def dispo_table(names: Names, rivens: list[dict] | None = None) -> list[dict]:
    """Riven 性質の一覧。性質の高い順(●5 -> 1)。Riven 相場があれば、プライマリのライフル/ショットガンはその武器種に合わせる"""
    market = {}
    for e in rivens or []:
        t, c = e.get("itemType"), e.get("compatibility")
        if c and t in ("Rifle Riven Mod", "Shotgun Riven Mod"):
            market[str(c).lower()] = t
    out = []
    for m in names.dispo:
        t = market.get(m["en"].lower(), m["type"]) if m["cat"] == "primary" else m["type"]
        label = RIVEN_TYPES_JA.get(t, t.replace(" Riven Mod", ""))
        if m["variant"]:
            label += f"({ {'primary': 'プライマリ', 'secondary': 'セカンダリ'}.get(m['variant'], m['variant']) })"
        out.append({**m, "type": t, "type_ja": label, "cat_ja": DISPO_CATS.get(m["cat"], m["cat"]),
                    "dots": dispo_dots(m["value"])})
    order = list(DISPO_CATS)
    out.sort(key=lambda r: (order.index(r["cat"]) if r["cat"] in order else 99, -r["value"], r["en"].lower(), r["variant"]))
    return out


def update_rivens(d: Path) -> bool:
    """Riven 相場だけを取得し直す(データ更新の一部 / 「Riven相場だけ更新」ボタン / riven --update)"""
    print("Riven 相場(公式・週次)を取得中...")
    try:
        rows = riven_stats.fetch_rivens()
        if not rows:
            raise RuntimeError("Riven 相場のデータが空でした")
        gamedata.save_rivens(d, rows)
        print(f"  {len(rows)} 件取得しました")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  失敗しました: {e}  ※前回取得分があればそれを使います")
        return False
