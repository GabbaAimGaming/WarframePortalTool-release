"""画面向け API: 個人データ(MOD 所持・マスター(ゲーム画面からの読み取りを含む)・クエスト・アルケイン・ビルド・画像の文字認識)"""
from __future__ import annotations

import re
import threading

import wfportal_msscan as msscan
import wfportal_ocr as ocr
from wfp.api.ocr import need_ocr, run_ocr
from wfp.api.store import ApiError, Raw, Store
from wfp.core.arcane import ArcaneNotFound, arcane_summary, arcane_table, set_arcanes_owned
from wfp.core.errors import error_text
from wfp.core.i18n import txt
from wfp.core.text import norm
from wfp.core.const import ARCANE_CATS, BUILD_TYPES, MASTERY_CATS, MOD_TYPES, POLARITY_EN, QUEST_CATS, SOURCE_CATS
from wfp.core.archon import clean_shards, shard_list
from wfp.core.build import arcane_pairs, canon_arcanes
from wfp.core.devbuilds import adopt_entry, dev_build_list, find_dev_build
from wfp.core.helminth import clean_helminth, subsume_list
from wfp.core.mastery import mastery_items, mastery_summary, mastery_table
from wfp.core.mods import mod_table
from wfp.core.quests import QuestNotFound, quest_items, quest_summary, quest_table, set_quests_done
from wfp.store import appdata, build_images, userdata


def mods_list(store: Store) -> dict:
    names = store.names()
    if not names.mods:
        raise ApiError(txt("err.mods.nodata"), 409)
    rows = mod_table(names, store.drops(), store.sources(), userdata.load_owned(store.d))
    # 種別・入手先の種類は並びだけを返す(表示名は画面の I18N の mod.type.<キー> / src.cat.<キー>)
    return {"mods": rows, "types": list(MOD_TYPES), "cats": list(SOURCE_CATS),
            "polarities": dict(POLARITY_EN)}


def set_owned(store: Store, body: dict) -> dict:
    names = store.names()
    valid = {m["en"].lower() for m in names.mods}
    targets = body.get("en")
    targets = [targets] if isinstance(targets, str) else list(targets or [])
    with userdata.editing(store.d, "mods_owned") as owned:
        for en in targets:
            k = str(en).lower()
            if k not in valid:
                raise ApiError(txt("err.mods.unknown", name=str(en)), 404)
            (owned.add if body.get("owned") else owned.discard)(k)
    return {"owned": len(owned)}


def mastery_list(store: Store) -> dict:
    names = store.names()
    if not names.mastery:
        raise ApiError(txt("err.mastery.nodata"), 409)
    rows = mastery_table(names, userdata.load_mastered(store.d))
    # カテゴリーは並びだけ(表示名は画面の I18N の mastery.cat.<キー>)
    return {"rows": rows, "cats": list(MASTERY_CATS), "summary": mastery_summary(rows)}


def set_mastered(store: Store, body: dict) -> dict:
    ids = body.get("ids")
    ids = [ids] if isinstance(ids, str) else list(ids or [])
    valid = {m["id"] for m in mastery_items(store.names())}
    with userdata.editing(store.d, "mastered") as done:
        for i in ids:
            if i not in valid:
                raise ApiError(txt("err.mastery.unknown", id=str(i)), 404)
            (done.add if body.get("done") else done.discard)(i)
    rows = mastery_table(store.names(), done)
    return {"summary": mastery_summary(rows)}


def quests_list(store: Store) -> dict:
    """クエスト・ジャンクションの一覧。前提は同梱の flow.json なので、データ更新の前でも出る(名前は flow.json のもの)"""
    rows = quest_table(store.names(), userdata.load_quests_done(store.d))
    # 種類・状態はキーのまま(表示名は画面の I18N の quest.cat.<キー> / quest.state.<キー>)。export は Export の名前を使えているか
    return {"rows": rows, "cats": list(QUEST_CATS), "summary": quest_summary(rows), "export": bool(store.names().quests)}


def set_quests(store: Store, body: dict) -> dict:
    """body: {"ids": id or [id], "done": bool}。前提が足りない・ほかの完了済みの前提になっているときは 409 で何も変えない"""
    ids = body.get("ids")
    ids = [ids] if isinstance(ids, str) else list(ids or [])
    names = store.names()
    with userdata.editing(store.d, "quests_done") as done:  # 前提の検査と書き込みの間に、ほかの変更が割り込まない
        try:
            new = set_quests_done(quest_items(names), done, [str(i) for i in ids], bool(body.get("done")))
        except ValueError as e:
            raise ApiError(error_text(e), 404 if isinstance(e, QuestNotFound) else 409)
        done.clear()
        done.update(new)
    rows = quest_table(names, done)  # 状態は前提の完了で変わるので、一覧ごと返す
    return {"rows": rows, "summary": quest_summary(rows)}


