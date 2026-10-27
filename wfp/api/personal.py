"""画面向け API: 個人データ(MOD 所持・マスター・アルケイン・ビルド・画像の文字認識)"""
from __future__ import annotations

import re
import threading

import wfportal_ocr as ocr
from wfp.api.store import ApiError, Raw, Store
from wfp.core.arcane import ArcaneNotFound, arcane_summary, arcane_table, set_arcanes_owned
from wfp.core.common import ARCANE_CATS, BUILD_TYPES, MASTERY_CATS, MOD_TYPES, POLARITY_EN, SOURCE_CATS, error_text, norm, txt
from wfp.core.mastery import mastery_items, mastery_summary, mastery_table
from wfp.core.mods import mod_table
from wfp.store import build_images, userdata


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
    owned = userdata.load_owned(store.d)
    for en in targets:
        k = str(en).lower()
        if k not in valid:
            raise ApiError(txt("err.mods.unknown", name=str(en)), 404)
        (owned.add if body.get("owned") else owned.discard)(k)
    userdata.save_owned(store.d, owned)
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
    done = userdata.load_mastered(store.d)
    for i in ids:
        if i not in valid:
            raise ApiError(txt("err.mastery.unknown", id=str(i)), 404)
        (done.add if body.get("done") else done.discard)(i)
    userdata.save_mastered(store.d, done)
    rows = mastery_table(store.names(), done)
    return {"summary": mastery_summary(rows)}


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
    owned = userdata.load_arcanes_owned(store.d)
    try:
        set_arcanes_owned(names, owned, targets, bool(body.get("owned")), rank, store.all_items())
    except ValueError as e:
        raise ApiError(error_text(e), 404 if isinstance(e, ArcaneNotFound) else 400)
    userdata.save_arcanes_owned(store.d, owned)
    return {"summary": arcane_summary(arcane_table(names, owned, store.all_items()))}


def builds_list(store: Store) -> dict:
    # 種別は並び(キー)だけ。表示名は画面の I18N の build.type.<キー>
    return {"builds": userdata.load_builds(store.d), "types": list(BUILD_TYPES), "arcanes": store.names().arcanes}


def clean_build(body: dict) -> dict:
    name = str(body.get("name", "")).strip()
    if not name:
        raise ApiError(txt("err.build.name"))
    btype = body.get("type") if body.get("type") in BUILD_TYPES else "other"
    try:
        forma = max(0, int(body.get("forma") or 0))
    except (TypeError, ValueError):
        raise ApiError(txt("err.build.forma"))
    split = lambda v: [x.strip() for x in re.split(r"[\n,、]", "\n".join(v) if isinstance(v, list) else str(v or "")) if x.strip()]
    images = body.get("images") or []
    return {"name": name, "type": btype, "target": str(body.get("target", "")).strip(), "forma": forma,
            "mods": split(body.get("mods")), "arcanes": split(body.get("arcanes")),
            "tags": split(body.get("tags")), "note": str(body.get("note", "")).strip(),
            "images": [str(x) for x in images if isinstance(x, str) and build_images.IMAGE_NAME_RE.match(x)] if isinstance(images, list) else []}


def save_build(store: Store, body: dict) -> list[dict]:
    entry = clean_build(body)
    builds = userdata.load_builds(store.d)
    original = str(body.get("original_name") or "")
    same = lambda b, n: norm(b["name"]) == norm(n)
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
    userdata.save_builds(store.d, builds)
    build_images.delete_build_images(store.d, removed)
    return builds


def add_build_image(store: Store, name: str, data: bytes) -> list[dict]:
    builds = userdata.load_builds(store.d)
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
    userdata.save_builds(store.d, builds)
    return builds


def delete_build(store: Store, name: str) -> list[dict]:
    builds = userdata.load_builds(store.d)
    keep = [b for b in builds if norm(b["name"]) != norm(name)]
    if len(keep) == len(builds):
        raise ApiError(txt("err.build.none"), 404)
    userdata.save_builds(store.d, keep)
    for b in builds:
        if b not in keep:
            build_images.delete_build_images(store.d, b.get("images", []))
    return keep


