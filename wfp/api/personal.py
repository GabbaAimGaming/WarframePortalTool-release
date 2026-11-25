"""画面向け API: 個人データ(MOD 所持・マスター(ゲーム画面からの読み取りを含む)・クエスト・アルケイン・ToDo・ビルド・画像の文字認識)"""
from __future__ import annotations

import threading
from datetime import datetime, timezone

import wfportal_msscan as msscan
import wfportal_ocr as ocr
from wfp.api.ocr import need_ocr, run_ocr
from wfp.api.store import ApiError, Raw, Store, file_stamp, need_drops, str_list
from wfp.core.arcane import ArcaneNotFound, arcane_table, set_arcanes_owned
from wfp.core.errors import error_text
from wfp.core.i18n import txt
from wfp.core.text import norm
from wfp.core.const import (
    ARCANE_CATS, BUILD_IMAGE_MAX, BUILD_TYPES, MASTERY_CATS, MASTERY_EXTRA_FILE, MOD_TYPES, OCR_CACHE_DIR, OCR_DEFAULT_LANGS,
    POLARITY_EN, QUEST_CATS, SOURCE_CATS,
)
from wfp.core.archon import shard_list
from wfp.core.build import arcane_pairs, make_build
from wfp.core.devbuilds import adopt_entry, dev_build_list, find_dev_build
from wfp.core.helminth import subsume_list
from wfp.core.mastery import add_source_cats, mastery_items, mastery_table, vaulted_owners
from wfp.core.mods import mod_table
from wfp.core.quests import QuestNotFound, quest_items, quest_summary, quest_table, set_quests_done
from wfp.core import todo
from wfp.drops.search import find_sources, part_sources, parts_by_owner
from wfp.store import appdata, build_images, gamedata, userdata


def mods_list(store: Store) -> dict:
    names = store.names()
    if not names.mods:
        raise ApiError(txt("err.mods.nodata"), 409)
    rows = mod_table(names, None, None, userdata.load_owned(store.d), userdata.load_confirmed(store.d), store.source_index())
    # 種別・入手先の種類は並びだけを返す(表示名は画面の I18N の mod.type.<キー> / src.cat.<キー>)
    return {"mods": rows, "types": list(MOD_TYPES), "cats": list(SOURCE_CATS),
            "polarities": dict(POLARITY_EN)}


def set_owned(store: Store, body: dict) -> dict:
    """所持を付け外しする。confirm: true なら利用者が確定した印も付ける(読み取りで飛ばす)。外すときは印も消す。
    所持と印は別の種類なので2回に分けて書く(印だけ書けなくても、次の読み取りでまた聞かれるだけ)"""
    names = store.names()
    valid = {m["en"].lower() for m in names.mods}
    keys = [en.lower() for en in str_list(body, "en")]
    for en, k in zip(str_list(body, "en"), keys):
        if k not in valid:
            raise ApiError(txt("err.mods.unknown", name=en), 404)
    add = bool(body.get("owned"))
    with userdata.editing(store.d, "mods_owned") as owned:
        for k in keys:
            (owned.add if add else owned.discard)(k)
    if not add or body.get("confirm"):
        with userdata.editing(store.d, "mods_confirmed") as confirmed:
            for k in keys:
                (confirmed.add if add else confirmed.discard)(k)
    return {"owned": len(owned)}