def arcanes_list(store: Store) -> dict:
    names = store.names()
    if not names.arcane_list:
        raise ApiError(txt("err.arcane.nodata"), 409)
    rows = arcane_table(names, userdata.load_arcanes_owned(store.d), store.all_items())
    # カテゴリーは並びだけ(表示名は画面の I18N の arcane.cat.<キー>)
    return {"rows": rows, "cats": list(ARCANE_CATS), "summary": arcane_summary(rows)}


def set_arcanes(store: Store, body: dict) -> dict:
    """body: {"en": 名前 or [名前], "owned": bool, "rank": int (省略可)}"""
    targets = body.get("en")
    targets = [targets] if isinstance(targets, str) else list(targets or [])
    rank = body.get("rank")
    if rank is not None and (isinstance(rank, bool) or not isinstance(rank, int)):
        raise ApiError(txt("err.arcane.rank", rank=str(rank)))
    names = store.names()
    with userdata.editing(store.d, "arcanes_owned") as owned:
        try:
            set_arcanes_owned(names, owned, targets, bool(body.get("owned")), rank, store.all_items())
        except ValueError as e:
            raise ApiError(error_text(e), 404 if isinstance(e, ArcaneNotFound) else 400)
    return {"summary": arcane_summary(arcane_table(names, owned, store.all_items()))}


def mod_effects_of(store: Store, builds: list[dict]) -> dict:
    """ビルドの MOD の効果(最大ランク)。{英名(小文字): {ja, en}}。mod_stats.json が無い・一覧に無い MOD は入れない(画面は名前だけ出す)"""
    stats = store.mod_stats()
    return stats.effects([m for b in builds for m in b.get("mods") or []]) if stats else {}


def with_effects(store: Store, builds: list[dict], **extra) -> dict:
    """ビルドの一覧を返す応答(保存・追加のあとも MOD の効果を付ける)"""
    return {"builds": builds, "mod_effects": mod_effects_of(store, builds), **extra}


def builds_list(store: Store) -> dict:
    # 種別は並び(キー)だけ。表示名は画面の I18N の build.type.<キー>。helminth は入力欄の候補({frame, ability}。英名)
    # archon はアルコンの欠片の色と効果の一覧({tauforged_rate, colors}。名前と文は ja・en の両方)
    # arcanes はアルケイン欄の候補([{en, ja}]。保存は英名、表示は画面が言語で選ぶ)
    builds = userdata.load_builds(store.d)
    return {"builds": builds, "mod_effects": mod_effects_of(store, builds), "types": list(BUILD_TYPES), "arcanes": arcane_pairs(store.names()),
            "helminth": subsume_list(appdata.read_helminth()), "archon": shard_list(appdata.read_archon())}


def clean_build(body: dict, names) -> dict:
    """names: アルケインを英名にそろえるための名前辞書(和名で書いても英名で保存する)"""
    name = str(body.get("name", "")).strip()
    if not name:
        raise ApiError(txt("err.build.name"))
    btype = body.get("type") if body.get("type") in BUILD_TYPES else "other"
    try:
        forma = max(0, int(body.get("forma") or 0))
    except (TypeError, ValueError):
        raise ApiError(txt("err.build.forma"))
    try:
        helminth = clean_helminth(btype, body.get("helminth"))
        shards = clean_shards(btype, body.get("shards"), shard_list(appdata.read_archon()))
    except ValueError as e:
        raise ApiError(error_text(e))
    split = lambda v: [x.strip() for x in re.split(r"[\n,、]", "\n".join(v) if isinstance(v, list) else str(v or "")) if x.strip()]
    images = body.get("images") or []
    return {"name": name, "type": btype, "target": str(body.get("target", "")).strip(), "forma": forma,
            "mods": split(body.get("mods")), "arcanes": canon_arcanes(names, split(body.get("arcanes"))),
            "tags": split(body.get("tags")), "note": str(body.get("note", "")).strip(),
            "images": [str(x) for x in images if isinstance(x, str) and build_images.IMAGE_NAME_RE.match(x)] if isinstance(images, list) else [],
            # Helminth は Warframe のビルドで入力したときだけ付ける(無ければ項目ごと無い)
            **({"helminth": helminth} if helminth else {}),
            # アルコンの欠片も同じ(5枠の一覧。空の枠は null)
            **({"shards": shards} if shards else {})}


