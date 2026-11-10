"""開発者のビルド(同梱の data/builds/dev_builds.json)の作成と検査

中身はビルド管理の builds.json と同じ形のビルド(images は配らない)に、外側の as_of(いつ時点か)を付けたもの。
作るのは開発用の tools/dev_builds.py(make_dev_builds)。ツールから書き込まない。
Q&A が読み、利用者が選べばビルド管理に追加できる(既存のビルドは上書きしない)。
"""
from __future__ import annotations

from datetime import date

from wfp.core.archon import clean_shards, find_effect, shard_text
from wfp.core.errors import TextError
from wfp.core.text import norm
from wfp.core.const import BUILD_TYPES, DEV_BUILD_KEYS, DEV_BUILD_LANGS, DEV_BUILD_NOTE, DEV_BUILD_VARIANTS, DEV_BUILDS_TAG
from wfp.core.helminth import clean_helminth, subsume_frame


def _is_date(value: object) -> bool:
    """YYYY-MM-DD の日付の文字列か"""
    if not isinstance(value, str) or len(value) != 10:
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _is_str_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(x, str) and x.strip() for x in value)


def make_dev_builds(builds: list[dict], as_of: str, tag: str = DEV_BUILDS_TAG) -> dict:
    """ビルド管理のビルドから、タグ tag の付いたものを選んで dev_builds.json の中身にする。

    項目は DEV_BUILD_KEYS の順で、無い項目は書かない(images など一覧に無い項目は捨てる)。タグの照合は norm。
    """
    picked = [b for b in builds if isinstance(b, dict) and any(norm(str(x)) == norm(tag) for x in b.get("tags") or [])]
    return {"as_of": as_of, "builds": [{k: b[k] for k in DEV_BUILD_KEYS if k in b} for b in picked]}


def check_dev_builds(raw: object, subsume: list[dict], archon: dict) -> list[str]:
    """同梱データの検査(テストと tools/dev_builds.py 用)。見つかった問題の一覧(無ければ空)。

    subsume は core.helminth.subsume_list、archon は core.archon.shard_list の結果。
    名前辞書(MOD・アルケイン・対象の名前)は同梱しないので見ない(tools/dev_builds.py の name_problems)。
    """
    if not isinstance(raw, dict):
        return ["中身が JSON のオブジェクトではない"]
    problems: list[str] = []
    if not _is_date(raw.get("as_of")):
        problems.append("as_of が YYYY-MM-DD の日付ではない")
    if set(raw) - {"as_of", "builds"}:
        problems.append(f"知らない項目 {sorted(set(raw) - {'as_of', 'builds'})}")
    builds = raw.get("builds")
    if not isinstance(builds, list) or not builds:
        return problems + ["builds が無い"]
    seen: set[str] = set()
    for i, b in enumerate(builds, 1):
        if not isinstance(b, dict):
            problems.append(f"{i}件目: オブジェクトではない")
            continue
        name = b.get("name")
        where = f"{i}件目({name})" if isinstance(name, str) else f"{i}件目"
        problems += [f"{where}: {p}" for p in _check_build(b, subsume, archon)]
        if isinstance(name, str) and name.strip():
            if norm(name) in seen:
                problems.append(f"{where}: name が重複")
            seen.add(norm(name))
    return problems


