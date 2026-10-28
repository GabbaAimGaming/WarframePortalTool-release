"""CLI: 管理(update・logos・serve)"""
from __future__ import annotations

import sys

from wfp.core import update
from wfp.core.common import EXPORT_EXTRA_LANGS
from wfp.fetch import logos
from wfp.store import datadir


def cmd_update(args):
    d = datadir.data_dir(args.data_dir)
    try:
        update.update_all(d, (args.lang,) if getattr(args, "lang", None) else ())
    except update.UpdateFailed as e:
        sys.exit(str(e))


def cmd_logos(args):
    d = datadir.data_dir(args.data_dir)
    if args.if_missing and logos.find_logos_dir(d):
        return
    logos.fetch_logos(d, force=args.force)



def serve_argv(args) -> list[str]:
    """serve の引数を画面サーバー(wfportal_ui)の引数にする。起動そのものは入口(wfportal.py)が行う"""
    argv = ["--port", str(args.port)]
    if args.data_dir:
        argv += ["--data-dir", args.data_dir]
    if args.no_browser:
        argv.append("--no-open")
    return argv

def add_serve(sub) -> None:
    s = sub.add_parser("serve", help="ブラウザで操作する画面を起動 (引数なしでも起動)")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-browser", action="store_true", help="ブラウザを自動で開かない")
    s.set_defaults(fn=None)  # 起動は入口(wfportal.py)が行う


def add_update(sub) -> None:
    s = sub.add_parser("update", help="公式データを取得/更新")
    s.add_argument("--lang", choices=EXPORT_EXTRA_LANGS,
                   help="日本語・英語のほかに名前辞書を取る言語 (公式 Public Export の言語コード。取得済みの言語は指定しなくても取り直す)")
    s.set_defaults(fn=cmd_update)


def add_logos(sub) -> None:
    s = sub.add_parser("logos", help="公式ファンキットのロゴ素材を取得 (各自の PC に保存)")
    s.add_argument("--force", action="store_true", help="取得済みでも取り直す")
    s.add_argument("--if-missing", action="store_true", help="未取得のときだけ取得する (起動用バッチから使用)")
    s.set_defaults(fn=cmd_logos)


# このグループのコマンド: 名前 -> parser に登録する関数(並び順は wfp/cli/main.py の ORDER)
COMMANDS = {"serve": add_serve, "update": add_update, "logos": add_logos}
