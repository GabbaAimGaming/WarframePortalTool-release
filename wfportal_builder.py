#!/usr/bin/env python3
"""wfportal_builder - シミュレータ: フレーム性能・武器ダメージ・Riven の振れ幅の参考値を計算する

ブラウザ画面は web/wfportal_builder.html。ポータルのメニュー「シミュレータ」の中に表示する
(wfportal_ui.py の /builder。単独のページとしても開ける)。
計算はこのモジュールで行い、画面は /api/builder/* を呼び出して結果を表示するだけにしている
(計算を Python 側にまとめて、tests/test_builder.py で確かめられるようにするため)。

データ:
  - 公式 Public Export の ExportWarframes / ExportWeapons (英語・日本語) から必要な値だけを抜き出して
    データ置き場の builder.json に保存する。「データ更新」のときに名前辞書と同じデータから作る
    (シミュレータの画面の「シミュレータ用データを取得」でも取得できる。取得元は名前辞書と同じ
    calamity-inc/warframe-public-export -> 失敗したら公式 Public Export から直接)。
  - Public Export に無いもの(アビリティの数値、MOD の効果量、Riven の基準値)は、
    下の表(WARFRAME Wiki 掲載値をもとにした参考値)を使う。ゲームの更新で変わることがあるので、
    画面では「参考値」と表示し、入力欄で値を直せるようにしている。

標準ライブラリのみ。非公式のファンツールです(Digital Extremes Ltd. とは関係ありません)。
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from wfp.core.common import EXPORT_BASE, EXPORT_GITHUB
from wfp.fetch import decode, net

BUILDER_FILE = "builder.json"
BUILDER_EXPORTS = ("ExportWarframes", "ExportWeapons")


class BuilderError(Exception):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


# --------------------------------------------------------------------------
# ダメージの種類 (ExportWeapons の damagePerShot は 20 要素の配列で、この順)
# --------------------------------------------------------------------------

DAMAGE_TYPES = (
    ("impact", "衝撃"), ("puncture", "貫通"), ("slash", "切断"),
    ("heat", "火炎"), ("cold", "冷気"), ("electricity", "電気"), ("toxin", "毒"),
    ("blast", "爆発"), ("radiation", "放射線"), ("gas", "ガス"), ("magnetic", "磁気"),
    ("viral", "感染"), ("corrosive", "腐食"), ("void", "Void"), ("tau", "Tau"),
    ("cinematic", "演出用"), ("shield_drain", "シールド吸収"), ("health_drain", "ヘルス吸収"),
    ("energy_drain", "エネルギー吸収"), ("true", "True"),
)
DAMAGE_KEYS = tuple(k for k, _ in DAMAGE_TYPES)
DAMAGE_JA = dict(DAMAGE_TYPES)
PHYSICAL = ("impact", "puncture", "slash")
PRIMARY_ELEMENTS = ("heat", "cold", "electricity", "toxin")
# 2つの基本属性 -> 複合属性
COMBINED = {
    frozenset(("heat", "cold")): "blast", frozenset(("electricity", "heat")): "radiation",
    frozenset(("heat", "toxin")): "gas", frozenset(("cold", "electricity")): "magnetic",
    frozenset(("cold", "toxin")): "viral", frozenset(("electricity", "toxin")): "corrosive",
}

# 武器のカテゴリー (ExportWeapons の productCategory)
WEAPON_CATS = {"LongGuns": "primary", "Pistols": "secondary", "Melee": "melee",
               "SpaceGuns": "archgun", "SentinelWeapons": "robotic"}
CAT_JA = {"primary": "プライマリ", "secondary": "セカンダリ", "melee": "近接",
          "archgun": "アークウイングガン", "robotic": "コンパニオン武器"}
# 組み立て式の部品(Kitgun・Zaw・アンプなど)は単体の性能にならないので除く
_MODULAR_PARTS = re.compile(r"/(OperatorAmplifiers|ModularMelee[^/]*|SUModular[^/]*|InfKitGun|Hoverboard|ZanukaPetParts|MoaPetParts)/")

# ランク 30 で増える量 (Update 36 以降の多くのフレーム: ヘルス・シールド +100、エネルギー +50。例外のフレームもある)
RANK30_BONUS = {"health": 100.0, "shield": 100.0, "energy": 50.0}
ARMOR_CONSTANT = 300.0          # 被ダメージ軽減率 = アーマー / (アーマー + 300)
EFFICIENCY_CAP = 175.0          # アビリティ効率の上限(%)


# --------------------------------------------------------------------------
# MOD のプリセット (最大ランクの値・参考値。画面では入力欄に足し込むだけなので自由に直せる)
# --------------------------------------------------------------------------

FRAME_PRESETS = [
    {"en": "Vitality", "ja": "バイタリティ", "add": {"health_pct": 440}},
    {"en": "Redirection", "ja": "リダイレクション", "add": {"shield_pct": 440}},
    {"en": "Steel Fiber", "ja": "スチールファイバー", "add": {"armor_pct": 110}},
    {"en": "Flow", "ja": "フロー", "add": {"energy_pct": 150}},
    {"en": "Primed Flow", "ja": "プライム フロー", "add": {"energy_pct": 185}},
    {"en": "Intensify", "ja": "インテンシファイ", "add": {"strength": 30}},
    {"en": "Umbral Intensify", "ja": "アンブラル インテンシファイ", "add": {"strength": 44}},
    {"en": "Transient Fortitude", "ja": "トランジェント フォーティチュード", "add": {"strength": 55, "duration": -27.5}},
    {"en": "Blind Rage", "ja": "ブラインド レイジ", "add": {"strength": 99, "efficiency": -55}},
    {"en": "Continuity", "ja": "コンティニュイティ", "add": {"duration": 30}},
    {"en": "Primed Continuity", "ja": "プライム コンティニュイティ", "add": {"duration": 55}},
    {"en": "Narrow Minded", "ja": "ナローマインド", "add": {"duration": 99, "range": -66}},
    {"en": "Stretch", "ja": "ストレッチ", "add": {"range": 45}},
    {"en": "Augur Reach", "ja": "オーガー リーチ", "add": {"range": 30}},
    {"en": "Overextended", "ja": "オーバーエクステンド", "add": {"range": 90, "strength": -60}},
    {"en": "Streamline", "ja": "ストリームライン", "add": {"efficiency": 30}},
    {"en": "Fleeting Expertise", "ja": "フリーティング エクスパーティーズ", "add": {"efficiency": 60, "duration": -60}},
]
WEAPON_PRESETS = {
    "primary": [
        {"en": "Serration", "add": {"damage": 165}}, {"en": "Heavy Caliber", "add": {"damage": 165}},
        {"en": "Split Chamber", "add": {"multishot": 90}}, {"en": "Vigilante Armaments", "add": {"multishot": 60}},
        {"en": "Point Strike", "add": {"cc": 150}}, {"en": "Vital Sense", "add": {"cd": 120}},
        {"en": "Speed Trigger", "add": {"fire_rate": 60}}, {"en": "Rifle Aptitude", "add": {"status": 90}},
        {"en": "Point Blank", "add": {"damage": 90}}, {"en": "Hell's Chamber", "add": {"multishot": 120}},
        {"en": "Magazine Warp", "add": {"magazine": 30}}, {"en": "Fast Hands", "add": {"reload": 30}},
        {"en": "Hellfire", "element": ("heat", 90)}, {"en": "Cryo Rounds", "element": ("cold", 90)},
        {"en": "Stormbringer", "element": ("electricity", 90)}, {"en": "Infected Clip", "element": ("toxin", 90)},
        {"en": "Malignant Force", "element": ("toxin", 60), "add": {"status": 60}},
        {"en": "Bane of Grineer", "add": {"faction": 30}},
    ],
    "secondary": [
        {"en": "Hornet Strike", "add": {"damage": 220}}, {"en": "Barrel Diffusion", "add": {"multishot": 120}},
        {"en": "Lethal Torrent", "add": {"multishot": 60, "fire_rate": 60}}, {"en": "Pistol Gambit", "add": {"cc": 120}},
        {"en": "Target Cracker", "add": {"cd": 60}}, {"en": "Gunslinger", "add": {"fire_rate": 72}},
        {"en": "Heated Charge", "element": ("heat", 90)}, {"en": "Deep Freeze", "element": ("cold", 90)},
        {"en": "Convulsion", "element": ("electricity", 90)}, {"en": "Pathogen Rounds", "element": ("toxin", 90)},
    ],
    "melee": [
        {"en": "Pressure Point", "add": {"damage": 120}}, {"en": "Primed Pressure Point", "add": {"damage": 165}},
        {"en": "True Steel", "add": {"cc": 60}}, {"en": "Organ Shatter", "add": {"cd": 90}},
        {"en": "Fury", "add": {"fire_rate": 30}}, {"en": "Molten Impact", "element": ("heat", 90)},
        {"en": "North Wind", "element": ("cold", 90)}, {"en": "Shocking Touch", "element": ("electricity", 90)},
        {"en": "Fever Strike", "element": ("toxin", 90)},
    ],
}
WEAPON_PRESETS["archgun"] = WEAPON_PRESETS["primary"]
WEAPON_PRESETS["robotic"] = WEAPON_PRESETS["primary"]


# --------------------------------------------------------------------------
# Riven (WARFRAME Wiki 掲載の基準値。性質 1.0・最大ランク(8)・効果 2つ/マイナス無しの補正前の値)
#   値 = 基準値 × 性質値 × 効果数による補正 × 乱数(0.9〜1.1)   ランク r では × (r + 1) / 9
# --------------------------------------------------------------------------

RIVEN_GROUPS = ("rifle", "shotgun", "pistol", "melee", "archgun")
RIVEN_GROUP_JA = {"rifle": "ライフル", "shotgun": "ショットガン", "pistol": "ピストル", "melee": "近接", "archgun": "アークウイングガン"}
# Riven の種類 (wfportal の RIVEN_TYPES_JA のキー) -> 基準値の列。Kitgun・コンパニオン武器は推定
RIVEN_TYPE_GROUP = {"Rifle Riven Mod": "rifle", "Shotgun Riven Mod": "shotgun", "Pistol Riven Mod": "pistol",
                    "Melee Riven Mod": "melee", "Zaw Riven Mod": "melee", "Kitgun Riven Mod": "pistol",
                    "Archgun Riven Mod": "archgun", "Companion Weapon Riven Mod": "rifle"}
# (効果の数, マイナス効果あり) -> (プラス効果の補正, マイナス効果の補正)
RIVEN_MODIFIERS = {(2, False): (0.99, 0.0), (2, True): (1.2375, -0.495),
                   (3, False): (0.75, 0.0), (3, True): (0.9375, -0.75)}
_G = lambda rifle=None, shotgun=None, pistol=None, melee=None, archgun=None: {  # noqa: E731
    k: v for k, v in (("rifle", rifle), ("shotgun", shotgun), ("pistol", pistol), ("melee", melee), ("archgun", archgun)) if v is not None}
_GUNS = lambda v: _G(v, v, v, None, v)  # noqa: E731
RIVEN_STATS = [
    {"key": "cc", "ja": "クリティカル率", "unit": "%", "base": _G(149.99, 90, 149.99, 180, 99.9)},
    {"key": "cd", "ja": "クリティカルダメージ", "unit": "%", "base": _G(120, 90, 90, 90, 80.1)},
    {"key": "damage", "ja": "ダメージ(近接ダメージ)", "unit": "%", "base": _G(165, 164.7, 219.6, 164.7, 99.9)},
    {"key": "multishot", "ja": "マルチショット", "unit": "%", "base": _G(90, 119.7, 119.7, None, 60.3)},
    {"key": "fire_rate", "ja": "連射速度(攻撃速度)", "unit": "%", "base": _G(60.03, 89.1, 74.7, 54.9, 60.03)},
    {"key": "status", "ja": "状態異常率", "unit": "%", "base": _G(90, 90, 90, 90, 60.3)},
    {"key": "status_duration", "ja": "状態異常の持続時間", "unit": "%", "base": _G(99.99, 99, 99.99, 99, 99.99)},
    {"key": "heat", "ja": "火炎", "unit": "%", "base": _G(90, 90, 90, 90, 119.7)},
    {"key": "cold", "ja": "冷気", "unit": "%", "base": _G(90, 90, 90, 90, 119.7)},
    {"key": "electricity", "ja": "電気", "unit": "%", "base": _G(90, 90, 90, 90, 119.7)},
    {"key": "toxin", "ja": "毒", "unit": "%", "base": _G(90, 90, 90, 90, 119.7)},
    {"key": "impact", "ja": "衝撃", "unit": "%", "base": _G(119.97, 119.97, 119.97, 119.7, 90)},
    {"key": "puncture", "ja": "貫通", "unit": "%", "base": _G(119.97, 119.97, 119.97, 119.7, 90)},
    {"key": "slash", "ja": "切断", "unit": "%", "base": _G(119.97, 119.97, 119.97, 119.7, 90)},
    {"key": "faction", "ja": "勢力ダメージ(Grineer など)", "unit": "%", "base": _G(45, 45, 45, 45, 45)},
    {"key": "magazine", "ja": "マガジン容量", "unit": "%", "base": _G(50, 50, 50, None, 60.3)},
    {"key": "reload", "ja": "リロード速度", "unit": "%", "base": _G(50, 49.45, 50, None, 99.9)},
    {"key": "ammo", "ja": "最大弾薬数", "unit": "%", "base": _G(49.95, 90, 90, None, 99.9)},
    {"key": "projectile_speed", "ja": "弾速", "unit": "%", "base": _G(90, 89.1, 90)},
    {"key": "recoil", "ja": "反動(マイナスが有利)", "unit": "%", "base": _GUNS(90)},
    {"key": "zoom", "ja": "ズーム", "unit": "%", "base": _G(59.99, None, 80.1, None, 59.99)},
    {"key": "punch_through", "ja": "貫通力", "unit": "m", "base": _GUNS(2.7)},
    {"key": "range", "ja": "射程(近接)", "unit": "m", "base": _G(melee=1.94)},
    {"key": "combo_duration", "ja": "コンボ持続時間", "unit": "秒", "base": _G(melee=8.1)},
    {"key": "initial_combo", "ja": "初期コンボ", "unit": "", "base": _G(melee=24.5)},
    {"key": "slide_cc", "ja": "スライド攻撃のクリティカル率", "unit": "%", "base": _G(melee=120)},
    {"key": "finisher", "ja": "フィニッシャーダメージ", "unit": "%", "base": _G(melee=119.7)},
    {"key": "heavy_efficiency", "ja": "ヘビーアタック効率", "unit": "%", "base": _G(melee=73.44)},
]
RIVEN_STAT_INDEX = {s["key"]: s for s in RIVEN_STATS}


# --------------------------------------------------------------------------
# Public Export からシミュレータ用のデータを作る
# --------------------------------------------------------------------------

def _clean_name(name) -> str:
    return re.sub(r"^<[^>]+>\s*", "", str(name or "")).strip()


def _clean_text(text) -> str:
    """説明文の <DT_FIRE_COLOR> のようなタグを外し、空白をそろえる"""
    s = re.sub(r"<[^>]*>", "", str(text or ""))
    return re.sub(r"\s+", " ", s).strip()


def _num(v, default: float = 0.0) -> float:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else default


def extract_builder_data(en_docs: list[dict], ja_docs: list[dict]) -> dict:
    """ExportWarframes / ExportWeapons (英語・日本語) からフレームと武器の性能を抜き出す"""
    ja: dict[str, dict] = {}
    for doc in ja_docs:
        for key in BUILDER_EXPORTS:
            for it in doc.get(key, []) or []:
                if isinstance(it, dict) and it.get("uniqueName"):
                    ja[it["uniqueName"]] = it

    frames: dict[str, dict] = {}
    weapons: dict[tuple, dict] = {}
    for doc in en_docs:
        for it in doc.get("ExportWarframes", []) or []:
            if not isinstance(it, dict) or it.get("productCategory") != "Suits":
                continue
            name = _clean_name(it.get("name"))
            if not name or name.lower() in frames:
                continue
            j = ja.get(it.get("uniqueName", ""), {})
            abil_ja = {a.get("abilityUniqueName"): a for a in j.get("abilities", []) or [] if isinstance(a, dict)}
            abilities = []
            for a in it.get("abilities", []) or []:
                if not isinstance(a, dict) or not a.get("abilityName"):
                    continue
                aj = abil_ja.get(a.get("abilityUniqueName"), {})
                abilities.append({"en": _clean_name(a["abilityName"]), "ja": _clean_name(aj.get("abilityName") or a["abilityName"]),
                                  "desc": _clean_text(aj.get("description") or a.get("description"))})
            frames[name.lower()] = {
                "en": name, "ja": _clean_name(j.get("name") or name),
                "health": _num(it.get("health")), "shield": _num(it.get("shield")), "armor": _num(it.get("armor")),
                "energy": _num(it.get("power")), "sprint": _num(it.get("sprintSpeed"), 1.0),
                "passive": _clean_text(j.get("passiveDescription") or it.get("passiveDescription")),
                "abilities": abilities,
            }
        for it in doc.get("ExportWeapons", []) or []:
            if not isinstance(it, dict):
                continue
            uid, cat = it.get("uniqueName", ""), WEAPON_CATS.get(it.get("productCategory"))
            dmg = it.get("damagePerShot")
            if not cat or not isinstance(dmg, list) or it.get("excludeFromCodex") or _MODULAR_PARTS.search(uid):
                continue
            name = _clean_name(it.get("name"))
            damage = {DAMAGE_KEYS[i]: round(float(v), 4) for i, v in enumerate(dmg[:len(DAMAGE_KEYS)])
                      if isinstance(v, (int, float)) and v > 0}
            if not name or not damage or (cat, name.lower()) in weapons:
                continue
            w = {"en": name, "ja": _clean_name(ja.get(uid, {}).get("name") or name), "cat": cat, "damage": damage,
                 "cc": _num(it.get("criticalChance")), "cd": _num(it.get("criticalMultiplier"), 1.0),
                 "sc": _num(it.get("procChance")), "fire_rate": _num(it.get("fireRate"), 1.0),
                 "dispo": round(_num(it.get("omegaAttenuation"), 1.0), 2), "shotgun": "shotgun" in uid.lower()}
            if cat != "melee":
                w.update(multishot=_num(it.get("multishot"), 1.0) or 1.0, magazine=_num(it.get("magazineSize")),
                         reload=_num(it.get("reloadTime")), trigger=str(it.get("trigger") or ""))
            weapons[(cat, name.lower())] = w
    order = list(CAT_JA)
    return {"frames": sorted(frames.values(), key=lambda f: f["en"].lower()),
            "weapons": sorted(weapons.values(), key=lambda w: (order.index(w["cat"]), w["en"].lower()))}


def save_builder_data(d: Path, data: dict, source: str) -> dict:
    """抜き出したデータを builder.json に保存する(データ更新・シミュレータ用データの取得から使う)"""
    if not data.get("frames") or not data.get("weapons"):
        raise RuntimeError("フレームか武器のデータが空でした")
    data = {**data, "source": source, "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (d / BUILDER_FILE).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def _fetch_docs_github(lang: str) -> list[dict]:
    docs = []
    for prefix in BUILDER_EXPORTS:
        print(f"  取得: {prefix}_{lang}.json")
        raw = net.http_get(f"{EXPORT_GITHUB}/{prefix}_{lang}.json", timeout=120)
        docs.append(decode.parse_export_json(raw.decode("utf-8", "replace")))
    return docs


def _fetch_docs_official(lang: str) -> list[dict]:
    text = decode.decompress_lzma(net.http_get(f"{EXPORT_BASE}/index_{lang}.txt.lzma")).decode("utf-8", "replace")
    docs = []
    for line in text.splitlines():
        if line.startswith(BUILDER_EXPORTS):
            print(f"  取得: {line.split('!')[0]}")
            docs.append(decode.parse_export_json(net.http_get(f"{EXPORT_BASE}/Manifest/{line}").decode("utf-8", "replace")))
    return docs


def update_builder_data(d: Path) -> bool:
    """シミュレータ用のデータ(フレーム・武器の性能)だけを取得して builder.json に保存する。print でログを出す"""
    print("シミュレータ用のデータ(ExportWarframes / ExportWeapons)を取得中...")
    errors = []
    for label, fetch in (("GitHub (calamity-inc/warframe-public-export)", _fetch_docs_github),
                         ("公式 Public Export", _fetch_docs_official)):
        print(f"  取得元: {label}")
        try:
            data = save_builder_data(d, extract_builder_data(fetch("en"), fetch("ja")), label)
        except Exception as e:  # noqa: BLE001
            print(f"  失敗: {e}")
            errors.append(f"{label}: {e}")
            continue
        print(f"完了: フレーム {len(data['frames'])} 件 / 武器 {len(data['weapons'])} 件")
        return True
    print("取得できませんでした: " + " / ".join(errors) + "  ※前回取得分があればそれを使います")
    return False


def load_builder_data(d: Path) -> dict | None:
    f = d / BUILDER_FILE
    if not f.exists():
        return None
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("frames") is not None else None


# --------------------------------------------------------------------------
# 計算: フレーム
# --------------------------------------------------------------------------

def _get(mods: dict | None, key: str) -> float:
    try:
        return float((mods or {}).get(key) or 0)
    except (TypeError, ValueError):
        raise BuilderError(f"数字で入力してください: {key}")


def damage_reduction(armor: float) -> float:
    """アーマーによる被ダメージ軽減率 (0〜1)"""
    armor = max(0.0, armor)
    return armor / (armor + ARMOR_CONSTANT)


def frame_stats(frame: dict, mods: dict | None = None, rank30: bool = True, rank_bonus: dict | None = None) -> dict:
    """フレームの性能(ヘルス・シールド・アーマー・エネルギー)とアビリティ性能の倍率

    mods: health_pct / shield_pct / armor_pct / energy_pct (%)、health_flat などの固定値、
          strength / duration / range / efficiency (アビリティ性能の増減 %。100% からの差)
    """
    bonus = {**RANK30_BONUS, **{k: float(v) for k, v in (rank_bonus or {}).items() if k in RANK30_BONUS}}
    rows = {}
    for key in ("health", "shield", "armor", "energy"):
        base = float(frame.get(key) or 0)
        ranked = base + (bonus.get(key, 0.0) if rank30 else 0.0)
        modded = ranked * (1 + _get(mods, f"{key}_pct") / 100) + _get(mods, f"{key}_flat")
        rows[key] = {"base": base, "ranked": ranked, "modded": max(0.0, modded)}
    dr = damage_reduction(rows["armor"]["modded"])
    health, shield = rows["health"]["modded"], rows["shield"]["modded"]
    strength = 100 + _get(mods, "strength")
    duration = 100 + _get(mods, "duration")
    rng = 100 + _get(mods, "range")
    eff_raw = 100 + _get(mods, "efficiency")
    efficiency = min(EFFICIENCY_CAP, eff_raw)
    return {
        "stats": rows, "damage_reduction": dr,
        "ehp": health / (1 - dr) + shield,
        "ability": {"strength": strength, "duration": duration, "range": rng, "efficiency": efficiency,
                    "efficiency_raw": eff_raw, "efficiency_capped": eff_raw > EFFICIENCY_CAP,
                    "cost": max(0.0, 200 - efficiency)},
    }


def ability_value(base: float, scale: str, ability: dict) -> float:
    """アビリティの基準値(Wiki などで調べた値)に、どのステータスで伸びるかを掛けた参考値

    scale: strength / duration / range / cost (エネルギー消費) / inv_duration (持続時間で短くなるもの) / none
    """
    if scale == "strength":
        return base * ability["strength"] / 100
    if scale == "duration":
        return base * ability["duration"] / 100
    if scale == "range":
        return base * ability["range"] / 100
    if scale == "cost":
        return base * ability["cost"] / 100
    if scale == "inv_duration":
        return base * 100 / ability["duration"] if ability["duration"] > 0 else float("inf")
    return base


# --------------------------------------------------------------------------
# 計算: 武器
# --------------------------------------------------------------------------

def modded_damage(weapon: dict, mods: dict | None = None) -> dict[str, float]:
    """MOD 適用後の1発(1ヒット)あたりのダメージ内訳 (クリティカル・マルチショット・勢力は含まない)

    - ダメージ MOD は全体に掛かる。衝撃/貫通/切断の MOD は、その種類の基礎値にだけ掛かる
    - 属性 MOD は「ダメージ MOD 適用後の基礎ダメージ合計 × 属性 %」を追加する
    - 属性は MOD の並び順に2つずつ複合する。武器に元からある属性は最後に加わる
      (同じ属性の MOD があれば、その MOD の位置で合算する)
    """
    base = {k: float(v) for k, v in (weapon.get("damage") or {}).items() if float(v) > 0}
    total = sum(base.values())
    dmg_mult = 1 + _get(mods, "damage") / 100
    out: dict[str, float] = {}
    for k, v in base.items():
        mult = dmg_mult * (1 + _get(mods, k) / 100) if k in PHYSICAL else dmg_mult
        out[k] = v * mult
    order: list[str] = []
    amount: dict[str, float] = {}
    for e in (mods or {}).get("elements") or []:
        if not isinstance(e, dict):
            continue
        t, pct = str(e.get("type") or ""), _get(e, "pct")
        if t not in PRIMARY_ELEMENTS or not pct:
            continue
        if t not in order:
            order.append(t)
        amount[t] = amount.get(t, 0.0) + total * dmg_mult * pct / 100
    for t in PRIMARY_ELEMENTS:  # 元からある基本属性は最後
        if t in out:
            if t not in order:
                order.append(t)
            amount[t] = amount.get(t, 0.0) + out.pop(t)
    for i in range(0, len(order) - 1, 2):
        a, b = order[i], order[i + 1]
        c = COMBINED[frozenset((a, b))]
        out[c] = out.get(c, 0.0) + amount[a] + amount[b]
    if len(order) % 2:
        t = order[-1]
        out[t] = out.get(t, 0.0) + amount[t]
    return {k: v for k, v in out.items() if v > 0}


def weapon_stats(weapon: dict, mods: dict | None = None) -> dict:
    """MOD 適用後の武器性能と DPS の参考値

    mods: damage / multishot / cc / cd / fire_rate / status / faction / magazine / reload /
          impact / puncture / slash (いずれも %) と elements [{type, pct}]
    """
    melee = weapon.get("cat") == "melee"
    per_hit = modded_damage(weapon, mods)
    per_hit_total = sum(per_hit.values())
    cc = weapon.get("cc", 0) * (1 + _get(mods, "cc") / 100)
    cd = weapon.get("cd", 1) * (1 + _get(mods, "cd") / 100)
    crit_avg = 1 + max(0.0, cc) * (cd - 1)
    multishot = 1.0 if melee else weapon.get("multishot", 1) * (1 + _get(mods, "multishot") / 100)
    fire_rate = weapon.get("fire_rate", 1) * (1 + _get(mods, "fire_rate") / 100)
    status = weapon.get("sc", 0) * (1 + _get(mods, "status") / 100)
    faction = 1 + _get(mods, "faction") / 100
    burst = per_hit_total * crit_avg * multishot * max(0.0, fire_rate) * faction
    out = {
        "melee": melee,
        "damage": [{"key": k, "ja": DAMAGE_JA.get(k, k), "value": v, "share": v / per_hit_total if per_hit_total else 0}
                   for k, v in sorted(per_hit.items(), key=lambda x: -x[1])],
        "per_hit": per_hit_total, "cc": cc, "cd": cd, "crit_avg": crit_avg, "multishot": multishot,
        "fire_rate": fire_rate, "status": status, "status_per_sec": status * multishot * max(0.0, fire_rate),
        "faction": faction, "per_shot_avg": per_hit_total * crit_avg * multishot * faction, "burst_dps": burst,
    }
    if not melee and weapon.get("magazine") and weapon.get("reload"):
        mag = max(1, round(weapon["magazine"] * (1 + _get(mods, "magazine") / 100)))
        reload = weapon["reload"] / max(0.01, 1 + _get(mods, "reload") / 100)
        empty = mag / fire_rate if fire_rate > 0 else 0
        out.update(magazine=mag, reload=reload, mag_time=empty,
                   sustained_dps=burst * empty / (empty + reload) if empty + reload > 0 else 0)
    return out


# --------------------------------------------------------------------------
# 計算: Riven の振れ幅
# --------------------------------------------------------------------------

def riven_group(riven_type: str) -> str:
    return RIVEN_TYPE_GROUP.get(riven_type, "rifle")


def weapon_riven_type(weapon: dict, dispo_rows: list[dict] | None = None) -> str:
    """武器の Riven の種類。names.json の Riven 性質(ライフル/ショットガンの判定済み)があればそれを使う"""
    for r in dispo_rows or []:
        if r.get("en", "").lower() == weapon["en"].lower() and r.get("cat") == weapon["cat"] and not r.get("variant"):
            return r.get("type") or ""
    return {"primary": "Shotgun Riven Mod" if weapon.get("shotgun") else "Rifle Riven Mod",
            "secondary": "Pistol Riven Mod", "melee": "Melee Riven Mod", "archgun": "Archgun Riven Mod",
            "robotic": "Companion Weapon Riven Mod"}.get(weapon.get("cat"), "Rifle Riven Mod")


def riven_range(base: float, dispo: float, buffs: int, curse: bool, negative: bool = False, rank: int = 8) -> tuple[float, float]:
    """1つの効果の振れ幅 (最小, 最大)。マイナス効果は負の値で返す"""
    if (buffs, curse) not in RIVEN_MODIFIERS:
        raise BuilderError("プラス効果の数は 2 か 3 です。")
    if negative and not curse:
        raise BuilderError("マイナス効果が無い構成です。")
    if not 0 <= rank <= 8:
        raise BuilderError("ランクは 0〜8 です。")
    buff_m, curse_m = RIVEN_MODIFIERS[(buffs, curse)]
    v = base * dispo * (curse_m if negative else buff_m) * (rank + 1) / 9
    lo, hi = v * 0.9, v * 1.1
    return (min(lo, hi), max(lo, hi))


def riven_calc(group: str, dispo: float, buffs: list[str], curse: str | None, rank: int = 8) -> dict:
    if group not in RIVEN_GROUPS:
        raise BuilderError("Riven の種類が不正です。")
    if not 0.1 <= dispo <= 3:
        raise BuilderError("性質値は 0.5〜1.55 程度の数字で入力してください。")
    if len(buffs) not in (2, 3):
        raise BuilderError("プラス効果は 2 つか 3 つ選んでください。")
    keys = list(buffs) + ([curse] if curse else [])
    if len(set(keys)) != len(keys):
        raise BuilderError("同じ効果は2回選べません。")
    rows = []
    for i, k in enumerate(keys):
        st = RIVEN_STAT_INDEX.get(k)
        if st is None or group not in st["base"]:
            raise BuilderError(f"{RIVEN_GROUP_JA[group]}の Riven には付かない効果です: {st['ja'] if st else k}")
        neg = i >= len(buffs)
        lo, hi = riven_range(st["base"][group], dispo, len(buffs), bool(curse), negative=neg, rank=rank)
        lo0, hi0 = riven_range(st["base"][group], dispo, len(buffs), bool(curse), negative=neg, rank=0)
        rows.append({"key": k, "ja": st["ja"], "unit": st["unit"], "negative": neg, "base": st["base"][group],
                     "min": lo, "max": hi, "min_r0": lo0, "max_r0": hi0})
    return {"group": group, "dispo": dispo, "rank": rank, "rows": rows}


# --------------------------------------------------------------------------
# 画面(wfportal_ui.py)から呼ぶ API
# --------------------------------------------------------------------------

def _need_data(d: Path) -> dict:
    data = load_builder_data(d)
    if data is None:
        raise BuilderError("シミュレータ用のデータがありません。メニューの「データ更新」か、"
                           "画面上部の「シミュレータ用データを取得」で取得してください。", 409)
    return data


def _find(items: list[dict], name: str, cat: str | None = None) -> dict:
    n = str(name or "").strip().lower()
    hits = [x for x in items if n in (x["en"].lower(), x["ja"].lower()) and (not cat or x.get("cat") == cat)]
    if not hits:
        raise BuilderError(f"見つかりません: {name}", 404)
    return hits[0]


def api_data(d: Path, dispo_rows: list[dict] | None = None) -> dict:
    data = load_builder_data(d)
    riven = {"groups": RIVEN_GROUP_JA, "stats": RIVEN_STATS,
             "modifiers": [{"buffs": b, "curse": c, "buff": m[0], "curse_m": m[1]} for (b, c), m in RIVEN_MODIFIERS.items()]}
    meta = {"cats": CAT_JA, "damage_types": DAMAGE_JA, "elements": list(PRIMARY_ELEMENTS),
            "frame_presets": FRAME_PRESETS, "weapon_presets": WEAPON_PRESETS, "rank30_bonus": RANK30_BONUS,
            "riven": riven, "riven_type_group": RIVEN_TYPE_GROUP}
    if data is None:
        return {"has_data": False, **meta}
    weapons = [{**w, "riven_type": weapon_riven_type(w, dispo_rows)} for w in data["weapons"]]
    return {"has_data": True, "updated": data.get("updated"), "source": data.get("source"),
            "frames": data["frames"], "weapons": weapons, **meta}


def api_frame(d: Path, body: dict) -> dict:
    frame = _find(_need_data(d)["frames"], body.get("name"))
    res = frame_stats(frame, body.get("mods"), rank30=bool(body.get("rank30", True)), rank_bonus=body.get("rank_bonus"))
    refs = []
    for r in body.get("refs") or []:
        try:
            base = float(r.get("base"))
        except (TypeError, ValueError, AttributeError):
            continue
        refs.append({"id": r.get("id"), "value": ability_value(base, str(r.get("scale") or "none"), res["ability"])})
    return {"frame": frame, **res, "refs": refs}


def api_weapon(d: Path, body: dict, dispo_rows: list[dict] | None = None) -> dict:
    weapon = _find(_need_data(d)["weapons"], body.get("name"), body.get("cat"))
    weapon = {**weapon, "riven_type": weapon_riven_type(weapon, dispo_rows)}
    return {"weapon": weapon, **weapon_stats(weapon, body.get("mods"))}


def api_riven(d: Path, body: dict, dispo_rows: list[dict] | None = None) -> dict:
    weapon = None
    if body.get("name"):
        weapon = _find(_need_data(d)["weapons"], body.get("name"), body.get("cat"))
    try:
        dispo = float(body.get("dispo") if body.get("dispo") not in (None, "") else (weapon or {}).get("dispo", 1.0))
        rank = int(body.get("rank", 8))
    except (TypeError, ValueError):
        raise BuilderError("性質値・ランクは数字で入力してください。")
    group = body.get("group") or (riven_group(weapon_riven_type(weapon, dispo_rows)) if weapon else "rifle")
    buffs = [str(x) for x in body.get("buffs") or [] if x]
    res = riven_calc(group, dispo, buffs, str(body.get("curse")) if body.get("curse") else None, rank)
    res["weapon"] = {"en": weapon["en"], "ja": weapon["ja"], "dispo": weapon["dispo"]} if weapon else None
    return res
