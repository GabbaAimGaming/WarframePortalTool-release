"""CLI: 個人データ(mods・mastery・quest・arcane・build)"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from wfp.cli.common import find_hits, match_rows, split_action
from wfp.cli.table import pad, print_table
from wfp.core.arcane import arcane_summary, arcane_table, set_arcanes_owned
from wfp.core.build import find_build, make_build
from wfp.core.common import pct, rank
from wfp.core.i18n import render_ja, txt
from wfp.core.text import norm
from wfp.core.const import (
    ARCANE_CATS, BUILD_IMAGE_DIR, BUILD_IMAGE_MAX, BUILD_TYPES, DROPS_FILE, MASTERY_CATS, MOD_TYPES, OCR_ENGINE_PREFS,
    QUEST_CATS, QUEST_STATES, RARITY_JA, SOURCE_CATS,
)
from wfp.core.archon import find_effect, parse_shard_args, shard_list, shard_text
from wfp.core.helminth import parse_helminth_arg, subsume_frame, subsume_list
from wfp.core.loader import load_drops, load_names, load_sources, load_vault
from wfp.core.mastery import mastery_label, mastery_summary, mastery_table, vaulted_owners
from wfp.core.mods import mod_table
from wfp.core.quests import item_name, quest_items, quest_summary, quest_table, set_quests_done
from wfp.drops.search import all_item_names
from wfp.store import appdata, build_images, datadir, gamedata, userdata


def cmd_mods(args):
    d = datadir.data_dir(args.data_dir)
    names = load_names(d)
    if not names.mods:
        sys.exit("MOD の情報がありません。`python wfportal.py update` を実行してください。")
    owned = userdata.load_owned(d)
    action, query = split_action(args.query, ("own", "unown"))
    if action in ("own", "unown"):
        q = " ".join(query)
        hits = find_hits(names.mods, q, lambda m: [m["en"], m["ja"]])
        if len(hits) != 1:
            sys.exit(f"「{q}」に一致する MOD が {len(hits)} 件あります。名前を正確に入力してください。"
                     + ("".join(f"\n  {m['ja']} ({m['en']})" for m in hits[:15]) if hits else ""))
        m = hits[0]
        with userdata.editing(d, "mods_owned") as owned:
            (owned.add if action == "own" else owned.discard)(m["en"].lower())
        print(f"{m['ja']} を{'所持済み' if action == 'own' else '未所持'}にしました。")
        return
    drops = load_drops(d) if (d / DROPS_FILE).exists() else None
    rows = mod_table(names, drops, load_sources(d), owned)
    if query:
        q = " ".join(query)
        scored = [(rank(q, [m["en"], m["ja"], m.get("compat", "")]), m) for m in rows]
        rows = [m for r, m in sorted((x for x in scored if x[0] is not None), key=lambda x: (x[0], x[1]["en"].lower()))]
    if args.type:
        rows = [m for m in rows if m["type"] == args.type.upper()]
    if args.unowned:
        rows = [m for m in rows if not m["owned"]]
    if not rows:
        sys.exit("条件に合う MOD がありません。")
    out = []
    for m in rows[: args.limit]:
        b = m["best"]
        out.append(["✓" if m["owned"] else "", m["ja"], MOD_TYPES.get(m["type"], m["type"]), m["polarity_name"],
                    RARITY_JA.get(m["rarity"], m["rarity"]),
                    " ".join(f"{SOURCE_CATS[c]}{n}" for c, n in m["counts"].items()) or "記載なし",
                    f"{SOURCE_CATS[b['cat']]}: {render_ja(b['place'])} {pct(b['chance'])}" if b else ""])
    print_table(["所持", "MOD", "種別", "極性", "レア度", "入手先(件数)", "最も確率が高い入手先"], out)
    print(f"\n{len(rows)} 件中 {min(len(rows), args.limit)} 件を表示 / 所持 {sum(m['owned'] for m in rows)} 件")
    print("「記載なし」はドロップ表に無いもの(シンジケート・バロ・ナイトウェーブ・クエスト報酬など)です。")


def cmd_mastery(args):
    d = datadir.data_dir(args.data_dir)
    names = load_names(d)
    if not names.mastery:
        sys.exit("マスター一覧のデータがありません。`python wfportal.py update` を実行してください。")
    done = userdata.load_mastered(d)
    # 表示名(Kitgun の区別つき)とカテゴリー名は CLI で付ける(一覧の中身はキーのまま)
    rows = [{**r, "label": mastery_label(r), "cat_ja": MASTERY_CATS.get(r["cat"], r["cat"])} for r in mastery_table(names, done)]
    action, query = split_action(args.query, ("done", "undo"))
    q = " ".join(query)
    if args.cat:
        rows = [r for r in rows if r["cat"] == args.cat]
    keys = lambda r: [r["en"], r["ja"], r["label"]]
    if action in ("done", "undo"):
        hits = find_hits(rows, q, keys)
        if not hits:
            sys.exit(f"「{q}」に一致するものがありません。")
        if len(hits) > 1 and len({norm(r["en"]) for r in hits}) > 1:
            sys.exit(f"「{q}」に一致するものが {len(hits)} 件あります。名前を正確に入力するか --cat で絞り込んでください。"
                     + "".join(f"\n  {r['label']} [{r['cat_ja']}]" for r in hits[:15]))
        with userdata.editing(d, "mastered") as done:
            for r in hits:  # Kitgun はプライマリ版・セカンダリ版の両方 (片方だけなら --cat と名前で指定)
                (done.add if action == "done" else done.discard)(r["id"])
        print("、".join(r["label"] for r in hits) + f" を{'マスター済み' if action == 'done' else '未マスター'}にしました。")
        return
    if q:
        rows = match_rows(rows, q, keys)
    if args.todo:
        rows = [r for r in rows if not r["done"]]
    if not rows:
        sys.exit("条件に合うものがありません。")
    # いま作れない本体(入手不可のパーツがある)は名前の後ろに [Vault]。ドロップ表が無い・壊れているときは判定しない
    # (マスター一覧は names.json だけで出せるもの。ドロップ表の傷みで止めない)。Prime Resurgence の期間中のレリックは外す
    try:
        drops = load_drops(d) if (d / DROPS_FILE).exists() else None
        sources = load_sources(d)
        vaulted = vaulted_owners(names, load_vault(d, drops, sources), sources.part_owner if sources else None)
    except gamedata.DataBroken:
        vaulted = set()
    print_table(["済", "名前", "カテゴリー", "最大ランク", "マスタリー経験値"],
                [["✓" if r["done"] else "", r["label"] + (" [Vault]" if r["en"].lower() in vaulted else ""), r["cat_ja"], str(r["rank"]),
                  f"{r['xp']:,}"] for r in rows[: args.limit]],
                right_cols=(3, 4))
    summ = mastery_summary(mastery_table(names, done))
    print(f"\n{len(rows)} 件中 {min(len(rows), args.limit)} 件を表示")
    for c, label in MASTERY_CATS.items():
        v = summ[c]
        print(f"  {pad(label, 18)} {v['done']:>4} / {v['total']:<4}")
    a = summ["all"]
    print(f"  {pad('全体', 18)} {a['done']:>4} / {a['total']:<4}  マスタリー経験値 {a['xp_done']:,} / {a['xp']:,}")


def cmd_quest(args):
    d = datadir.data_dir(args.data_dir)
    names = load_names(d)
    done = userdata.load_quests_done(d)
    rows = quest_table(names, done)
    if not rows:
        sys.exit("クエストのデータがありません。")
    label = {r["id"]: render_ja(item_name(r)) for r in rows}
    action, query = split_action(args.query, ("done", "undo"))
    q = " ".join(query)
    if args.cat:
        rows = [r for r in rows if r["cat"] == args.cat]
    keys = lambda r: [r.get("en") or r.get("to", ""), r.get("ja", ""), label[r["id"]]]
    if action in ("done", "undo"):
        hits = find_hits(rows, q, keys)
        if len(hits) != 1:
            sys.exit(f"「{q}」に一致するものがありません。" if not hits else
                     f"「{q}」に一致するものが {len(hits)} 件あります。名前を正確に入力してください。"
                     + "".join(f"\n  {label[r['id']]} [{QUEST_CATS[r['cat']]}]" for r in hits[:15]))
        hit = hits[0]
        ids = (hit["route"] if action == "done" and args.route else []) + [hit["id"]]
        with userdata.editing(d, "quests_done") as done:  # 前提の検査と書き込みの間に、ほかの変更が割り込まない
            try:
                new = set_quests_done(quest_items(names), done, ids, action == "done")
            except ValueError as e:
                route = "" if action == "undo" or not hit["route"] else \
                    "\n先に必要な順: " + " → ".join(label[i] for i in hit["route"]) + "\n(--route を付けると、これらもまとめて完了にします)"
                sys.exit(str(e) + route)
            done.clear()
            done.update(new)
        print("、".join(label[i] for i in ids) + f" を{'完了' if action == 'done' else '未完了'}にしました。")
        return
    if q:
        rows = match_rows(rows, q, keys)
    if args.state == "todo":
        rows = [r for r in rows if not r["done"]]
    elif args.state:
        rows = [r for r in rows if r["state"] == args.state]
    if not rows:
        sys.exit("条件に合うものがありません。")
    print_table(["済", "状態", "名前", "種類", "未完了の前提"],
                [["✓" if r["done"] else "", QUEST_STATES[r["state"]], label[r["id"]], QUEST_CATS[r["cat"]],
                  "、".join(label[i] for i in r["missing"])] for r in rows[: args.limit]])
    summ = quest_summary(quest_table(names, done))
    print(f"\n{len(rows)} 件中 {min(len(rows), args.limit)} 件を表示")
    for c, name in list(QUEST_CATS.items()) + [("all", "全体")]:
        v = summ[c]
        if v["total"]:
            print(f"  {pad(name, 18)} {v['done']:>4} / {v['total']:<4}  受けられる {v['ready']}")


def cmd_arcane(args):
    d = datadir.data_dir(args.data_dir)
    names = load_names(d)
    if not names.arcane_list:
        sys.exit("アルケインのデータがありません。`python wfportal.py update` を実行してください"
                 "(この機能を追加する前に取得したデータには含まれていません)。")
    owned = userdata.load_arcanes_owned(d)
    drop_items = all_item_names(load_drops(d), load_sources(d)) if (d / DROPS_FILE).exists() else []
    rows = [{**r, "cat_ja": ARCANE_CATS.get(r["cat"], r["cat"]), "rarity_ja": RARITY_JA.get(r["rarity"], r["rarity"])}
            for r in arcane_table(names, owned, drop_items)]
    action, query = split_action(args.query, ("own", "unown"))
    q = " ".join(query)
    if args.cat:
        rows = [r for r in rows if r["cat"] == args.cat]
    keys = lambda r: [r["en"], r["ja"]]
    if action in ("own", "unown"):
        hits = find_hits(rows, q, keys)
        if not hits:
            sys.exit(f"「{q}」に一致するアルケインがありません。")
        if len(hits) > 1:
            sys.exit(f"「{q}」に一致するアルケインが {len(hits)} 件あります。名前を正確に入力してください。"
                     + "".join(f"\n  {r['ja']} [{r['cat_ja']}]" for r in hits[:15]))
        with userdata.editing(d, "arcanes_owned") as owned:
            try:
                m, = set_arcanes_owned(names, owned, [hits[0]["en"]], action == "own", args.rank if action == "own" else None,
                                       drop_items)
            except ValueError as e:
                sys.exit(str(e))
        print(f"{m['ja']} を" + (f"所持(ランク {owned[m['en'].lower()]})にしました。" if action == "own" else "未所持にしました。"))
        return
    if args.rank is not None:
        sys.exit("--rank は own と一緒に使います(例: python wfportal.py arcane own \"Arcane Energize\" --rank 5)。")
    if q:
        rows = match_rows(rows, q, keys)
    if args.unowned:
        rows = [r for r in rows if not r["owned"]]
    if not rows:
        sys.exit("条件に合うアルケインがありません。")
    print_table(["所持", "名前", "種類", "レア度", "ランク"],
                [["✓" if r["owned"] else "", r["ja"], r["cat_ja"], r["rarity_ja"] or "-", f"{r['rank'] if r['owned'] else '-'} / {r['max_rank']}"] for r in rows[: args.limit]],
                right_cols=(4,))
    summ = arcane_summary(arcane_table(names, owned, drop_items))
    print(f"\n{len(rows)} 件中 {min(len(rows), args.limit)} 件を表示")
    for c, label in list(ARCANE_CATS.items()) + [("all", "全体")]:
        v = summ[c]
        if v["total"]:
            print(f"  {pad(label, 18)} {v['owned']:>4} / {v['total']:<4} (ランク最大 {v['maxed']})")


def cmd_build(args):
    """CLI `build`: 動作(list / show / add / rm / export / analyze)ごとの関数を表 _BUILD_ACTIONS から引いて呼ぶ"""
    _BUILD_ACTIONS[args.action](datadir.data_dir(args.data_dir), args)


def _build_list(d, args) -> None:
    """build list: 一覧(--type で種別・検索語で名前・対象・タグを絞る)"""
    rows = [b for b in userdata.load_builds(d) if not args.type or b["type"] == args.type]
    if args.query:
        q = " ".join(args.query)
        rows = [b for b in rows if rank(q, [b["name"], b.get("target", ""), *b.get("tags", [])]) is not None]
    if not rows:
        print("ビルドがありません。`build add` で登録できます。")
        return
    print_table(["名前", "種別", "対象", "フォーマ", "MOD数", "画像", "タグ"],
                [[b["name"], BUILD_TYPES.get(b["type"], b["type"]), b.get("target", ""), str(b.get("forma", 0)),
                  str(len(b.get("mods", []))), str(len(b.get("images", []))), ",".join(b.get("tags", []))] for b in rows],
                right_cols=(3, 4, 5))


def _build_show(d, args) -> None:
    """build show: 1件の中身(MOD・アルケインは和名・Helminth・アルコンの欠片・メモ・タグ・画像の場所)"""
    b = find_build(userdata.load_builds(d), " ".join(args.query))
    if not b:
        sys.exit("該当するビルドが見つからない、または複数あります。")
    print(f"■ {b['name']}  [{BUILD_TYPES.get(b['type'], b['type'])}]  対象: {b.get('target', '-')}  フォーマ: {b.get('forma', 0)}")
    for i, m in enumerate(b.get("mods", []), 1):
        print(f"  {i:>2}. {m}")
    if b.get("arcanes"):
        names = load_names(d)  # 保存は英名。CLI は日本語なので和名で出す(和名が無ければ英名)
        print("アルケイン: " + ", ".join(names.ja(a) for a in b["arcanes"]))
    if b.get("helminth"):
        helm = b["helminth"]
        frame = subsume_frame(subsume_list(appdata.read_helminth()), helm["ability"])
        print(f"Helminth: {helm['slot']}番 → {helm['ability']}" + (f"({frame})" if frame else ""))
    if b.get("shards"):
        _print_shards(b["shards"])
    if b.get("note"):
        print(f"\nメモ: {b['note']}")
    if b.get("tags"):
        print("タグ: " + ", ".join(b["tags"]))
    for n in b.get("images", []):
        print(f"画像: {d / BUILD_IMAGE_DIR / n}")


def _print_shards(shards: list) -> None:
    """アルコンの欠片の5枠を出す(空の枠は「-」・一覧に無い色と効果はそのまま)"""
    print("アルコンの欠片:")
    data = shard_list(appdata.read_archon())
    for i, sh in enumerate(shards, 1):
        hit = find_effect(data, sh["color"], sh["effect"]) if sh else None
        if not sh:
            print(f"  {i}. -")
        elif hit:
            head = ("Tauforged " if sh["tauforged"] else "") + hit[0]["ja"]
            print(f"  {i}. {head}: {shard_text(hit[1], 'ja', sh['tauforged'], data['tauforged_rate'])}")
        else:
            print(f"  {i}. {sh['color']}: {sh['effect']}(一覧にありません)")


def _build_remove(d, args) -> None:
    """build rm: 1件を消す(画像のファイルは書き込みが確定してから消す)"""
    with userdata.editing(d, "builds") as builds:
        b = find_build(builds, " ".join(args.query))
        if not b:
            sys.exit("該当するビルドが見つからない、または複数あります。")
        builds.remove(b)
    build_images.delete_build_images(d, b.get("images", []))
    print(f"削除しました: {b['name']}")


def _build_export(d, args) -> None:
    """build export: 全部を JSON で出す"""
    print(json.dumps(userdata.load_builds(d), ensure_ascii=False, indent=2))


def _build_analyze(d, args) -> None:
    """build analyze: 画像を文字認識してビルドの中身を読む(wfportal_ocr。エンジンは wfp/ocr。--engine で選ぶ)"""
    import wfportal_ocr  # 文字認識を使うときだけ読み込む
    from wfp.ocr import engine
    prefs = userdata.load_ocr_prefs(d)  # 画面と同じ設定(--engine があればそちら)
    engine.configure(d, prefs["tier"])
    wfportal_ocr.main_analyze(args.query, d, raw=args.raw, save_ocr=args.save_ocr, ocr_json=args.ocr_json,
                              engine=args.engine or prefs["engine"])


def _build_raw(args, name: str, old_type: str | None) -> dict:
    """build add の引数を make_build の入力にする(API の本文と同じ形)。--update で --type を省いたら元の種別を引き継ぐ"""
    return {"name": name, "type": args.type or old_type, "target": args.target, "forma": args.forma, "mods": args.mods,
            "arcanes": args.arcanes, "tags": args.tags, "note": args.note,
            "helminth": parse_helminth_arg(args.helminth) if args.helminth else None, "shards": parse_shard_args(args.shard)}


def _read_images(paths: list[str]) -> list[bytes]:
    """--image のファイルを全部読んで検査する(1つでもだめなら何も保存せずに終わる)"""
    out = []
    for path in paths:
        try:
            data = Path(path).expanduser().read_bytes()
            build_images.check_build_image(data)
        except (OSError, ValueError) as e:
            sys.exit(f"画像を追加できませんでした({path}): {e}")
        out.append(data)
    return out


def _save_images(d, datas: list[bytes]) -> list[str]:
    """画像を保存して名前を返す。途中で失敗したら、それまでに保存した分を消して終わる"""
    saved: list[str] = []
    for data in datas:
        try:
            saved.append(build_images.save_build_image(d, data))
        except (OSError, ValueError) as e:
            build_images.delete_build_images(d, saved)
            sys.exit(f"画像を保存できませんでした: {e}")
    return saved


def _build_add(d, args) -> None:
    """build add: 新規か、--update で同名を上書き(既存の画像は残し --image の分を足す)。値のそろえ方は core/build の make_build(API と同じ)"""
    name = " ".join(args.query).strip()
    if not name:
        sys.exit(render_ja(txt("err.build.name")))
    datas = _read_images(args.image or [])  # ファイルの読み込みと検査は書き込みの前に済ませる
    with userdata.editing(d, "builds") as builds:  # 同名の検査と書き込みの間に、ほかの変更が割り込まない
        old = find_build(builds, name)
        same = old is not None and norm(old["name"]) == norm(name)
        if same and not args.update:
            sys.exit("同名のビルドがあります。上書きするには --update を付けてください。")
        kept = list(old.get("images", [])) if same else []
        if len(kept) + len(datas) > BUILD_IMAGE_MAX:
            sys.exit(render_ja(txt("err.build.images", n=str(BUILD_IMAGE_MAX))))
        try:
            entry = make_build(_build_raw(args, name, old["type"] if same else None), load_names(d),
                               shard_list(appdata.read_archon()), kept)
        except ValueError as e:
            sys.exit(str(e))
        entry["images"] += _save_images(d, datas)
        if same:
            builds[builds.index(old)] = entry
        else:
            builds.append(entry)
    print("更新しました。" if same else "追加しました。")  # 書き込みが確定してから出す


# build の動作 -> 関数(引数の選択肢もこの表から作る)
_BUILD_ACTIONS = {"list": _build_list, "show": _build_show, "add": _build_add, "rm": _build_remove,
                  "export": _build_export, "analyze": _build_analyze}


def add_build(sub) -> None:
    s = sub.add_parser("build", help="ビルド管理")
    s.add_argument("action", choices=list(_BUILD_ACTIONS))
    s.add_argument("query", nargs="*", help="ビルド名 / 検索語 / analyze のときは画像ファイル")
    s.add_argument("--type", choices=list(BUILD_TYPES))
    s.add_argument("--target", help="フレーム名・武器名")
    s.add_argument("--forma", type=int)
    s.add_argument("--mods", help="カンマ区切り")
    s.add_argument("--arcanes", help="アルケイン (カンマ区切り)")
    s.add_argument("--tags", help="カンマ区切り")
    s.add_argument("--note")
    s.add_argument("--helminth", metavar="番号:アビリティ", help="Helminth で置き換えるアビリティ (例: 3:Roar。Warframe のみ)")
    s.add_argument("--shard", action="append", metavar="枠:色:効果[:t]",
                   help="アルコンの欠片 (例: 1:red:MeleeCritDamage。Tauforged は末尾に :t。複数回指定可。Warframe のみ)")
    s.add_argument("--update", action="store_true", help="同名ビルドを上書き")
    s.add_argument("--image", action="append", metavar="画像ファイル", help="画像を添付 (複数回指定可)")
    s.add_argument("--raw", action="store_true", help="analyze: 読み取った文字をそのまま表示")
    s.add_argument("--save-ocr", metavar="JSON", help="analyze: 文字認識の結果を保存 (不具合の報告用)")
    s.add_argument("--ocr-json", metavar="JSON", help="analyze: 保存した文字認識の結果から解析し直す")
    s.add_argument("--engine", choices=OCR_ENGINE_PREFS,
                   help="analyze: 文字認識のエンジン(auto = 高精度が入っていればそれ・無ければ Windows / winrt / ppocr。既定は画面の設定)")
    s.set_defaults(fn=cmd_build)


def add_mods(sub) -> None:
    s = sub.add_parser("mods", help="MOD 入手一覧 (入手先と所持チェック)")
    s.add_argument("query", nargs="*", metavar="[own|unown] 名前",
                   help="MOD 名で絞り込み。先頭に own / unown を付けると所持チェックを付ける/外す")
    s.add_argument("--type", choices=[k.lower() for k in MOD_TYPES], help="種別で絞り込み")
    s.add_argument("--unowned", action="store_true", help="未所持のみ")
    s.add_argument("--limit", type=int, default=60)
    s.set_defaults(fn=cmd_mods)


def add_mastery(sub) -> None:
    s = sub.add_parser("mastery", help="マスター一覧 (Warframe・武器・コンパニオンなどのマスター済みチェック)")
    s.add_argument("query", nargs="*", metavar="[done|undo] 名前",
                   help="名前で絞り込み。先頭に done / undo を付けるとマスター済みにする / 外す")
    s.add_argument("--cat", choices=list(MASTERY_CATS), help="カテゴリーで絞り込み")
    s.add_argument("--todo", action="store_true", help="未マスターのみ")
    s.add_argument("--limit", type=int, default=60)
    s.set_defaults(fn=cmd_mastery)


def add_quest(sub) -> None:
    s = sub.add_parser("quest", help="クエスト一覧 (クエスト・ジャンクションの完了チェックと前提条件)")
    s.add_argument("query", nargs="*", metavar="[done|undo] 名前",
                   help="名前で絞り込み。先頭に done / undo を付けると完了にする / 外す(前提が未完了なら完了にできない)")
    s.add_argument("--cat", choices=list(QUEST_CATS), help="種類で絞り込み")
    s.add_argument("--state", choices=list(QUEST_STATES) + ["todo"], help="状態で絞り込み (todo は未完了すべて)")
    s.add_argument("--route", action="store_true", help="done のとき、未完了の前提もまとめて完了にする")
    s.add_argument("--limit", type=int, default=80)
    s.set_defaults(fn=cmd_quest)


def add_arcane(sub) -> None:
    s = sub.add_parser("arcane", help="アルケイン所持一覧 (所持チェックとランク)")
    s.add_argument("query", nargs="*", metavar="[own|unown] 名前",
                   help="名前で絞り込み。先頭に own / unown を付けると所持にする / 外す")
    s.add_argument("--cat", choices=list(ARCANE_CATS), help="種類で絞り込み")
    s.add_argument("--unowned", action="store_true", help="未所持のみ")
    s.add_argument("--rank", type=int, help="own で設定するランク (省略時: 所持済みならそのまま、未所持なら 0)")
    s.add_argument("--limit", type=int, default=60)
    s.set_defaults(fn=cmd_arcane)


# このグループのコマンド: 名前 -> parser に登録する関数(並び順は wfp/cli/main.py の ORDER)
COMMANDS = {"build": add_build, "mods": add_mods, "mastery": add_mastery, "quest": add_quest, "arcane": add_arcane}