def mastery_list(store: Store) -> dict:
    names = store.names()
    if not names.mastery:
        raise ApiError(txt("err.mastery.nodata"), 409)
    rows = mastery_table(names, userdata.load_mastered(store.d))
    # いま作れない本体(入手不可のパーツがある)に vaulted。vault は判定できたか(できなければ画面はチェックを使えなくする)。
    # 入手先の種類(src_cats。本体 + パーツ)も付ける。src_ready は入手先を判定できたか: ドロップ表が無ければ判定しない
    # (行の詳細 /api/mastery/sources が 409 になるのと合わせる。パーツも引けないので本体だけの不完全な種類になる)。
    # ドロップ表が壊れていても一覧は出す(マスター一覧は names.json だけで開けるもの。判定・入手先なしで続ける)
    try:
        src = store.sources()
        vault = store.vault()
        vaulted = vaulted_owners(names, vault, src.part_owner if src else None)
        ready = vault.ready
        src_ready = store.drops() is not None
    except gamedata.DataBroken:
        vaulted, ready, src_ready = set(), False, False
    add_source_cats(rows, *((store.source_index(), mastery_parts(store)) if src_ready else ({}, {})))
    for r in rows:
        if r["en"].lower() in vaulted:
            r["vaulted"] = True
    # カテゴリー・入手先の種類は並びだけ(表示名は画面の I18N の mastery.cat.<キー> / src.cat.<キー>)。集計は画面が数える(創設者の切り替えがあるため)
    return {"rows": rows, "cats": list(MASTERY_CATS), "vault": ready, "src_ready": src_ready}


def mastery_parts(store: Store) -> dict[str, list[str]]:
    """本体 → パーツの表(drops/search の parts_by_owner)。候補の項目・名前辞書・入手先が変わったときだけ作り直す"""
    names, src, items = store.names(), store.sources(), store.all_items()
    return store.derived("@mastery_parts", (names, items, src),
                         lambda: parts_by_owner(items, names, src.part_owner if src else None))


def mastery_by_id(store: Store) -> dict[str, dict]:
    """マスター一覧の項目の表 {id: 項目}(mastery_items)。名前辞書か同梱の extra.json が変わったときだけ作り直す"""
    names = store.names()
    return store.derived("@mastery_ids", (names, *file_stamp(appdata.mastery_dir() / MASTERY_EXTRA_FILE)),
                         lambda: {m["id"]: m for m in mastery_items(names)})


def mastery_sources(store: Store, mid: str) -> dict:
    """マスター一覧の1行(id)の入手先: 本体そのものの行(rows)と、パーツごとの行(parts。drops/search の part_sources)。
    行の形は /api/item と同じ。イベント限定は含めない。本体 → パーツの表は Store.derived で1回だけ作る"""
    names = store.names()
    item = mastery_by_id(store).get(mid)
    if item is None:
        raise ApiError(txt("err.mastery.unknown", id=mid), 404)
    drops, src = need_drops(store), store.sources()
    vault = store.vault()
    table = mastery_parts(store)
    body = item["en"]
    return {"ja": item["ja"], "en": body, "unavailable": vault.unavailable(body),
            "rows": find_sources(body, drops, src, names, vault=vault),
            "parts": part_sources(table.get(norm(body), []), drops, src, names, vault=vault)}


def set_mastered(store: Store, body: dict) -> dict:
    ids = str_list(body, "ids")
    valid = mastery_by_id(store)
    with userdata.editing(store.d, "mastered") as done:
        for i in ids:
            if i not in valid:
                raise ApiError(txt("err.mastery.unknown", id=i), 404)
            (done.add if body.get("done") else done.discard)(i)
    return {"ok": True}


def quests_list(store: Store) -> dict:
    """クエスト・ジャンクションの一覧。前提は同梱の flow.json なので、データ更新の前でも出る(名前は flow.json のもの)"""
    rows = quest_table(store.names(), userdata.load_quests_done(store.d))
    # 種類・状態はキーのまま(表示名は画面の I18N の quest.cat.<キー> / quest.state.<キー>)。export は Export の名前を使えているか
    return {"rows": rows, "cats": list(QUEST_CATS), "summary": quest_summary(rows), "export": bool(store.names().quests)}


def set_quests(store: Store, body: dict) -> dict:
    """body: {"ids": id or [id], "done": bool}。前提が足りない・ほかの完了済みの前提になっているときは 409 で何も変えない"""
    ids = str_list(body, "ids")
    names = store.names()
    with userdata.editing(store.d, "quests_done") as done:  # 前提の検査と書き込みの間に、ほかの変更が割り込まない
        try:
            new = set_quests_done(quest_items(names), done, ids, bool(body.get("done")))
        except ValueError as e:
            raise ApiError(error_text(e), 404 if isinstance(e, QuestNotFound) else 409)
        done.clear()
        done.update(new)
    rows = quest_table(names, done)  # 状態は前提の完了で変わるので、一覧ごと返す
    return {"rows": rows, "summary": quest_summary(rows)}


