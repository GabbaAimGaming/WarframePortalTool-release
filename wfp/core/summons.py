"""呼び出し(Warframe の中から呼び出す、Warframe のような存在。例: Sevagoth's Shadow)の同梱データ(data/summons/summons.json)

公式データ(Public Export)に本体の数値・アビリティが無いので、ゲーム画面の値を手で書いている。Export に無くても消さない。
一覧の行はフレーム(builder.json の frames)と同じ項目名にしてあるので、Q&A ではフレームと同じように答えられる。
"""
from __future__ import annotations

import re
from datetime import date

from wfp.core.common import SUMMON_SLOTS, SUMMON_STATS, norm

_EXPORT_PATH = re.compile(r"^/Lotus/[\w/]+$")


def _is_num(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _text(x: object) -> str:
    return x.strip() if isinstance(x, str) else ""


def _clean_ability(raw: object) -> dict | None:
    """アビリティの行を整える。番号・名前が無い行は None。数値の行は {label, value}(文字)"""
    if not isinstance(raw, dict) or raw.get("slot") not in SUMMON_SLOTS or not _text(raw.get("en")):
        return None
    values = [{"label": _text(v.get("label")), "value": _text(v.get("value"))}
              for v in raw.get("values") or [] if isinstance(v, dict) and _text(v.get("label")) and _text(v.get("value"))]
    return {"slot": raw["slot"], "en": _text(raw["en"]), "ja": _text(raw.get("ja")) or _text(raw["en"]),
            "desc": _text(raw.get("desc")), "values": values}


def summon_list(raw: object) -> list[dict]:
    """summons.json の中身から呼び出しの一覧を作る。形の崩れた行・項目は飛ばす(読めなければ空)。

    行: {en, ja, owner, weapon, as_of, health, shield, armor, energy, sprint(あるものだけ), abilities: [{slot, en, ja, desc, values}]}
    """
    rows = raw.get("summons") if isinstance(raw, dict) else None
    out: list[dict] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not _text(row.get("en")) or not _text(row.get("owner")):
            continue
        stats = row.get("stats") if isinstance(row.get("stats"), dict) else {}
        abilities = sorted((a for a in map(_clean_ability, row.get("abilities") or []) if a), key=lambda a: a["slot"])
        out.append({"en": _text(row["en"]), "ja": _text(row.get("ja")) or _text(row["en"]), "owner": _text(row["owner"]),
                    "weapon": _text(row.get("weapon")), "as_of": _text(row.get("as_of")),
                    **{k: stats[k] for k in SUMMON_STATS if _is_num(stats.get(k))}, "abilities": abilities})
    return out


def check_summons(raw: object) -> list[str]:
    """同梱データの検査(テスト用)。見つかった問題の一覧(無ければ空)"""
    rows = raw.get("summons") if isinstance(raw, dict) else None
    if not isinstance(rows, list) or not rows:
        return ["summons が無い"]
    problems: list[str] = []
    seen: set[str] = set()
    for i, row in enumerate(rows, 1):
        where = f"{i}件目({row.get('en')})" if isinstance(row, dict) else f"{i}件目"
        if not isinstance(row, dict):
            problems.append(f"{where}: オブジェクトではない")
            continue
        for key in ("en", "ja", "owner"):
            if not _text(row.get(key)):
                problems.append(f"{where}: {key} が無い")
        if _text(row.get("en")):
            if norm(row["en"]) in seen:
                problems.append(f"{where}: en が重複")
            seen.add(norm(row["en"]))
        if row.get("weapon") is not None and not _EXPORT_PATH.match(_text(row.get("weapon"))):
            problems.append(f"{where}: weapon が内部パスの形ではない")
        try:
            date.fromisoformat(str(row.get("as_of")))
        except ValueError:
            problems.append(f"{where}: as_of が YYYY-MM-DD の日付ではない")
        stats = row.get("stats")
        if not isinstance(stats, dict) or set(stats) - set(SUMMON_STATS) or not all(_is_num(v) and v > 0 for v in stats.values()):
            problems.append(f"{where}: stats は {list(SUMMON_STATS)} の正の数だけ")
        raw_ab = row.get("abilities") if isinstance(row.get("abilities"), list) else []
        clean = [a for a in map(_clean_ability, raw_ab) if a]
        if len(clean) != len(raw_ab) or not clean:
            problems.append(f"{where}: abilities に形の崩れた行がある(slot は {list(SUMMON_SLOTS)}・en が要る)")
        slots = [a["slot"] for a in clean]
        if len(slots) != len(set(slots)):
            problems.append(f"{where}: abilities の slot が重複")
        for a in raw_ab:
            if isinstance(a, dict) and any(not (isinstance(v, dict) and _text(v.get("label")) and _text(v.get("value")))
                                           for v in a.get("values") or []):
                problems.append(f"{where}: {a.get('en')} の values に label・value の無い行がある")
    return problems

