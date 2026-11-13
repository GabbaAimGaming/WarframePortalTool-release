"""CLI: 検索(item・area・enemy・recipe)"""
from __future__ import annotations

import sys

from wfp.cli.common import need_drops
from wfp.cli.table import print_table
from wfp.core.common import pct, rank
from wfp.core.i18n import render_ja
from wfp.core.text import norm
from wfp.core.const import (
    AREA_KIND_DEFAULT, AREA_KINDS, ENEMY_KIND_DEFAULT, ITEM_KIND_DEFAULT, MASTERY_CATS, MODES_JA, PLANETS_JA, RARITY_JA,
    RECIPE_SOURCE_LIMIT, SOURCE_CATS,
)
from wfp.core.loader import DropsMissing, load_drops, load_names, load_recipes, load_sources
from wfp.core.recipes import pick_tops, sort_sources
from wfp.drops.search import all_item_names, area_stages, enemy_drops, find_sources, group_candidates, pick_candidates, pick_enemies
from wfp.drops.tables import stage_label
from wfp.store import datadir


def cmd_item(args):
    d = datadir.data_dir(args.data_dir)
    drops, names, sources = need_drops(d), load_names(d), load_sources(d)
    query = " ".join(args.query)
    kinds = set(AREA_KINDS) if args.all else set(args.kind or ITEM_KIND_DEFAULT)
    owners = sources.part_owner if sources else {}
    cands = pick_candidates(query, all_item_names(drops, sources), names, keep=lambda n: names.item_kind(n, owners) in kinds)
    if not cands:
        hint = "" if args.all else " (ほかの種類も探すには --kind か --all)"
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
    out = [[SOURCE_CATS.get(r["cat"], r["cat"]), render_ja(r["place"]) + (" [イベント]" if r["event"] else ""), render_ja(r["detail"]),
            render_ja(r["stage"]), (f"{r['qty']}個 " if r["qty"] else "") + pct(r["chance"]), RARITY_JA.get(r["rarity"], r["rarity"])]
           for r in rows[: args.limit]]
    print_table(["種類", "入手先", "詳細", "ステージ", "確率", "レア度"], out, right_cols=(4,))
    if len(rows) > args.limit:
        print(f"\n(上位 {args.limit} 件を表示。--limit で変更できます)")
    print("\n確率: ミッション/バウンティは報酬1回の抽選で選ばれる割合、敵は1体倒したときに落とす割合、"
          "レリックは開けたときに出る割合です。クラン研究・Simaris 交換・クエスト報酬は確率が無いので「—」です。")


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

    kinds = set(AREA_KINDS) if args.all else set(args.kind or AREA_KIND_DEFAULT)
    for planet, node in targets:
        rows = [r for r in drops.rows if r[0] == planet and r[1] == node]
        if not rows:
            continue
        mode, event = rows[0][2], rows[0][3]
        if event and not args.events:
            continue
        out = []
        for rot, lst in area_stages(rows, names, kinds).items():
            for i, (r, item_kind) in enumerate(lst):
                out.append([render_ja(stage_label(rot)) if i == 0 else "", names.ja(r[5]), AREA_KINDS[item_kind],
                            pct(r[6]), RARITY_JA.get(r[7], r[7])])
        if not out and len(targets) > 1:
            continue  # 選んだ種類が出ないノードは一覧から省く
        print(f"\n■ {PLANETS_JA.get(planet, planet)} / {node} — {MODES_JA.get(mode, mode)}" + (" [イベント]" if event else ""))
        if out:
            print_table(["ステージ", "アイテム", "種類", "確率", "レア度"], out, right_cols=(3,))
        else:
            print("  (選んだ種類のドロップはありません。--kind で種類を足すか、--all ですべての種類を表示)")


