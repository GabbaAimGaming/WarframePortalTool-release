"""CLI: 検索(item・area)"""
from __future__ import annotations

import sys

from wfp.cli.common import need_drops
from wfp.cli.table import print_table
from wfp.core.common import MODES_JA, PLANETS_JA, RARITY_JA, SOURCE_CATS, norm, pct, rank
from wfp.core.loader import load_names, load_sources
from wfp.drops.search import all_item_names, find_sources, group_candidates, pick_candidates
from wfp.drops.tables import stage_label
from wfp.store import datadir


def cmd_item(args):
    d = datadir.data_dir(args.data_dir)
    drops, names, sources = need_drops(d), load_names(d), load_sources(d)
    query = " ".join(args.query)
    cands = pick_candidates(query, all_item_names(drops, sources), names, materials_only=not args.all)
    if not cands:
        hint = "" if args.all else " (素材以外も探すには --all)"
        sys.exit(f"「{query}」に一致する項目がありません。{hint}")
    groups = group_candidates(cands, names)
    keys = list(groups.values())
    exact = [k for k in keys if norm(query) in (norm(k), norm(names.ja(k)))]
    if exact:
        keys = exact[:1]
    elif len(keys) > 1 and not args.pick:
        print(f"「{query}」の候補が {len(keys)} 件あります。--pick 番号 で選ぶか、もう少し具体的に入力してください。")
        for i, k in enumerate(keys[:30], 1):
            print(f"  {i:>2}. {names.ja(k)}  ({k})")
        return
    if args.pick:
        if not 1 <= args.pick <= len(keys):
            sys.exit("--pick の番号が範囲外です。")
        keys = [keys[args.pick - 1]]

    base = keys[0]
    rows = find_sources(base, drops, sources, names, events=args.events)
    if args.cat:
        rows = [r for r in rows if r["cat"] in args.cat]
    print(f"■ {names.ja(base)}  ({base})  — {len(rows)} か所\n")
    out = [[r["cat_ja"], r["place"] + (" [イベント]" if r["event"] else ""), r["detail"], r["stage"],
            (f"{r['qty']}個 " if r["qty"] else "") + pct(r["chance"]), r["rarity_ja"]] for r in rows[: args.limit]]
    print_table(["種類", "入手先", "詳細", "ステージ", "確率", "レア度"], out, right_cols=(4,))
    if len(rows) > args.limit:
        print(f"\n(上位 {args.limit} 件を表示。--limit で変更できます)")
    print("\n確率: ミッション/バウンティは報酬1回の抽選で選ばれる割合、敵は1体倒したときに落とす割合、"
          "レリックは開けたときに出る割合です。")


def cmd_area(args):
    d = datadir.data_dir(args.data_dir)
    drops, names = need_drops(d), load_names(d)
    query = " ".join(args.query)
    planet_hits = [p for p in drops.planets if rank(query, [p, PLANETS_JA.get(p, p)]) is not None]
    exact_planet = [p for p in planet_hits if norm(query) in (norm(p), norm(PLANETS_JA.get(p, p)))]
    if exact_planet:
        planet_hits = exact_planet
    node_hits = [] if planet_hits else [(p, n) for p, n in drops.node_order if rank(query, [n]) is not None]
    if not planet_hits and not node_hits:
        sys.exit(f"「{query}」に一致するエリア/ノードがありません。")
    targets = [(p, n) for p, n in drops.node_order if p in planet_hits] if planet_hits else node_hits
    if len(targets) > 1 and not planet_hits and not args.all_nodes:
        exact = [t for t in targets if norm(t[1]) == norm(query)]
        targets = exact or targets

    materials_only = not args.all
    for planet, node in targets:
        rows = [r for r in drops.rows if r[0] == planet and r[1] == node]
        if not rows:
            continue
        mode, event = rows[0][2], rows[0][3]
        if event and not args.events:
            continue
        out = []
        by_rot: dict[str, list] = {}
        for r in rows:
            if materials_only and not names.is_resource(r[5]):
                continue
            by_rot.setdefault(r[4], []).append(r)
        for rot in sorted(by_rot):
            first = True
            for r in sorted(by_rot[rot], key=lambda x: -x[6]):
                out.append([stage_label(rot) if first else "", names.ja(r[5]), pct(r[6]), RARITY_JA.get(r[7], r[7])])
                first = False
        if not out and len(targets) > 1:
            continue  # 素材が出ないノードは一覧から省く
        print(f"\n■ {PLANETS_JA.get(planet, planet)} / {node} — {MODES_JA.get(mode, mode)}" + (" [イベント]" if event else ""))
        if out:
            print_table(["ステージ", "素材", "確率", "レア度"], out, right_cols=(2,))
        else:
            print("  (素材のドロップはありません。--all でMODや設計図も表示)")


def add_item(sub) -> None:
    s = sub.add_parser("item", help="素材名 -> 入手場所・ステージ・確率 (ミッション・敵・バウンティ・レリック等)")
    s.add_argument("query", nargs="+")
    s.add_argument("--all", action="store_true", help="素材以外(MOD・設計図など)も対象にする")
    s.add_argument("--pick", type=int, help="候補が複数のとき番号で選ぶ")
    s.add_argument("--limit", type=int, default=50)
    s.add_argument("--events", action="store_true", help="イベント限定ノードも含める")
    s.add_argument("--cat", action="append", choices=list(SOURCE_CATS), help="入手先の種類で絞り込み (複数回指定可)")
    s.set_defaults(fn=cmd_item)


def add_area(sub) -> None:
    s = sub.add_parser("area", help="エリア(惑星/ノード) -> ステージごとの素材と確率")
    s.add_argument("query", nargs="+")
    s.add_argument("--all", action="store_true", help="素材以外も表示")
    s.add_argument("--all-nodes", action="store_true", help="部分一致のノードをすべて表示")
    s.add_argument("--events", action="store_true")
    s.set_defaults(fn=cmd_area)


# このグループのコマンド: 名前 -> parser に登録する関数(並び順は wfp/cli/main.py の ORDER)
COMMANDS = {"item": add_item, "area": add_area}
