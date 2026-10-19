"""CLI: 個人データ(mods・mastery・arcane・build)"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from wfp.cli.table import pad, print_table
from wfp.core.arcane import arcane_summary, arcane_table, set_arcanes_owned
from wfp.core.build import find_build
from wfp.core.common import ARCANE_CATS, BUILD_TYPES, MASTERY_CATS, MOD_TYPES, SOURCE_CATS, norm, pct, rank
from wfp.core.loader import load_drops, load_names, load_sources
from wfp.core.mastery import mastery_summary, mastery_table
from wfp.core.mods import mod_table
from wfp.drops.search import all_item_names
from wfp.store import build_images, datadir, userdata


def cmd_mods(args):
    d = datadir.data_dir(args.data_dir)
    names = load_names(d)
    if not names.mods:
        sys.exit("MOD の情報がありません。`python wfportal.py update` を実行してください。")
    owned = userdata.load_owned(d)
    args.action = "list"
    if args.query and args.query[0] in ("list", "own", "unown"):
        args.action, args.query = args.query[0], args.query[1:]
    if args.action in ("own", "unown"):
        q = " ".join(args.query)
        hits = [m for m in names.mods if norm(q) in (norm(m["en"]), norm(m["ja"]))] or \
               [m for m in names.mods if rank(q, [m["en"], m["ja"]]) is not None]
        if len(hits) != 1:
            sys.exit(f"「{q}」に一致する MOD が {len(hits)} 件あります。名前を正確に入力してください。"
                     + ("".join(f"\n  {m['ja']} ({m['en']})" for m in hits[:15]) if hits else ""))
        m = hits[0]
        (owned.add if args.action == "own" else owned.discard)(m["en"].lower())
        userdata.save_owned(d, owned)
        print(f"{m['ja']} を{'所持済み' if args.action == 'own' else '未所持'}にしました。")
        return
    drops = load_drops(d) if (d / "missionRewards.json").exists() else None
    rows = mod_table(names, drops, load_sources(d), owned)
    if args.query:
        q = " ".join(args.query)
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
        out.append(["✓" if m["owned"] else "", m["ja"], m["type_ja"], m["polarity_name"], m["rarity_ja"],
                    " ".join(f"{SOURCE_CATS[c]}{n}" for c, n in m["counts"].items()) or "記載なし",
                    f"{b['cat_ja']}: {b['place']} {pct(b['chance'])}" if b else ""])
    print_table(["所持", "MOD", "種別", "極性", "レア度", "入手先(件数)", "最も確率が高い入手先"], out)
    print(f"\n{len(rows)} 件中 {min(len(rows), args.limit)} 件を表示 / 所持 {sum(m['owned'] for m in rows)} 件")
    print("「記載なし」はドロップ表に無いもの(シンジケート・バロ・ナイトウェーブ・クエスト報酬など)です。")


def cmd_mastery(args):
    d = datadir.data_dir(args.data_dir)
    names = load_names(d)
    if not names.mastery:
        sys.exit("マスター一覧のデータがありません。`python wfportal.py update` を実行してください。")
    done = userdata.load_mastered(d)
    rows = mastery_table(names, done)
    action, query = "list", list(args.query)
    if query and query[0] in ("list", "done", "undo"):
        action, query = query[0], query[1:]
    q = " ".join(query)
    if args.cat:
        rows = [r for r in rows if r["cat"] == args.cat]
    if action in ("done", "undo"):
        hits = [r for r in rows if norm(q) in (norm(r["en"]), norm(r["ja"]), norm(r["label"]))] or \
               [r for r in rows if rank(q, [r["en"], r["ja"], r["label"]]) is not None]
        if not hits:
            sys.exit(f"「{q}」に一致するものがありません。")
        if len(hits) > 1 and len({norm(r["en"]) for r in hits}) > 1:
            sys.exit(f"「{q}」に一致するものが {len(hits)} 件あります。名前を正確に入力するか --cat で絞り込んでください。"
                     + "".join(f"\n  {r['label']} [{r['cat_ja']}]" for r in hits[:15]))
        for r in hits:  # Kitgun はプライマリ版・セカンダリ版の両方 (片方だけなら --cat と名前で指定)
            (done.add if action == "done" else done.discard)(r["id"])
        userdata.save_mastered(d, done)
        print("、".join(r["label"] for r in hits) + f" を{'マスター済み' if action == 'done' else '未マスター'}にしました。")
        return
    if q:
        rows = [r for r in rows if rank(q, [r["en"], r["ja"], r["label"]]) is not None]
    if args.todo:
        rows = [r for r in rows if not r["done"]]
    if not rows:
        sys.exit("条件に合うものがありません。")
    print_table(["済", "名前", "カテゴリー", "最大ランク", "マスタリー経験値"],
                [["✓" if r["done"] else "", r["label"], r["cat_ja"], str(r["rank"]), f"{r['xp']:,}"] for r in rows[: args.limit]],
                right_cols=(3, 4))
    summ = mastery_summary(mastery_table(names, done))
    print(f"\n{len(rows)} 件中 {min(len(rows), args.limit)} 件を表示")
    for c, label in MASTERY_CATS.items():
        v = summ[c]
        print(f"  {pad(label, 18)} {v['done']:>4} / {v['total']:<4}")
    a = summ["all"]
    print(f"  {pad('全体', 18)} {a['done']:>4} / {a['total']:<4}  マスタリー経験値 {a['xp_done']:,} / {a['xp']:,}")


def cmd_arcane(args):
    d = datadir.data_dir(args.data_dir)
    names = load_names(d)
    if not names.arcane_list:
        sys.exit("アルケインのデータがありません。`python wfportal.py update` を実行してください"
                 "(この機能を追加する前に取得したデータには含まれていません)。")
    owned = userdata.load_arcanes_owned(d)
    drop_items = all_item_names(load_drops(d), load_sources(d)) if (d / "missionRewards.json").exists() else []
    rows = arcane_table(names, owned, drop_items)
    action, query = "list", list(args.query)
    if query and query[0] in ("list", "own", "unown"):
        action, query = query[0], query[1:]
    q = " ".join(query)
    if args.cat:
        rows = [r for r in rows if r["cat"] == args.cat]
    if action in ("own", "unown"):
        hits = [r for r in rows if norm(q) in (norm(r["en"]), norm(r["ja"]))] or \
               [r for r in rows if rank(q, [r["en"], r["ja"]]) is not None]
        if not hits:
            sys.exit(f"「{q}」に一致するアルケインがありません。")
        if len(hits) > 1:
            sys.exit(f"「{q}」に一致するアルケインが {len(hits)} 件あります。名前を正確に入力してください。"
                     + "".join(f"\n  {r['ja']} [{r['cat_ja']}]" for r in hits[:15]))
        try:
            m, = set_arcanes_owned(names, owned, [hits[0]["en"]], action == "own", args.rank if action == "own" else None,
                                   drop_items)
        except ValueError as e:
            sys.exit(str(e))
        userdata.save_arcanes_owned(d, owned)
        print(f"{m['ja']} を" + (f"所持(ランク {owned[m['en'].lower()]})にしました。" if action == "own" else "未所持にしました。"))
        return
    if args.rank is not None:
        sys.exit("--rank は own と一緒に使います(例: python wfportal.py arcane own \"Arcane Energize\" --rank 5)。")
    if q:
        rows = [r for r in rows if rank(q, [r["en"], r["ja"]]) is not None]
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
    d = datadir.data_dir(args.data_dir)
    builds = userdata.load_builds(d)
    act = args.action
    if act == "list":
        rows = [b for b in builds if not args.type or b["type"] == args.type]
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
    elif act == "show":
        b = find_build(builds, " ".join(args.query))
        if not b:
            sys.exit("該当するビルドが見つからない、または複数あります。")
        print(f"■ {b['name']}  [{BUILD_TYPES.get(b['type'], b['type'])}]  対象: {b.get('target', '-')}  フォーマ: {b.get('forma', 0)}")
        for i, m in enumerate(b.get("mods", []), 1):
            print(f"  {i:>2}. {m}")
        if b.get("arcanes"):
            print("アルケイン: " + ", ".join(b["arcanes"]))
        if b.get("note"):
            print(f"\nメモ: {b['note']}")
        if b.get("tags"):
            print("タグ: " + ", ".join(b["tags"]))
        for n in b.get("images", []):
            print(f"画像: {d / build_images.IMAGE_DIR / n}")
    elif act == "add":
        name = " ".join(args.query)
        if not name:
            sys.exit("ビルド名を指定してください。")
        old = find_build(builds, name)
        entry = {"name": name, "type": args.type or "frame", "target": args.target or "",
                 "forma": args.forma or 0, "mods": [m.strip() for m in (args.mods or "").split(",") if m.strip()],
                 "arcanes": [a.strip() for a in (args.arcanes or "").split(",") if a.strip()],
                 "tags": [t.strip() for t in (args.tags or "").split(",") if t.strip()], "note": args.note or "",
                 "images": []}
        same = old is not None and norm(old["name"]) == norm(name)
        if same and not args.update:
            sys.exit("同名のビルドがあります。上書きするには --update を付けてください。")
        if same:
            entry["images"] = list(old.get("images", []))  # 既存の画像は残し、--image の分を追加する
        for path in args.image or []:
            try:
                entry["images"].append(build_images.save_build_image(d, Path(path).expanduser().read_bytes()))
            except (OSError, ValueError) as e:
                sys.exit(f"画像を追加できませんでした({path}): {e}")
        if same:
            builds[builds.index(old)] = entry
            print("更新しました。")
        else:
            builds.append(entry)
            print("追加しました。")
        userdata.save_builds(d, builds)
    elif act == "rm":
        b = find_build(builds, " ".join(args.query))
        if not b:
            sys.exit("該当するビルドが見つからない、または複数あります。")
        builds.remove(b)
        userdata.save_builds(d, builds)
        build_images.delete_build_images(d, b.get("images", []))
        print(f"削除しました: {b['name']}")
    elif act == "export":
        print(json.dumps(builds, ensure_ascii=False, indent=2))
    elif act == "analyze":
        import wfportal_ocr  # Windows の文字認識を使う画像解析
        wfportal_ocr.main_analyze(args.query, d, raw=args.raw, save_ocr=args.save_ocr, ocr_json=args.ocr_json)


def add_build(sub) -> None:
    s = sub.add_parser("build", help="ビルド管理")
    s.add_argument("action", choices=["list", "show", "add", "rm", "export", "analyze"])
    s.add_argument("query", nargs="*", help="ビルド名 / 検索語 / analyze のときは画像ファイル")
    s.add_argument("--type", choices=list(BUILD_TYPES))
    s.add_argument("--target", help="フレーム名・武器名")
    s.add_argument("--forma", type=int)
    s.add_argument("--mods", help="カンマ区切り")
    s.add_argument("--arcanes", help="アルケイン (カンマ区切り)")
    s.add_argument("--tags", help="カンマ区切り")
    s.add_argument("--note")
    s.add_argument("--update", action="store_true", help="同名ビルドを上書き")
    s.add_argument("--image", action="append", metavar="画像ファイル", help="画像を添付 (複数回指定可)")
    s.add_argument("--raw", action="store_true", help="analyze: 読み取った文字をそのまま表示")
    s.add_argument("--save-ocr", metavar="JSON", help="analyze: 文字認識の結果を保存 (不具合の報告用)")
    s.add_argument("--ocr-json", metavar="JSON", help="analyze: 保存した文字認識の結果から解析し直す")
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
COMMANDS = {"build": add_build, "mods": add_mods, "mastery": add_mastery, "arcane": add_arcane}