def save_build(store: Store, body: dict) -> list[dict]:
    entry = clean_build(body, store.names())
    original = str(body.get("original_name") or "")
    same = lambda b, n: norm(b["name"]) == norm(n)
    with userdata.editing(store.d, "builds") as builds:  # 名前の重なりの検査と書き込みの間に、ほかの変更が割り込まない
        if original:
            idx = next((i for i, b in enumerate(builds) if same(b, original)), None)
            if idx is None:
                raise ApiError(txt("err.build.original"), 404)
            if not same(entry, original) and any(same(b, entry["name"]) for b in builds):
                raise ApiError(txt("err.build.dup"))
            # 画像は「元のビルドに付いていたもの」だけ残せる。外されたものはファイルも消す
            before = builds[idx].get("images", [])
            entry["images"] = [x for x in entry["images"] if x in before]
            removed = [x for x in before if x not in entry["images"]]
            builds[idx] = entry
        else:
            if any(same(b, entry["name"]) for b in builds):
                raise ApiError(txt("err.build.dup"))
            entry["images"], removed = [], []
            builds.append(entry)
    build_images.delete_build_images(store.d, removed)  # 画像のファイルは書き込みが確定してから消す
    return builds


def add_build_image(store: Store, name: str, data: bytes) -> list[dict]:
    with userdata.editing(store.d, "builds") as builds:
        b = next((x for x in builds if norm(x["name"]) == norm(name)), None)
        if b is None:
            raise ApiError(txt("err.build.none"), 404)
        if len(b.get("images", [])) >= 30:
            raise ApiError(txt("err.build.images", n="30"))
        try:
            fname = build_images.save_build_image(store.d, data)
        except ValueError as e:
            raise ApiError(error_text(e), 415)
        b.setdefault("images", []).append(fname)
    return builds


def adopt_dev_build(store: Store, body: dict) -> dict:
    """POST /api/builds/adopt: 開発者のビルド(同梱の dev_builds.json)をビルド管理に追加する。本文 {build: 開発者のビルド名, name: 保存する名前}。
    画面はビルド名だけを送り、中身はここで読み直す。同じ名前のビルドがあれば 409(上書きしない。画面で名前を入れ直してもらう)"""
    src = find_dev_build(dev_build_list(appdata.read_dev_builds()), str(body.get("build") or ""))
    if src is None:
        raise ApiError(txt("err.qa.build.none"), 404)
    name = str(body.get("name") or "").strip()
    if not name:
        raise ApiError(txt("err.build.name"))
    if any(norm(b["name"]) == norm(name) for b in userdata.load_builds(store.d)):
        raise ApiError(txt("err.build.dup"), 409)
    return with_effects(store, save_build(store, adopt_entry(src, name)), name=name)


def delete_build(store: Store, name: str) -> list[dict]:
    with userdata.editing(store.d, "builds") as builds:
        gone = [b for b in builds if norm(b["name"]) == norm(name)]
        if not gone:
            raise ApiError(txt("err.build.none"), 404)
        builds[:] = [b for b in builds if norm(b["name"]) != norm(name)]
    for b in gone:  # 画像のファイルは書き込みが確定してから消す
        build_images.delete_build_images(store.d, b.get("images", []))
    return builds


def analyze_build_image(store: Store, image_name: str, data: bytes | None) -> dict:
    """保存済みの画像(image_name)か、送られてきた画像(data)を解析する"""
    need_ocr()
    names = store.names()
    if not names.mods:
        raise ApiError(txt("err.mods.nodata"), 409)
    if image_name:
        p = build_images.build_image_path(store.d, image_name)
        if p is None:
            raise ApiError(txt("err.image.none"), 404)
        data = p.read_bytes()
    if not data or not build_images.image_ext(data):
        raise ApiError(txt("err.image.format"), 415)
    raw = run_ocr(data, cache_dir=store.d / "ocr_cache")
    matcher = store.derived("@matcher", (names,), lambda: ocr.build_matcher(names))
    result = ocr.analyze(raw, names, matcher)
    result["has_items"] = bool(names.items)
    return result


