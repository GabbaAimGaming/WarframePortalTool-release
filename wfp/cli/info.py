"""CLI: 情報(cycle・arby・baro・riven・modstats・ask)"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

from wfp.cli.table import print_table
from wfp.core.arbitration import arbitration_view, load_schedule, update_arbys
from wfp.core.archon import shard_list
from wfp.core.common import (BARO_KINDS, CAMBION, CYCLE_SOURCES, CYCLES, FACTIONS_JA, MODES_JA, MOD_GROUPS, PHASE_ALIASES, QA_ANSWERS_FILE, QA_INTENTS_FILE,
                             QA_LORE_FILE, QA_LORE_TALK_FILE, QA_MENU_FILE, QA_MISS_FILE, QA_TALK_FILE, RIVEN_TYPES_JA, fmt_dur, norm, parse_remaining, rank,
                             error_text, render_ja, txt)
from wfp.core.cycle import cycle_rows, next_daily_reset, next_weekly_reset, set_manual_cycle
from wfp.core.devbuilds import dev_build_list
from wfp.core.helminth import subsume_list
from wfp.core.loader import DropsMissing, load_drops, load_names, load_rivens, load_sources
from wfp.core.modstats import fold, load_mod_stats, parse_groups
from wfp.core.qa import QaContext, QaIndex, answer, load_qa_data, stop_words
from wfp.core.qalore import index_names, load_lore
from wfp.core.qamenu import load_menu
from wfp.core.qatalk import load_talk
from wfp.core.quests import check_flow
from wfp.core.riven import riven_table, update_rivens
from wfp.core.summons import summon_list
from wfp.drops.search import all_item_names
from wfp.store import appdata, datadir, userdata


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
    phase_ja = {p[0]: p[1] for c in CYCLES.values() for p in c["phases"]}
    for r in view["cycles"]:
        end = datetime.fromtimestamp(now + r["left"], jst)
        print(f"{CYCLES[r['key']]['name']}: {phase_ja[r['phase_key']]}  残り {fmt_dur(r['left'])}  "
              f"(切替 {end:%H:%M:%S} → {phase_ja[r['next_key']]})  [{CYCLE_SOURCES[r['source']]}]")
        if "cambion" in r:
            print(f"カンビオンの荒地: {CAMBION[r['cambion']]}  (Cetus と連動)")
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
            sys.exit(" / ".join(render_ja(e) for e in r["errors"]))
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
        print(f"バロ: {state}  {render_ja(cur['relay'])}  {when(cur['activation'])} 〜 {when(cur['expiry'])} JST")
        for it in cur["items"]:
            print(f"  {mark[it['owned']]} {it['ja']}  ({BARO_KINDS[it['kind']]} / {it['ducats']} デュカット + {it['credits']:,} cr)")
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
        print(f"  {mark[r['owned']]} {r['ja']}  [{BARO_KINDS[r['kind']]}]  {seen}")
    if len(rows) > args.limit:
        print(f"  ... ほか {len(rows) - args.limit} 件 (--limit で増やせます)")


def cmd_riven(args):
    d = datadir.data_dir(args.data_dir)
    if args.update and not update_rivens(d):
        sys.exit(1)
    raw = load_rivens(d)
    if raw is None:
        sys.exit("Riven 相場のデータがありません。`python wfportal.py update` を実行してください。")
    # 武器種・未開封の表示名は CLI で付ける(一覧の中身はキーのまま)
    rows = [{**r, "type_ja": RIVEN_TYPES_JA.get(r["type"], r["type"].replace(" Riven Mod", "")),
             "weapon_ja": r["weapon_ja"] if not r["veiled"] else "未開封(ヴェール)"} for r in riven_table(raw, load_names(d))]
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


def _pick_target(data, args) -> str | None:
    """影響先キーを決める。--target はキーか表示名。指定が無ければ入力が影響先の名前に当たるか見る(当たらなければ全文検索)"""
    word = (args.target or "").strip()
    if word:
        hits = [k for k, ent in data.targets.items() if fold(word) in (fold(k), fold(ent["ja"]), fold(ent["en"]))]
        if not hits:
            sys.exit(f"影響先が見つかりません: {word}(--targets で一覧)")
        return hits[0]
    query = " ".join(args.query)
    if args.text or not query:
        return None
    cands = data.suggest(query)
    exact = [c["key"] for c in cands if fold(query) in (fold(c["ja"]), fold(c["en"]))]
    if exact or len(cands) == 1:
        return exact[0] if exact else cands[0]["key"]
    if cands:
        print("影響先の候補: " + " / ".join(f"{c['ja']}({c['key']})" for c in cands))
        sys.exit("--target で選ぶか、--text で効果テキストを全文検索してください。")
    return None


def cmd_modstats(args):
    d = datadir.data_dir(args.data_dir)
    data = load_mod_stats(d)
    if data is None:
        sys.exit(render_ja(txt("err.nodata")))
    if args.targets:
        for key, ent in data.targets.items():
            print(f"{key:<20} {ent['ja']} / {ent['en']}")
        return
    try:
        groups = parse_groups(args.group or "")
    except ValueError as e:
        sys.exit(str(e))
    target = _pick_target(data, args)
    res = data.find(target or "", "" if target else " ".join(args.query), groups, args.limit)
    if res["target"]:
        print(f"影響先: {res['target']['ja']}\n")
    names = {k: ent["ja"] for k, ent in data.targets.items()}
    for row in res["rows"]:
        compat = f"  対象: {row['compat']}" if row["compat"] and row["compat"].upper() != row["compat"] else ""
        print(f"■ {row['ja']}  [{' / '.join(MOD_GROUPS[g] for g in row['groups'])}]{compat}")
        if row["targets"]:
            cond = "(条件付きあり)" if any(ln["cond"] for ln in row["lines"]) else ""
            print(f"  影響先: {'、'.join(names[k] for k in row['targets'])}{cond}")
        ranks = row["stats_ja"] or row["stats_en"]
        picks = range(len(ranks)) if args.ranks else sorted({0, len(ranks) - 1}) if ranks else []
        for idx in picks:
            print(f"  R{idx:<2}: " + " / ".join(ln.replace("\n", " ") for ln in ranks[idx]))
        if not ranks:
            print("  " + (row["desc_ja"] or row["desc_en"]).replace("\n", " "))
    print(f"\n{res['total']} 件" + (f"(先頭 {len(res['rows'])} 件を表示)" if res["total"] > len(res["rows"]) else ""))


def cmd_ask(args):
    """Q&A(日本語のみ)。データ置き場の builder.json・ドロップ表・名前辞書と同梱データから答える"""
    import wfportal_builder as wb
    question = " ".join(args.question).strip()
    if not question and not args.lore and not args.menu and not args.talk:
        sys.exit(render_ja(txt("err.qa.empty")))
    d = datadir.data_dir(args.data_dir)
    names = load_names(d)
    try:
        drops = load_drops(d)
    except DropsMissing:
        drops = None
    sources = load_sources(d)
    items = all_item_names(drops, sources) if drops else []
    data = load_qa_data(appdata.read_qa(QA_INTENTS_FILE), appdata.read_qa(QA_ANSWERS_FILE), appdata.read_qa(QA_MISS_FILE))
    builder, subsume = wb.load_builder_data(d), subsume_list(appdata.read_helminth())
    dev = dev_build_list(appdata.read_dev_builds())
    lore = load_lore(appdata.read_qa(QA_LORE_FILE), appdata.read_qa(QA_LORE_TALK_FILE))
    index = QaIndex(builder, names, items, subsume, dev, stop_words(data), summon_list(appdata.read_summons()), index_names(lore))
    quest_names = {q["id"]: q["ja"] for q in check_flow(appdata.read_quests()) if q["kind"] == "quest"}
    ctx = QaContext(data, index, builder=builder, drops=drops, sources=sources, items=items, subsume=subsume,
                    archon=shard_list(appdata.read_archon()), dev=dev, mod_stats=load_mod_stats(d),
                    lore=lore, done=userdata.load_quests_done(d), quest_names=quest_names,
                    menu=load_menu(appdata.read_qa(QA_MENU_FILE)), talk=load_talk(appdata.read_qa(QA_TALK_FILE)))
    print_qa(answer(ctx, question, lore=args.lore or None, spoil=args.spoil, only=args.only, menu=args.menu or None,
                    talk=args.talk or None))


def print_qa(res: dict) -> None:
    """Q&A の答えを標準出力に出す"""
    for line in (res["miss"]["text"] if res["miss"] else "", res["text"]):
        if line:
            print(line)
    if res["spoiler"]:
        print(f"(--lore {res['spoiler']['id']} --spoil{' --only' if res['spoiler']['only'] else ''} で聞けます)")
    if res["talk"]:
        print(f"■ {res['talk']['title']}")
        for para in res["talk"]["paragraphs"]:
            print(f"  {para}")
    if res["lore"]:
        lore = res["lore"]
        print(f"■ {lore['parts'][0]['title']}")  # 見出しは 0段目(最初の段)のタイトル、2つ目からの段は小見出し
        for i, part in enumerate(lore["parts"]):
            if i:
                print(f"□ {part['title']}")
            if part["prefix"]:
                print(part["prefix"])
            for para in part["paragraphs"]:
                print(f"  {para}")
        if lore["credit"] or lore["source"]:
            print("(出典: " + " / ".join(x for x in (lore["credit"], lore["license"]) if x) + ")")
            for url in lore["source"]:
                print(f"  {url}")
    if res["next"]:
        print(f"{res['next']['label']} → --lore {res['next']['id']} --only")
    for f in res["facts"]:
        value = f["value"].replace("\n", "\n    ")  # 複数行の値(呼び出しのアビリティの数値など)は字下げしてそろえる
        print(f"  {f['label']}: {value}" if f["label"] and value else f"  {f['label'] or value}")
    for group in res["sources"]:
        if group["title"]:
            print(f"■ {group['title']}")
        for r in group["rows"]:
            print(f"  {r['chance']:>7}  {r['where']}" + (f"  ×{r['qty']}" if r["qty"] else ""))
            if r.get("relics"):  # 時代ごとのレリックの入手先: その場所で出るレリック
                print("           " + " / ".join(x["name"] + (f" {x['chance']}" if x["chance"] else "") for x in r["relics"]))
    for b in res["builds"]:
        print(f"■ {b['name']}({b['type_ja']}・{b['target_ja']}・フォーマ {b['forma']})")
        for m in b["mods"]:
            print(f"  MOD: {m['name']}" + (f"  … {m['effect']}" if m["effect"] else ""))
        if b["arcanes"]:
            print(f"  アルケイン: {'、'.join(b['arcanes'])}")
        if b["helminth"]:
            print(f"  Helminth: {b['helminth']}")
        for sh in b["shards"]:
            print(f"  欠片: {sh}")
        if b["note"]:
            print(f"  メモ: {b['note']}")
    if res["candidates"]:
        print("もしかして: " + "、".join(c["ja"] for c in res["candidates"]))
    if res["options"]:
        print((res["options_title"] or "聞けること") + ": " + "、".join(
            o["label"] + _option_hint(o) for o in res["options"]))
    if res["basis"]:
        print(f"({res['basis']})")


def _option_hint(o: dict) -> str:
    """CLI でボタンの代わりに使う引数の案内(解説 --lore・メニュー --menu・話 --talk・画面のページ・例文 q は label と違うときだけ質問の文)"""
    if o.get("lore"):
        return f"(--lore {o['lore']})"
    if o.get("menu"):
        return f"(--menu {o['menu']})"
    if o.get("talk"):
        return f"(--talk {o['talk']})"
    if o.get("page"):
        return f"(画面のページ {o['page']})"
    if o.get("q") and o["q"] != o["label"]:
        return f"(「{o['q']}」)"
    return ""


def cmd_arby(args):
    """仲裁: 今の枠と次の枠(画面と同じく今の1件 + 次の12件)。sync でスケジュールを取り直す"""
    d = datadir.data_dir(args.data_dir)
    if args.action == "sync":
        try:
            update_arbys(d)
        except Exception as e:  # noqa: BLE001
            print(render_ja(txt("err.arbys.fetch", e=error_text(e))), file=sys.stderr)
        else:
            print("仲裁のスケジュールを取り直しました。")
    view = arbitration_view(d, load_schedule(d))
    if not view["has_schedule"]:
        sys.exit("仲裁のスケジュールがまだありません。`update` か `arby sync` で取得してください。")
    if view["out_of_range"]:
        sys.exit("保存済みのスケジュールの範囲を過ぎました。`arby sync` で取り直してください。")
    jst = timezone(timedelta(hours=9))
    if not view["regions_ok"]:
        print("※ノード名の辞書がまだ無いため、内部名で表示しています(`update` で取得できます)。")
    elif view["regions_old"]:
        print("※ノード名の辞書が古いため、ミッションの種類と敵がわかりません(`update` で取り直してください)。")
    out = []
    for r in view["rows"]:
        start, end = datetime.fromtimestamp(r["start"], jst), datetime.fromtimestamp(r["end"], jst)
        when = f"{start:%m/%d %H:%M}〜{end:%H:%M}"
        node = f"{r['node_ja']}({r['planet_ja']})" if r["planet_ja"] else r["node_ja"]
        mission = MODES_JA.get(r["mission"], r["mission"]) if r["mission"] else _arby_unknown(r["mission_index"])
        faction = FACTIONS_JA.get(r["faction"], r["faction"]) if r["faction"] else _arby_unknown(r["faction_index"])
        left = f"残り {fmt_dur(r['end'] - view['now'])}" if r["current"] else ""
        out.append(["▶" if r["current"] else "", when, node, mission, faction, left])
    print_table(["", "時間(JST)", "ノード", "ミッション", "敵", ""], out)


def _arby_unknown(index) -> str:
    return f"不明({index})" if index is not None else "不明"


def add_arby(sub) -> None:
    s = sub.add_parser("arby", help="仲裁(今の枠と次の 12 件)")
    s.add_argument("action", nargs="?", default="show", choices=["show", "sync"],
                   help="sync: スケジュール(browse.wf の arbys.txt)を取り直す")
    s.set_defaults(fn=cmd_arby)


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


def add_modstats(sub) -> None:
    s = sub.add_parser("modstats", help="MOD 効果検索 (影響先・効果テキストで探す)")
    s.add_argument("query", nargs="*", help="影響先の名前(例: 威力)か、効果テキストの一部")
    s.add_argument("--target", help="影響先のキーか名前 (ability_strength / アビリティ威力 など)")
    s.add_argument("--text", action="store_true", help="影響先の名前と見なさず、効果テキストを全文検索する")
    s.add_argument("--group", help="区分で絞り込み (カンマ区切り: " + ",".join(MOD_GROUPS) + ")")
    s.add_argument("--ranks", action="store_true", help="全ランクの効果を出す (既定はランク0と最大)")
    s.add_argument("--targets", action="store_true", help="影響先の一覧を出す")
    s.add_argument("--limit", type=int, default=30)
    s.set_defaults(fn=cmd_modstats)


def add_ask(sub) -> None:
    s = sub.add_parser("ask", help="Q&A(β) (フレーム・武器の数値・入手先・開発者のビルド・Helminth・設定とストーリーの解説を質問の文で聞く。日本語のみ)")
    s.add_argument("question", nargs="*", help="質問の文(例: Rhino のアーマーは? / グリニアって何?)")
    s.add_argument("--lore", help="解説の id を指定して聞く(例: setting.grineer)")
    s.add_argument("--spoil", action="store_true", help="クエストのネタバレの確認を飛ばす")
    s.add_argument("--only", action="store_true", help="--lore の段だけを出す(続き。指定なしは 0段目からその段まで)")
    s.add_argument("--talk", help="ツールの使い方・雑談の話の id を指定して聞く(例: chat.omikuji)")
    s.add_argument("--menu", help="「教えてクロちゃん」の分類の id を指定して聞く(例: stats。top で分類の一覧)")
    s.set_defaults(fn=cmd_ask)


# このグループのコマンド: 名前 -> parser に登録する関数(並び順は wfp/cli/main.py の ORDER)
COMMANDS = {"cycle": add_cycle, "arby": add_arby, "riven": add_riven, "baro": add_baro, "modstats": add_modstats, "ask": add_ask}
