"""シミュレータ用のデータ(builder.json): 公式 Public Export の ExportWarframes / ExportWeapons(英語・日本語)から
フレームと武器の性能を抜き出して保存する。データ更新(core/update)と、シミュレータ用データだけの取得(api の /api/builder/update)で使う。

計算(フレーム性能・武器 DPS・Riven)は wfportal_builder。2026-11-10 に wfportal_builder から移した(D4)
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from wfp.core.const import (
    BUILDER_EXPORTS, EXPORT_SRC_GITHUB, EXPORT_SRC_OFFICIAL, SIM_CATS, SIM_DAMAGE_TYPES, SIM_WEAPON_CATS,
)
from wfp.core.errors import TextFailure, error_text
from wfp.core.i18n import name_txt, txt
from wfp.core.log import say
from wfp.fetch import exports
from wfp.store import gamedata

# ExportWeapons の damagePerShot は 20 要素の配列で、この順(表示名は SIM_DAMAGE_TYPES)
DAMAGE_KEYS = tuple(SIM_DAMAGE_TYPES)
# 組み立て式の部品(Kitgun・Zaw・アンプなど)は単体の性能にならないので除く
_MODULAR_PARTS = re.compile(r"/(OperatorAmplifiers|ModularMelee[^/]*|SUModular[^/]*|InfKitGun|Hoverboard|ZanukaPetParts|MoaPetParts)/")


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
                # desc は日本語(無ければ英語)、desc_en は英語の説明(英語の画面で使う。古い builder.json には無い)
                abilities.append({"en": _clean_name(a["abilityName"]), "ja": _clean_name(aj.get("abilityName") or a["abilityName"]),
                                  "desc": _clean_text(aj.get("description") or a.get("description")),
                                  "desc_en": _clean_text(a.get("description"))})
            frames[name.lower()] = {
                "en": name, "ja": _clean_name(j.get("name") or name),
                "health": _num(it.get("health")), "shield": _num(it.get("shield")), "armor": _num(it.get("armor")),
                "energy": _num(it.get("power")), "sprint": _num(it.get("sprintSpeed"), 1.0),
                "passive": _clean_text(j.get("passiveDescription") or it.get("passiveDescription")),
                "passive_en": _clean_text(it.get("passiveDescription")),
                "abilities": abilities,
            }
        for it in doc.get("ExportWeapons", []) or []:
            if not isinstance(it, dict):
                continue
            uid, cat = it.get("uniqueName", ""), SIM_WEAPON_CATS.get(it.get("productCategory"))
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
                 "shotgun": "shotgun" in uid.lower()}
            if cat != "melee":
                w.update(multishot=_num(it.get("multishot"), 1.0) or 1.0, magazine=_num(it.get("magazineSize")),
                         reload=_num(it.get("reloadTime")), trigger=str(it.get("trigger") or ""))
            weapons[(cat, name.lower())] = w
    order = list(SIM_CATS)
    return {"frames": sorted(frames.values(), key=lambda f: f["en"].lower()),
            "weapons": sorted(weapons.values(), key=lambda w: (order.index(w["cat"]), w["en"].lower()))}


def save_builder_data(d: Path, data: dict, source: str) -> dict:
    """抜き出したデータを builder.json に保存する(取得元 source と時刻を付ける)。フレームか武器が空なら保存しない"""
    if not data.get("frames") or not data.get("weapons"):
        raise TextFailure(txt("err.sim.empty"))
    data = {**data, "source": source, "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    gamedata.save_builder(d, data)
    return data


def update_builder_data(d: Path) -> bool:
    """シミュレータ用のデータだけを取得して builder.json に保存する(GitHub の展開済み → 公式の順)。進み具合は say で出す"""
    say(txt("log.fetching.sim"))
    errors = []
    fetchers = ((EXPORT_SRC_GITHUB, exports.fetch_export_github), (EXPORT_SRC_OFFICIAL, exports.fetch_export))
    for label, fetch in fetchers:
        say(txt("log.source", src=name_txt("export.src.", label)), 1)
        try:
            data = save_builder_data(d, extract_builder_data(fetch("en", BUILDER_EXPORTS), fetch("ja", BUILDER_EXPORTS)), label)
        except Exception as e:  # noqa: BLE001
            say(txt("log.failed", e=error_text(e)), 1)
            errors.append(txt("log.failed.what", what=name_txt("export.src.", label), e=error_text(e)))
            continue
        say(txt("log.sim.done2", f=str(len(data["frames"])), w=str(len(data["weapons"]))))
        return True
    say(txt("log.sim.fetchfail", e=errors))
    return False