def _utc_now() -> datetime:
    """ToDo の今の時刻(テストで差し替える)"""
    return datetime.now(timezone.utc)


def todo_list(store: Store) -> dict:
    """ToDo の一覧(完了かどうかは最後のリセットより後にチェックしたか。core/todo)"""
    return todo.todo_view(todo.clean_items(userdata.load_todo(store.d)), _utc_now())


# 変える操作: body の action -> (一覧, body, 今) を受けて一覧をその場で変える
TODO_ACTIONS = {
    "add": lambda items, b, now: todo.add_item(items, b.get("name"), b.get("kind")),
    "edit": lambda items, b, now: todo.edit_item(items, b.get("id"), b.get("name"), b.get("kind")),
    "delete": lambda items, b, now: todo.delete_item(items, b.get("id")),
    "move": lambda items, b, now: todo.move_item(items, b.get("id"), -1 if b.get("step") == -1 else 1),
    "check": lambda items, b, now: todo.check_item(items, b.get("id"), bool(b.get("done")), now),
}


def change_todo(store: Store, body: dict) -> dict:
    """body: {"action": TODO_ACTIONS のキー, ...}。誤りは 400、無い id は 404(何も書かない)。応答は一覧ごと(todo_list と同じ形)"""
    action = TODO_ACTIONS.get(body.get("action"))
    if action is None:
        raise ApiError(txt("err.todo.action", name=str(body.get("action"))), 400)
    now = _utc_now()
    with userdata.editing(store.d, "todo") as raw:
        items = todo.clean_items(raw)
        try:
            action(items, body, now)
        except todo.TodoError as e:
            raise ApiError(error_text(e), 404 if isinstance(e, todo.TodoNotFound) else 400)
        raw[:] = items
    return todo.todo_view(items, now)


def arcanes_list(store: Store) -> dict:
    names = store.names()
    if not names.arcane_list:
        raise ApiError(txt("err.arcane.nodata"), 409)
    rows = arcane_table(names, userdata.load_arcanes_owned(store.d), store.all_items(), index=store.source_index())
    # カテゴリー・入手先の種類は並びだけ(表示名は画面の I18N の arcane.cat.<キー> / src.cat.<キー>)。集計は画面が数える
    return {"rows": rows, "cats": list(ARCANE_CATS), "src_cats": list(SOURCE_CATS)}


def set_arcanes(store: Store, body: dict) -> dict:
    """body: {"en": 名前 or [名前], "owned": bool, "rank": int (省略可)}"""
    targets = str_list(body, "en")
    rank = body.get("rank")
    if rank is not None and (isinstance(rank, bool) or not isinstance(rank, int)):
        raise ApiError(txt("err.arcane.rank", rank=str(rank)))
    names = store.names()
    with userdata.editing(store.d, "arcanes_owned") as owned:
        try:
            set_arcanes_owned(names, owned, targets, bool(body.get("owned")), rank, store.all_items())
        except ValueError as e:
            raise ApiError(error_text(e), 404 if isinstance(e, ArcaneNotFound) else 400)
    return {"ok": True}


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
    """ビルド保存の本文を検査して保存する形にする(中身は core/build の make_build。CLI と共通)。
    画像は名前の形(build_images.IMAGE_NAME_RE)に合うものだけ残す。names: アルケインを英名にそろえるための名前辞書"""
    images = body.get("images") or []
    images = [x for x in images if isinstance(x, str) and build_images.IMAGE_NAME_RE.match(x)] if isinstance(images, list) else []
    try:
        return make_build(body, names, shard_list(appdata.read_archon()), images)
    except ValueError as e:
        raise ApiError(error_text(e))


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
        if len(b.get("images", [])) >= BUILD_IMAGE_MAX:
            raise ApiError(txt("err.build.images", n=str(BUILD_IMAGE_MAX)))
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
    """保存済みの画像(image_name)か、送られてきた画像(data)を解析する。
    保存済みの画像のファイルが無いときはエラーにせず {"missing": True} を返す(画面はその画像を飛ばす)"""
    need_ocr(store)
    names = store.names()
    if not names.mods:
        raise ApiError(txt("err.mods.nodata"), 409)
    if image_name:
        p = build_images.build_image_path(store.d, image_name)
        if p is None:
            return {"missing": True}
        data = p.read_bytes()
    if not data or not build_images.image_ext(data):
        raise ApiError(txt("err.image.format"), 415)
    raw = run_ocr(store, data, cache_dir=store.d / OCR_CACHE_DIR)
    matcher = store.derived("@matcher", (names,), lambda: ocr.build_matcher(names))
    result = ocr.analyze(raw, names, matcher)
    result["has_items"] = bool(names.items)
    return result