def cmd_enemy(args):
    d = datadir.data_dir(args.data_dir)
    need_drops(d)
    names, sources = load_names(d), load_sources(d)
    query = " ".join(args.query)
    cands = pick_enemies(query, sources.enemies if sources else [])
    if not cands:
        sys.exit(f"「{query}」に一致する敵がありません(敵の名前は英語です)。")
    exact = [n for n in cands if norm(n) == norm(query)]
    if exact:
        cands = exact[:1]
    elif len(cands) > 1 and not args.pick:
        print(f"「{query}」の候補が {len(cands)} 件あります。--pick 番号 で選ぶか、もう少し具体的に入力してください。")
        for i, n in enumerate(cands[:30], 1):
            print(f"  {i:>2}. {n}")
        return
    if args.pick:
        if not 1 <= args.pick <= len(cands):
            sys.exit("--pick の番号が範囲外です。")
        cands = [cands[args.pick - 1]]

    enemy = cands[0]
    kinds = set(args.kind) if args.kind else set(ENEMY_KIND_DEFAULT)
    rows = enemy_drops(enemy, sources, names, kinds)
    print(f"■ {enemy}  — {len(rows)} 件\n")
    if not rows:
        print("  (選んだ種類のドロップはありません。--kind を外すとすべての種類を表示)")
        return
    out = [[names.ja(r["en"]), AREA_KINDS[r["kind"]], render_ja(r["detail"]), (f"{r['qty']}個 " if r["qty"] else "") + pct(r["chance"]),
            RARITY_JA.get(r["rarity"], r["rarity"])] for r in rows]
    print_table(["アイテム", "種類", "区分", "確率", "レア度"], out, right_cols=(3,))
    print("\n確率: 1体倒したときに落とす割合です(区分の % はその表を引く割合で、確率にはかけ合わせ済み)。")


def add_item(sub) -> None:
    s = sub.add_parser("item", help="アイテム名 -> 入手場所・ステージ・確率 (ミッション・敵・バウンティ・レリック等)")
    s.add_argument("query", nargs="+")
    s.add_argument("--kind", action="append", choices=list(AREA_KINDS),
                   help="探す種類 (複数回指定可。既定は " + ",".join(ITEM_KIND_DEFAULT) + "。"
                        + " / ".join(f"{k}={v}" for k, v in AREA_KINDS.items()) + ")")
    s.add_argument("--all", action="store_true", help="すべての種類を対象にする (--kind より優先)")
    s.add_argument("--pick", type=int, help="候補が複数のとき番号で選ぶ")
    s.add_argument("--limit", type=int, default=50)
    s.add_argument("--events", action="store_true", help="イベント限定ノードも含める")
    s.add_argument("--cat", action="append", choices=list(SOURCE_CATS), help="入手先の種類で絞り込み (複数回指定可)")
    s.set_defaults(fn=cmd_item)

