"""CLI: 情報(cycle・baro・riven)"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

from wfp.cli.table import print_table
from wfp.core.common import PHASE_ALIASES, fmt_dur, norm, parse_remaining, rank
from wfp.core.cycle import cycle_rows, next_daily_reset, next_weekly_reset, set_manual_cycle
from wfp.core.loader import load_names, load_rivens
from wfp.core.riven import riven_table, update_rivens
from wfp.store import datadir


def cmd_cycle(args):
    d = datadir.data_dir(args.data_dir)
    if args.action == "set":
        key = (args.target or "").lower()
        phase = PHASE_ALIASES.get(args.phase.lower() if args.phase else "", None)
        try:
            set_manual_cycle(d, key, phase, parse_remaining(args.remaining or ""))
        except ValueError as e:
            sys.exit(str(e))
        print("時刻合わせを保存しました。")
    elif args.action == "sync":
        import wfportal_worldstate as ws
        try:
            snap = ws.sync(d, force=True, verbose=True)
        except ws.WorldStateError as e:
            sys.exit(f"公式データを取得できませんでした: {e}\n※基準時刻(または前回の同期)からの計算で表示します。")
        print(f"公式データで同期しました(PC の時計のずれ {snap['offset']:+.0f} 秒)。")
    jst = timezone(timedelta(hours=9))
    view = cycle_rows(d)
    now = view["now"]
    nowdt = datetime.fromtimestamp(now, jst)
    print(f"現在 {nowdt:%Y-%m-%d %H:%M:%S} JST" + (f"  (PC の時計を {view['offset']:+.0f} 秒補正)" if view["offset"] else "") + "\n")
    for r in view["cycles"]:
        end = datetime.fromtimestamp(now + r["left"], jst)
        print(f"{r['name']}: {r['phase']}  残り {fmt_dur(r['left'])}  (切替 {end:%H:%M:%S} → {r['next']})  [{r['source_ja']}]")
        if "cambion" in r:
            print(f"カンビオンの荒地: {r['cambion']}  (Cetus と連動)")
    dr, wr = next_daily_reset(nowdt), next_weekly_reset(nowdt)
    print(f"\nデイリーリセットまで  {fmt_dur((dr - nowdt).total_seconds())}  ({dr.astimezone(jst):%m/%d %H:%M} JST)")
    print(f"ウィークリーリセットまで {fmt_dur((wr - nowdt).total_seconds())}  ({wr.astimezone(jst):%m/%d %H:%M} JST)")


def cmd_baro(args):
    import wfportal_baro as wbaro
    d = datadir.data_dir(args.data_dir)
    words = list(args.query)
    action = words.pop(0) if words and words[0] in ("update", "own", "unown") else "show"
    if action == "update":
        r = wbaro.update_all(d, verbose=True)
        if r["errors"]:
            sys.exit(" / ".join(r["errors"]))
        if r["recorded"]:
            print(f"  {r['recorded']} の来訪を記録しました(履歴リストに追加・最後に来た日と回数を更新)")
    elif action in ("own", "unown"):
        name = " ".join(words)
        try:
            wbaro.set_manual_owned(d, name, action == "own")
        except ValueError as e:
            sys.exit(str(e))
        print(f"{name} を{'所持にしました' if action == 'own' else '未所持に戻しました'}。")
        return
    names = load_names(d)
    view = wbaro.baro_view(d, names)
    jst = timezone(timedelta(hours=9))
    mark = {True: "○", False: "×", None: "-"}
    cur = view["current"]
    if cur:
        when = lambda t: datetime.fromtimestamp(t, jst).strftime("%m/%d %H:%M")
        state = {"here": "来ています", "coming": "次に来ます", "gone": "前回の来訪(終了)"}[cur["state"]]
        print(f"バロ: {state}  {cur['relay']}  {when(cur['activation'])} 〜 {when(cur['expiry'])} JST")
        for it in cur["items"]:
            print(f"  {mark[it['owned']]} {it['ja']}  ({it['kind_ja']} / {it['ducats']} ドゥカット + {it['credits']:,} cr)")
        print()
    else:
        print("今回の品物: 未取得(baro update で取得できます)\n")
    if not view["rows"]:
        print("履歴リスト: まだありません(update でデータを取得するか、バロが来ているときに baro update を実行してください)")
        return
    q = norm(" ".join(words)) if words else ""
    rows = [r for r in view["rows"] if (not q or q in norm(r["name"]) or q in norm(r["ja"]))
            and (not args.kind or r["kind"] == args.kind) and (not args.unowned or r["owned"] is False)]
    rows.sort(key=lambda r: (r["last"] or ""), reverse=True)
    sm = view["summary"]["all"]
    v = view["visits"]
    print(f"履歴リスト {len(view['rows'])} 件(照合できるもの: 所持 {sm['owned']} / {sm['total']})"
          f"  記録した来訪 {v['count']} 回" + (f"(最新 {v['latest']})" if v["latest"] else ""))
    for r in rows[:args.limit]:
        seen = f"最後 {r['last']} / {r['count']} 回" if r["count"] else "未記録"
        print(f"  {mark[r['owned']]} {r['ja']}  [{r['kind_ja']}]  {seen}")
    if len(rows) > args.limit:
        print(f"  ... ほか {len(rows) - args.limit} 件 (--limit で増やせます)")


def cmd_riven(args):
    d = datadir.data_dir(args.data_dir)
    if args.update and not update_rivens(d):
        sys.exit(1)
    raw = load_rivens(d)
    if raw is None:
        sys.exit("Riven 相場のデータがありません。`python wfportal.py update` を実行してください。")
    rows = riven_table(raw, load_names(d))
    if args.query:
        q = " ".join(args.query)
        rows = [r for r in rows if rank(q, [r["weapon_en"], r["weapon_ja"], r["type_ja"]]) is not None]
    if args.type:
        rows = [r for r in rows if norm(args.type) in (norm(r["type_ja"]), norm(r["type"].split(" ")[0]))]
    if not rows:
        sys.exit("条件に合う Riven がありません。")
    stat = lambda s: f"{s['median']:g} ({s['min']:g}〜{s['max']:g}, {int(s['pop'])}件)" if s else "—"
    print_table(["武器", "武器種", "未リロール 中央値(最小〜最大, 件数)", "リロール済み 中央値(最小〜最大, 件数)"],
                [[r["weapon_ja"], r["type_ja"], stat(r["unrolled"]), stat(r["rerolled"])] for r in rows[: args.limit]])
    f = d / "rivens.json"
    print(f"\n単位はプラチナ(PC 版・公式の週次統計 / {datetime.fromtimestamp(f.stat().st_mtime):%Y-%m-%d} 取得)。"
          "極端な出品価格が混ざるため、平均より中央値が目安になります。")


def add_cycle(sub) -> None:
    s = sub.add_parser("cycle", help="昼夜サイクルとリセット時刻")
    s.add_argument("action", nargs="?", default="show", choices=["show", "set", "sync"],
                   help="sync: 公式データ(World State)で時刻合わせ / set: ゲーム内の残り時間で手動の時刻合わせ")
    s.add_argument("target", nargs="?", help="set のとき cetus / vallis")
    s.add_argument("phase", nargs="?", help="現在のフェーズ (昼/夜/温暖/寒冷)")
    s.add_argument("remaining", nargs="?", help="そのフェーズの残り時間 (分 or mm:ss)")
    s.set_defaults(fn=cmd_cycle)


def add_riven(sub) -> None:
    s = sub.add_parser("riven", help="Riven 相場 (公式の週次統計)")
    s.add_argument("query", nargs="*", help="武器名で絞り込み")
    s.add_argument("--type", help="武器種 (ライフル / 近接 / rifle など)")
    s.add_argument("--limit", type=int, default=40)
    s.add_argument("--update", action="store_true", help="Riven 相場だけを取得し直してから表示")
    s.set_defaults(fn=cmd_riven)


def add_baro(sub) -> None:
    s = sub.add_parser("baro", help="バロ吉入手一覧 (Void 商人の商品と所持の照合)")
    s.add_argument("query", nargs="*", metavar="[update|own|unown] 名前",
                   help="名前で絞り込み。update で今回の品物を取得(来ていれば来訪を記録)、own / unown で手動の所持チェックを付ける / 外す")
    s.add_argument("--kind", choices=["mod", "weapon", "manual", "repeat"], help="種類で絞り込み")
    s.add_argument("--unowned", action="store_true", help="未所持のみ")
    s.add_argument("--limit", type=int, default=60)
    s.set_defaults(fn=cmd_baro)


# このグループのコマンド: 名前 -> parser に登録する関数(並び順は wfp/cli/main.py の ORDER)
COMMANDS = {"cycle": add_cycle, "riven": add_riven, "baro": add_baro}