def _start_png(data: bytes) -> tuple[threading.Thread | None, dict]:
    """PNG なら展開を別のスレッドで始める(文字認識を待つあいだに並べて行う)。展開できなければ holder は空のまま"""
    holder: dict = {}
    if build_images.image_ext(data) != "png":
        return None, holder

    def decode() -> None:
        try:
            holder["png"] = msscan.read_png(data)
        except ValueError:
            pass  # 読めない PNG(16 ビット・インターレース等)は明るさを判定しない
    worker = threading.Thread(target=decode, daemon=True)
    worker.start()
    return worker, holder


def scan_mods(store: Store, data: bytes) -> dict:
    """ゲームの MOD 一覧画面(の画像)から MOD 名を読み取る。所持チェックを付けるかは画面側で決める。
    lit = 名前の文字が明るい(取得済み)か(PNG でなければ None)・confirmed = 利用者が所持と確定済み(読み取りで飛ばす)"""
    need_ocr(store)
    names = store.names()
    if not names.mods:
        raise ApiError(txt("err.mods.nodata"), 409)
    if not data or not build_images.image_ext(data):
        raise ApiError(txt("err.image.format"), 415)
    worker, decoded = _start_png(data)
    try:
        # 何度も読むので、英語だけ・拡大は控えめにして速さを優先する。結果は保存しない
        raw = run_ocr(store, data, cache_dir=None, langs="en-US", scale=1.5, speed="fast")
    finally:
        if worker:
            worker.join()
    matcher = store.derived("@modmatcher", (names,), lambda: ocr.NameMatcher([("mod", m["en"], m) for m in names.mods]))
    result = ocr.analyze(raw, names, matcher)
    marks = ocr.scan_marks(result["mods"], decoded.get("png"))
    owned, confirmed = userdata.load_owned(store.d), userdata.load_confirmed(store.d)
    conclave = {m["en"].lower() for m in names.mods if m.get("conclave")}
    found, seen = [], set()
    for m in marks:
        k = m["en"].lower()
        if m["kind"] == "mod" and k not in seen:
            seen.add(k)
            found.append({"en": m["en"], "ja": m["ja"], "score": m["score"], "read": m["read"], "lit": m["lit"],
                          "owned": k in owned, "confirmed": k in owned and k in confirmed, "conclave": k in conclave})
    return {"found": found, "lines": len(result["lines"])}


def scan_mastery(store: Store, data: bytes) -> dict:
    """ゲームの「プロフィール → エクストラ」の装備一覧(の画像)からマスター済みを読み取る。印を付けるかは画面側で決める
    (付けるときは POST /api/mastery)。ここは何も書き込まない"""
    need_ocr(store)
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
        raw = run_ocr(store, data, cache_dir=None, langs=OCR_DEFAULT_LANGS)
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
    ("GET", "/api/mastery/sources"): lambda c: mastery_sources(c.store, c.q.get("id", "")),
    ("POST", "/api/mastery/scan"): lambda c: scan_mastery(c.store, c.image()),
    ("GET", "/api/quests"): lambda c: quests_list(c.store),
    ("POST", "/api/quests"): lambda c: set_quests(c.store, c.body()),
    ("GET", "/api/todo"): lambda c: todo_list(c.store),
    ("POST", "/api/todo"): lambda c: change_todo(c.store, c.body()),
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
