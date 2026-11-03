"""アルコンの欠片: 色と効果の一覧(同梱の data/archon/shards.json)と、ビルドに書く欠片の値の検査

効果の種類と値は Export に無い(Export にあるのは欠片の名前だけ)ので、ゲーム画面を見て手で書く。
効果の id は WFCD の archonShards.json の内部パスの末尾(ArchonCrystalUpgrade の後ろ)。保存済みのビルドはこの id で効果を指す。
Tauforged の値は保存せず、表示するときに tauforged_rate を掛けて出す(効果ごとの "tauforged" があればその値)。
"""
from __future__ import annotations

import re

from wfp.core.common import ARCHON_SLOTS, ARCHON_VALUE_KEYS, TextError, txt

# 文の中の差し込み({v} {max} {per})と、値の項目の対応
_HOLE_KEYS = {"v": "value", "max": "max", "per": "per"}
_HOLE_RE = re.compile(r"\{(\w+)\}")
_DEFAULT_RATE = 1.5


def _is_num(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _clean_effect(raw: object) -> dict | None:
    """効果の行を整える。id・ja・en・value が無い行は None"""
    if not isinstance(raw, dict):
        return None
    eid, ja, en = raw.get("id"), raw.get("ja"), raw.get("en")
    if not all(isinstance(x, str) and x.strip() for x in (eid, ja, en)) or not _is_num(raw.get("value")):
        return None
    out = {"id": eid.strip(), "ja": ja, "en": en}
    out.update({k: raw[k] for k in ARCHON_VALUE_KEYS if _is_num(raw.get(k))})
    over = raw.get("tauforged")
    if isinstance(over, dict):
        over = {k: v for k, v in over.items() if k in ARCHON_VALUE_KEYS and _is_num(v)}
        if over:
            out["tauforged"] = over
    return out


def shard_list(raw: object) -> dict:
    """shards.json の中身から {tauforged_rate, colors: [{key, ja, en, export, effects}]} を作る。

    形の崩れた色・効果は飛ばす(読めなければ色は空)。色の並びはファイルの順。
    """
    data = raw if isinstance(raw, dict) else {}
    rate = data.get("tauforged_rate")
    colors_raw = data.get("colors")
    colors: list[dict] = []
    for key, c in (colors_raw.items() if isinstance(colors_raw, dict) else []):
        if not isinstance(c, dict) or not all(isinstance(c.get(k), str) and c[k].strip() for k in ("ja", "en")):
            continue
        effects = [e for e in map(_clean_effect, c.get("effects") if isinstance(c.get("effects"), list) else []) if e]
        colors.append({"key": key, "ja": c["ja"], "en": c["en"],
                       "export": c.get("export") if isinstance(c.get("export"), str) else "", "effects": effects})
    return {"tauforged_rate": rate if _is_num(rate) and rate > 0 else _DEFAULT_RATE, "colors": colors}


def check_shards(raw: object) -> list[str]:
    """同梱データの検査(テスト用)。見つかった問題の一覧(無ければ空)"""
    problems: list[str] = []
    data = raw if isinstance(raw, dict) else {}
    if not _is_num(data.get("tauforged_rate")) or data["tauforged_rate"] <= 1:
        problems.append("tauforged_rate が 1 より大きい数ではない")
    colors = data.get("colors")
    if not isinstance(colors, dict) or not colors:
        return problems + ["colors が無い"]
    seen: set[str] = set()
    for key, c in colors.items():
        effects = c.get("effects") if isinstance(c, dict) else None
        if not isinstance(effects, list) or not effects:
            problems.append(f"{key}: effects が無い")
            continue
        for raw_e in effects:
            e = _clean_effect(raw_e)
            if e is None:
                problems.append(f"{key}: 形の崩れた効果 {raw_e!r}")
                continue
            where = f"{key}/{e['id']}"
            if e["id"] in seen:
                problems.append(f"{where}: id が重複")
            seen.add(e["id"])
            have = {k for k in ARCHON_VALUE_KEYS if k in e}
            for lang in ("ja", "en"):
                holes = set(_HOLE_RE.findall(e[lang]))
                if holes - set(_HOLE_KEYS):
                    problems.append(f"{where}: {lang} に知らない差し込み {sorted(holes - set(_HOLE_KEYS))}")
                if {_HOLE_KEYS[h] for h in holes if h in _HOLE_KEYS} != have:
                    problems.append(f"{where}: {lang} の差し込みと値の項目が合わない")
            if set(e.get("tauforged", {})) - have:
                problems.append(f"{where}: tauforged に元の値に無い項目")
            if isinstance(raw_e.get("tauforged"), dict) and len(raw_e["tauforged"]) != len(e.get("tauforged", {})):
                problems.append(f"{where}: tauforged に数でない値")
    return problems


def find_effect(data: dict, color: str, effect_id: str) -> tuple[dict, dict] | None:
    """色のキーと効果の id から (色, 効果)。どちらかが一覧に無い・色が違えば None"""
    c = next((c for c in data["colors"] if c["key"] == color), None)
    e = next((e for e in c["effects"] if e["id"] == effect_id), None) if c else None
    return (c, e) if e else None


def shard_values(effect: dict, tauforged: bool, rate: float) -> dict:
    """効果の値({value, max, per} のうちあるもの)。Tauforged なら上書きの値、無ければ rate を掛けた値"""
    over = effect.get("tauforged", {}) if tauforged else {}
    return {k: over.get(k, round(effect[k] * rate, 2) if tauforged else effect[k])
            for k in ARCHON_VALUE_KEYS if k in effect}


def format_num(x: float) -> str:
    """値の表示(整数なら小数点を付けない。37.5 はそのまま)"""
    return str(int(x)) if float(x).is_integer() else f"{x:g}"


def shard_text(effect: dict, lang: str, tauforged: bool, rate: float) -> str:
    """効果の文に値を埋めたもの(lang は ja / en。CLI は ja)"""
    vals = shard_values(effect, tauforged, rate)
    return _HOLE_RE.sub(lambda m: format_num(vals[_HOLE_KEYS[m.group(1)]]) if _HOLE_KEYS.get(m.group(1)) in vals
                        else m.group(0), effect[lang])


def clean_shards(btype: str, value: object, data: dict) -> list | None:
    """ビルドの shards の値(5枠の一覧。枠は {color, effect, tauforged} か null)を検査して整える。

    Warframe 以外の種別・未入力(全部の枠が空)は None(項目を付けない)。
    形の誤り・色か効果の片方だけ・一覧に無い色と効果(効果がその色のものでない場合も)は TextError。
    一覧が読めないとき(data の色が空)は、形だけ見て保存する。
    """
    if btype != "frame" or value is None:
        return None
    if not isinstance(value, list) or len(value) > ARCHON_SLOTS:
        raise TextError(txt("err.build.shards.form"))
    slots: list = []
    for raw in list(value) + [None] * (ARCHON_SLOTS - len(value)):
        if raw is None:
            slots.append(None)
            continue
        if not isinstance(raw, dict):
            raise TextError(txt("err.build.shards.form"))
        color, effect = str(raw.get("color") or "").strip(), str(raw.get("effect") or "").strip()
        if not color and not effect:
            slots.append(None)
            continue
        if not color or not effect:
            raise TextError(txt("err.build.shards.pair"))
        if data["colors"] and not find_effect(data, color, effect):
            raise TextError(txt("err.build.shards.unknown", name=f"{color}:{effect}"))
        slots.append({"color": color, "effect": effect, "tauforged": raw.get("tauforged") is True})
    return slots if any(slots) else None


def parse_shard_args(texts: list[str]) -> list | None:
    """CLI の --shard「1:red:MeleeCritDamage」(Tauforged は末尾に :t)を5枠の一覧にする(検査は clean_shards)。指定が無ければ None"""
    if not texts:
        return None
    slots: list = [None] * ARCHON_SLOTS
    for text in texts:
        parts = [p.strip() for p in text.split(":")]
        tauforged = len(parts) == 4 and parts[3].lower() == "t"
        if len(parts) not in (3, 4) or (len(parts) == 4 and not tauforged):
            raise TextError(txt("err.build.shards.pair"))
        try:
            num = int(parts[0])
        except ValueError:
            num = 0
        if not 1 <= num <= ARCHON_SLOTS:
            raise TextError(txt("err.build.shards.slot"))
        slots[num - 1] = {"color": parts[1], "effect": parts[2], "tauforged": tauforged}
    return slots