def scan_mods(store: Store, data: bytes) -> dict:
    """ゲームの MOD 一覧画面(の画像)から MOD 名を読み取る。所持チェックを付けるかは画面側で決める"""
    need_ocr()
    names = store.names()
    if not names.mods:
        raise ApiError(txt("err.mods.nodata"), 409)
    if not data or not build_images.image_ext(data):
        raise ApiError(txt("err.image.format"), 415)
    # 何度も読むので、英語だけ・拡大は控えめにして速さを優先する。結果は保存しない
    raw = run_ocr(data, cache_dir=None, langs="en-US", scale=1.5)
    matcher = store.derived("@modmatcher", (names,), lambda: ocr.NameMatcher([("mod", m["en"], m) for m in names.mods]))
    result = ocr.analyze(raw, names, matcher)
    owned = userdata.load_owned(store.d)
    found, seen = [], set()
    for m in result["mods"]:
        k = m["en"].lower()
        if m["kind"] == "mod" and k not in seen:
            seen.add(k)
            found.append({"en": m["en"], "ja": m["ja"], "score": m["score"], "read": m["read"], "owned": k in owned})
    return {"found": found, "lines": len(result["lines"])}


def scan_mastery(store: Store, data: bytes) -> dict:
    """ゲームの「プロフィール → エクストラ」の装備一覧(の画像)からマスター済みを読み取る。印を付けるかは画面側で決める
    (付けるときは POST /api/mastery)。ここは何も書き込まない"""
    need_ocr()
    names = store.names()
    if not names.mastery:
        raise ApiError(txt("err.mastery.nodata"), 409)
    if not data or build_images.image_ext(data) != "png":
        raise ApiError(txt("err.msscan.png"), 415)
    # PNG の展開(大きい画像で1〜2秒)は、文字認識(別のプロセス)を待つあいだに並べて行う
    decoded: dict = {}

    def decode() -> None:
        try:
            decoded["png"] = msscan.read_png(data)
        except ValueError as err:
            decoded["error"] = err
    worker = threading.Thread(target=decode, daemon=True)
    worker.start()
    try:
        # 日本語の小さい文字(ランク表記)を読むので、拡大は既定のまま。結果は保存しない
        raw = run_ocr(data, cache_dir=None, langs=ocr.DEFAULT_LANGS)
    finally:
        worker.join()
    if "error" in decoded:
        raise ApiError(error_text(decoded["error"]), 415)
    index = store.derived("@msindex", (names,), lambda: msscan.build_index(mastery_items(names)))
    return msscan.analyze_mastery(raw, decoded["png"], index, userdata.load_mastered(store.d))


def build_image(store: Store, name: str) -> Raw:
    """ビルドの画像。ファイル名は毎回ちがう乱数なので、長くキャッシュしてよい"""
    p = build_images.build_image_path(store.d, name)
    if p is None:
        raise ApiError(txt("err.image.none"), 404)
    return Raw(p.read_bytes(), build_images.IMAGE_MIME[p.suffix[1:]], "private, max-age=31536000, immutable")


# (メソッド, パス) -> 処理。c はリクエスト(wfp/api/server.py の Request)。パスが / で終わるものは前方一致
ROUTES = {
    ("GET", "/api/mods"): lambda c: mods_list(c.store),
    ("POST", "/api/mods/owned"): lambda c: set_owned(c.store, c.body()),
    ("POST", "/api/mods/scan"): lambda c: scan_mods(c.store, c.image()),
    ("GET", "/api/mastery"): lambda c: mastery_list(c.store),
    ("POST", "/api/mastery"): lambda c: set_mastered(c.store, c.body()),
    ("POST", "/api/mastery/scan"): lambda c: scan_mastery(c.store, c.image()),
    ("GET", "/api/quests"): lambda c: quests_list(c.store),
    ("POST", "/api/quests"): lambda c: set_quests(c.store, c.body()),
    ("GET", "/api/arcanes"): lambda c: arcanes_list(c.store),
    ("POST", "/api/arcanes/owned"): lambda c: set_arcanes(c.store, c.body()),
    ("GET", "/api/builds"): lambda c: builds_list(c.store),
    ("POST", "/api/builds"): lambda c: with_effects(c.store, save_build(c.store, c.body())),
    ("DELETE", "/api/builds"): lambda c: {"builds": delete_build(c.store, c.q.get("name", ""))},
    ("POST", "/api/builds/adopt"): lambda c: adopt_dev_build(c.store, c.body()),
    ("POST", "/api/build-image"): lambda c: {"builds": add_build_image(c.store, c.q.get("name", ""), c.image())},
    ("GET", "/api/build-image/"): lambda c: build_image(c.store, c.path.rsplit("/", 1)[1]),
    ("POST", "/api/build-analyze"): lambda c: analyze_build_image(
        c.store, c.q.get("image", ""), None if c.q.get("image", "") else c.image()),
}
