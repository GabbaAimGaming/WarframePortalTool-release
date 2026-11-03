"""Helminth: 吸収できるアビリティの一覧(同梱の data/helminth/subsume.json)と、ビルドに書く Helminth の値の検査

名前はどれも英名(Export の日本語版でもアビリティ名・フレーム名は英語のまま)。
一覧に無いアビリティ名でもビルドには保存できる(画面は注意を出すだけ)。一覧の項目は Export に無くても消さない。
"""
from __future__ import annotations

from wfp.core.common import HELMINTH_SLOTS, TextError, txt


def subsume_list(raw: object) -> list[dict]:
    """subsume.json の中身から {frame, ability} の一覧を作る。形の崩れた行は飛ばす(読めなければ空)"""
    rows = raw.get("subsume") if isinstance(raw, dict) else None
    out: list[dict] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        frame, ability = row.get("frame"), row.get("ability")
        if isinstance(frame, str) and isinstance(ability, str) and frame.strip() and ability.strip():
            out.append({"frame": frame.strip(), "ability": ability.strip()})
    return out


def subsume_frame(entries: list[dict], ability: str) -> str | None:
    """アビリティ名(前後の空白を除き、大文字小文字は区別しない完全一致。画面の helmFrame と同じ)から持ち主のフレーム名。一覧に無ければ None"""
    key = ability.strip().lower()
    return next((e["frame"] for e in entries if e["ability"].lower() == key), None)


def clean_helminth(btype: str, value: object) -> dict | None:
    """ビルドの helminth の値 {slot, ability} を検査して整える。

    Warframe 以外の種別・未入力は None(項目を付けない)。番号とアビリティの片方だけ、番号が 1〜4 以外は TextError。
    """
    if btype != "frame" or not isinstance(value, dict):
        return None
    slot, ability = value.get("slot"), str(value.get("ability") or "").strip()
    if slot in (None, "") and not ability:
        return None
    if slot in (None, "") or not ability:
        raise TextError(txt("err.build.helminth.pair"))
    try:
        # 整数か整数の文字列だけ(画面は文字列で送る)。True や 2.5 は誤り
        num = int(str(slot).strip()) if isinstance(slot, (int, str)) and not isinstance(slot, bool) else 0
    except ValueError:
        num = 0
    if num not in HELMINTH_SLOTS:
        raise TextError(txt("err.build.helminth.slot"))
    return {"slot": num, "ability": ability}


def parse_helminth_arg(text: str) -> dict:
    """CLI の --helminth「3:Roar」を {slot, ability} にする(検査は clean_helminth)"""
    slot, sep, ability = text.partition(":")
    if not sep:
        raise TextError(txt("err.build.helminth.pair"))
    return {"slot": slot.strip(), "ability": ability.strip()}