def _recipe_time(sec: int) -> str:
    """作成時間の表示(日・時間・分。秒は1分未満のときだけ)"""
    d, rem = divmod(sec, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    out = (f"{d}日" if d else "") + (f"{h}時間" if h else "") + (f"{m}分" if m else "")
    return out or f"{s}秒"


def _print_recipe_parts(parts: list[dict], depth: int) -> None:
    """要求素材集の入れ子を字下げで出す(部品は下に開く。末端の素材は入手先を RECIPE_SOURCE_LIMIT 件まで)"""
    pad = "  " * depth
    for p in parts:
        if p["kind"] == "part":
            print(f"{pad}{p['ja']} ×{p['count']:,}  [{p['credits']:,} クレジット / {_recipe_time(p['time'])}]")
            _print_recipe_parts(p["parts"], depth + 1)
            continue
        print(f"{pad}{p['ja']} ×{p['count']:,}")
        src = p.get("sources") or {"rows": [], "total": 0}
        for r in src["rows"]:
            stage = "" if r["stage"] == "—" else render_ja(r["stage"])  # ローテーションの無い入手先は出さない
            print(f"{pad}    - {render_ja(r['place'])} / {render_ja(r['detail'])}{' / ' + stage if stage else ''}  {pct(r['chance'])}")
        if not src["rows"]:
            print(f"{pad}    - (入手先が見つかりません)")
        elif src["total"] > len(src["rows"]):
            print(f"{pad}    (ほか {src['total'] - len(src['rows'])} か所。item コマンドで全部見られます)")


def cmd_recipe(args):
    d = datadir.data_dir(args.data_dir)
    recipes, names = load_recipes(d), load_names(d)
    if not recipes:
        sys.exit("要求素材集のデータがありません。先に `python wfportal.py update` を実行してください。")
    query = " ".join(args.query)
    cands = pick_tops(query, recipes.tops(names))
    if not cands:
        sys.exit(f"「{query}」に一致する Warframe・武器などがありません。")
    exact = [c for c in cands if norm(query) in (norm(c["en"]), norm(c["ja"]))]
    if exact:
        cands = exact[:1]
    elif len(cands) > 1 and not args.pick:
        print(f"「{query}」の候補が {len(cands)} 件あります。--pick 番号 で選ぶか、もう少し具体的に入力してください。")
        for i, c in enumerate(cands[:30], 1):
            print(f"  {i:>2}. {c['ja']}  ({c['en']} / {MASTERY_CATS.get(c['cat'], c['cat'])})")
        return
    if args.pick:
        if not 1 <= args.pick <= len(cands):
            sys.exit("--pick の番号が範囲外です。")
        cands = [cands[args.pick - 1]]
    try:
        drops = load_drops(d)
    except DropsMissing:
        drops = None  # ドロップ表がまだ無ければ入手先なしで素材だけ出す
    sources = load_sources(d)

    def sources_of(en: str) -> dict:
        rows = sort_sources(find_sources(en, drops, sources, names)) if drops else []
        return {"rows": rows[:RECIPE_SOURCE_LIMIT], "total": len(rows)}

    view = recipes.view(cands[0]["key"], names, sources_of)
    print(f"■ {view['ja']}  ({view['en']})")
    for i, rec in enumerate(view["recipes"], 1):
        if len(view["recipes"]) > 1:
            print(f"\n― 作り方 {i}/{len(view['recipes'])}")
        print(f"\n{rec['bp_ja']}  [{rec['credits']:,} クレジット / {_recipe_time(rec['time'])}]")
        _print_recipe_parts(rec["parts"], 1)
        print("\n  合計(末端の素材)")
        print_table(["素材", "数"], [[x["ja"], f"{x['count']:,}"] for x in rec["total"]["items"]], right_cols=(1,))
        print(f"  クレジットの合計: {rec['total']['credits']:,}")
    if drops is None:
        print("\n(ドロップ表がまだ無いので入手先は出していません。`python wfportal.py update` で取れます)")


def add_area(sub) -> None:
    s = sub.add_parser("area", help="エリア(惑星/ノード) -> ステージごとの素材と確率")
    s.add_argument("query", nargs="+")
    s.add_argument("--kind", action="append", choices=list(AREA_KINDS),
                   help="出す種類 (複数回指定可。既定は resource=素材だけ。" + " / ".join(f"{k}={v}" for k, v in AREA_KINDS.items()) + ")")
    s.add_argument("--all", action="store_true", help="すべての種類を表示 (--kind より優先)")
    s.add_argument("--all-nodes", action="store_true", help="部分一致のノードをすべて表示")
    s.add_argument("--events", action="store_true")
    s.set_defaults(fn=cmd_area)


def add_enemy(sub) -> None:
    s = sub.add_parser("enemy", help="敵の名前(英語) -> 落とすアイテムと確率")
    s.add_argument("query", nargs="+")
    s.add_argument("--kind", action="append", choices=list(AREA_KINDS),
                   help="出す種類 (複数回指定可。既定はすべて。" + " / ".join(f"{k}={v}" for k, v in AREA_KINDS.items()) + ")")
    s.add_argument("--pick", type=int, help="候補が複数のとき番号で選ぶ")
    s.set_defaults(fn=cmd_enemy)


def add_recipe(sub) -> None:
    s = sub.add_parser("recipe", help="Warframe・武器などの名前 -> 作るのに要る素材(部品ごと)・クレジット・作成時間・素材の入手先")
    s.add_argument("query", nargs="+")
    s.add_argument("--pick", type=int, help="候補が複数のとき番号で選ぶ")
    s.set_defaults(fn=cmd_recipe)


# このグループのコマンド: 名前 -> parser に登録する関数(並び順は wfp/cli/main.py の ORDER)
COMMANDS = {"item": add_item, "area": add_area, "enemy": add_enemy, "recipe": add_recipe}