_ocr_info: dict | None = None


_ocr_lock = threading.Lock()


def ocr_info() -> dict:
    """Windows の文字認識が使えるか(初回だけ調べて覚えておく)。reason は使えない理由のテキスト指定(使えるときは空)"""
    global _ocr_info
    with _ocr_lock:
        if _ocr_info is None:
            try:
                langs = ocr.ocr_languages()
                _ocr_info = {"available": bool(langs), "languages": langs,
                             "english": any(x.lower().startswith("en") for x in langs),
                             "reason": "" if langs else txt("err.ocr.nolang")}
            except ocr.OcrUnavailable as e:
                _ocr_info = {"available": False, "languages": [], "english": False, "reason": error_text(e)}
        return _ocr_info


def analyze_build_image(store: Store, image_name: str, data: bytes | None) -> dict:
    """保存済みの画像(image_name)か、送られてきた画像(data)を解析する"""
    info = ocr_info()
    if not info["available"]:
        raise ApiError(info["reason"] or txt("err.ocr.none"), 501)
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
    try:
        raw = ocr.run_ocr_bytes(data, cache_dir=store.d / "ocr_cache")
    except ocr.OcrUnavailable as e:
        raise ApiError(error_text(e), 502)
    with store._lock:
        matcher = store._cache.get("@matcher")
        if not matcher or matcher[0] is not names:
            matcher = (names, ocr.build_matcher(names))
            store._cache["@matcher"] = matcher
    result = ocr.analyze(raw, names, matcher[1])
    result["has_items"] = bool(names.items)
    return result


def scan_mods(store: Store, data: bytes) -> dict:
    """ゲームの MOD 一覧画面(の画像)から MOD 名を読み取る。所持チェックを付けるかは画面側で決める"""
    info = ocr_info()
    if not info["available"]:
        raise ApiError(info["reason"] or txt("err.ocr.none"), 501)
    names = store.names()
    if not names.mods:
        raise ApiError(txt("err.mods.nodata"), 409)
    if not data or not build_images.image_ext(data):
        raise ApiError(txt("err.image.format"), 415)
    try:
        # 何度も読むので、英語だけ・拡大は控えめにして速さを優先する。結果は保存しない
        raw = ocr.run_ocr_bytes(data, cache_dir=None, langs="en-US", scale=1.5)
    except ocr.OcrUnavailable as e:
        raise ApiError(error_text(e), 502)
    with store._lock:
        cached = store._cache.get("@modmatcher")
        if not cached or cached[0] is not names:
            cached = (names, ocr.NameMatcher([("mod", m["en"], m) for m in names.mods]))
            store._cache["@modmatcher"] = cached
    result = ocr.analyze(raw, names, cached[1])
    owned = userdata.load_owned(store.d)
    found, seen = [], set()
    for m in result["mods"]:
        k = m["en"].lower()
        if m["kind"] == "mod" and k not in seen:
            seen.add(k)
            found.append({"en": m["en"], "ja": m["ja"], "score": m["score"], "read": m["read"], "owned": k in owned})
    return {"found": found, "lines": len(result["lines"])}


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
    ("GET", "/api/arcanes"): lambda c: arcanes_list(c.store),
    ("POST", "/api/arcanes/owned"): lambda c: set_arcanes(c.store, c.body()),
    ("GET", "/api/builds"): lambda c: builds_list(c.store),
    ("POST", "/api/builds"): lambda c: {"builds": save_build(c.store, c.body())},
    ("DELETE", "/api/builds"): lambda c: {"builds": delete_build(c.store, c.q.get("name", ""))},
    ("POST", "/api/build-image"): lambda c: {"builds": add_build_image(c.store, c.q.get("name", ""), c.image())},
    ("GET", "/api/build-image/"): lambda c: build_image(c.store, c.path.rsplit("/", 1)[1]),
    ("POST", "/api/build-analyze"): lambda c: analyze_build_image(
        c.store, c.q.get("image", ""), None if c.q.get("image", "") else c.image()),
    ("GET", "/api/ocr-info"): lambda c: ocr_info(),
}