def _check_build(b: dict, subsume: list[dict], archon: dict) -> list[str]:
    """ビルド1件の検査(check_dev_builds から)"""
    problems: list[str] = []
    if set(b) - set(DEV_BUILD_KEYS):
        problems.append(f"知らない項目 {sorted(set(b) - set(DEV_BUILD_KEYS))}")
    for key in ("name", "target"):
        if not isinstance(b.get(key), str) or not b[key].strip():
            problems.append(f"{key} が無い")
    btype = b.get("type")
    if btype not in BUILD_TYPES:
        problems.append(f"type が {list(BUILD_TYPES)} のどれでもない")
    forma = b.get("forma", 0)
    if not isinstance(forma, int) or isinstance(forma, bool) or forma < 0:
        problems.append("forma が 0 以上の整数ではない")
    for key in ("mods", "arcanes", "tags"):
        if key in b and not _is_str_list(b[key]):
            problems.append(f"{key} が文字列の一覧ではない")
    note = b.get("note", "")
    if not (isinstance(note, str) or (isinstance(note, dict) and set(note) <= set(DEV_BUILD_LANGS)
                                      and all(isinstance(v, str) for v in note.values()))):
        problems.append(f"note が文字列か {list(DEV_BUILD_LANGS)} の文字列ではない")
    if "as_of" in b and not _is_date(b["as_of"]):
        problems.append("as_of が YYYY-MM-DD の日付ではない")
    problems += _check_extras(b, btype, subsume, archon)
    return problems


def _check_extras(b: dict, btype: object, subsume: list[dict], archon: dict) -> list[str]:
    """Helminth・アルコンの欠片の検査(Warframe のビルドだけに書ける。ビルド管理の保存と同じ検査)"""
    problems: list[str] = []
    if btype != "frame":
        return [f"{key} は Warframe のビルドにだけ書ける" for key in ("helminth", "shards") if key in b]
    if "helminth" in b:
        try:
            clean = clean_helminth("frame", b["helminth"])
        except TextError as e:
            clean, problems = None, problems + [f"helminth: {e}"]
        if clean is None and not problems:
            problems.append("helminth が空(無ければ項目ごと書かない)")
        elif clean is not None and subsume_frame(subsume, clean["ability"]) is None:
            problems.append(f"helminth: 吸収一覧に無いアビリティ {clean['ability']}")
    if "shards" in b:
        try:
            clean = clean_shards("frame", b["shards"], archon)
        except TextError as e:
            return problems + [f"shards: {e}"]
        if clean is None:
            problems.append("shards が空(無ければ項目ごと書かない)")
        elif len(b["shards"]) != len(clean):
            problems.append(f"shards の枠が {len(clean)} 個ではない")
    return problems


def name_problems(raw: dict, names) -> list[str]:
    """名前辞書(core.names.Names)に無い MOD・アルケイン・対象の名前の一覧(tools/dev_builds.py の注意。止めない)"""
    out: list[str] = []
    for b in raw.get("builds") or []:
        where = b.get("name", "?")
        if b.get("target") and not names.has(b["target"]):
            out.append(f"{where}: 対象 {b['target']}")
        out += [f"{where}: MOD {m}" for m in b.get("mods") or [] if not names.is_mod(m)]
        known = {norm(a) for a in names.arcanes}
        out += [f"{where}: アルケイン {a}" for a in b.get("arcanes") or [] if norm(a) not in known]
    return out


def dev_build_list(raw: object) -> list[dict]:
    """dev_builds.json の中身から、Q&A で使うビルドの一覧を作る(読めなければ空)。

    形の崩れたビルド(name・target が無い・種別が不明)は飛ばす。as_of はビルドごとの値か外側の値を入れておく。
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("builds"), list):
        return []
    outer = raw.get("as_of") if _is_date(raw.get("as_of")) else ""
    out: list[dict] = []
    for b in raw["builds"]:
        if not isinstance(b, dict) or b.get("type") not in BUILD_TYPES:
            continue
        if not all(isinstance(b.get(k), str) and b[k].strip() for k in ("name", "target")):
            continue
        entry = {k: b[k] for k in DEV_BUILD_KEYS if k in b}
        entry["as_of"] = b["as_of"] if _is_date(b.get("as_of")) else outer
        out.append(entry)
    return out


def variant_base(target: str) -> str | None:
    """対象の名前の末尾が派生の語(DEV_BUILD_VARIANTS。Prime・Umbra)なら、それを除いた基本の名前。違えば None"""
    head, _, tail = target.strip().rpartition(" ")
    return head.strip() if head.strip() and norm(tail) in {norm(v) for v in DEV_BUILD_VARIANTS} else None


def builds_for(builds: list[dict], name: str) -> list[dict]:
    """名前(英名)に当たる開発者のビルド。対象(target)が同じものを全部(例: Jade → Jade と Glory)。
    基本の名前なら派生(Prime・Umbra)を対象にしたビルドも後ろに付ける(例: Ash → Ash・Ash Prime の順)。
    派生の名前(Ash Prime)では基本のビルドは混ぜない。対象に当たらなければビルド名で当てる(例: Glory → Glory だけ)。照合は norm"""
    key = norm(name)
    same = [b for b in builds if norm(b["target"]) == key]
    variants = [b for b in builds if norm(b["target"]) != key and norm(variant_base(b["target"]) or "") == key]
    return same + variants or [b for b in builds if norm(b["name"]) == key]


def find_dev_build(builds: list[dict], name: str) -> dict | None:
    """ビルド名(norm で照合)から開発者のビルド。無ければ None"""
    return next((b for b in builds if norm(b["name"]) == norm(name)), None)


def note_text(note: object, lang: str = "ja") -> str:
    """note(文字列か {ja, en})の文。lang が無ければもう一方"""
    if isinstance(note, dict):
        other = [v for k, v in note.items() if k != lang and isinstance(v, str)]
        return note.get(lang) if isinstance(note.get(lang), str) and note[lang] else (other[0] if other else "")
    return note if isinstance(note, str) else ""


def adopt_entry(b: dict, name: str) -> dict:
    """開発者のビルドを、ビルド管理に保存する形(save_build に渡す本文)にする。
    名前は name。メモの末尾に「(開発者のビルド・<as_of>時点)」を付ける。画像は無し"""
    entry = {k: b[k] for k in DEV_BUILD_KEYS if k in b and k != "as_of"}
    note = note_text(b.get("note"))
    mark = DEV_BUILD_NOTE.format(as_of=b.get("as_of") or "?")
    return {**entry, "name": name, "note": f"{note}\n{mark}" if note else mark, "images": []}


def build_view(b: dict, names, subsume: list[dict], archon: dict, mod_stats=None) -> dict:
    """Q&A に出すビルドの表示(日本語のみ)。MOD は英名のままで、効果(最大ランク・日本語)を付ける({name, effect}。
    mod_stats(core.modstats.ModStats)が無い・一覧に無い MOD は効果が空)。アルケイン・対象は和名(無ければ英名)、Helminth と欠片は文にする"""
    helm = b.get("helminth")
    helm_text = ""
    if isinstance(helm, dict) and helm.get("ability"):
        owner = subsume_frame(subsume, helm["ability"])
        helm_text = f"{helm.get('slot')}番 → {helm['ability']}" + (f"({owner})" if owner else "")
    shards: list[str] = []
    for slot in b.get("shards") or []:
        hit = find_effect(archon, slot["color"], slot["effect"]) if isinstance(slot, dict) and archon.get("colors") else None
        if hit:
            color, effect = hit
            tau = slot.get("tauforged") is True
            shards.append(f"{color['ja']}{'(Tauforged)' if tau else ''}: {shard_text(effect, 'ja', tau, archon['tauforged_rate'])}")
        elif isinstance(slot, dict):
            shards.append(f"{slot.get('color')}: {slot.get('effect')}")
    return {"name": b["name"], "type": b["type"], "type_ja": BUILD_TYPES[b["type"]], "target": b["target"],
            "target_ja": names.ja(b["target"]), "forma": b.get("forma", 0),
            "mods": [{"name": m, "effect": mod_stats.effect(m, "ja") if mod_stats else ""} for m in b.get("mods") or []],
            "arcanes": [names.ja(a) for a in b.get("arcanes") or []],
            "helminth": helm_text, "shards": shards, "note": note_text(b.get("note")), "as_of": b.get("as_of", "")}
