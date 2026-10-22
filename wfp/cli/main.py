"""CLI の組み立てと実行(コマンドは各グループの COMMANDS から集める)"""
from __future__ import annotations

import argparse
import sys
from typing import Callable

from wfp.cli import admin, info, personal, search
from wfp.core.common import app_version

GROUPS = (search, personal, info, admin)
# --help に出るコマンドの並び順。コマンドを足したらここにも足す(tests/test_cli.py が漏れ・重複を検査する)
ORDER = ("serve", "update", "logos", "item", "area", "cycle", "build", "mods", "riven", "mastery", "arcane",
         "baro")


def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="wfportal", description="Warframe ポータルツール")
    p.add_argument("--version", action="version", version=f"Warframe Portal Tool v{app_version()}")
    p.add_argument("--data-dir", help="データ置き場 (既定: ~/.wfportal)")
    sub = p.add_subparsers(dest="cmd")  # 省略時は画面(serve)を起動
    registry = {name: add for g in GROUPS for name, add in g.COMMANDS.items()}
    for name in ORDER:
        registry[name](sub)
    return p


def main(argv: list[str] | None = None, serve: Callable[[list[str]], None] | None = None) -> None:
    """serve: 画面サーバーを起動する関数(引数は wfportal_ui の引数)。入口(wfportal.py)が渡す"""
    args = make_parser().parse_args(argv)
    if args.cmd is None:
        args.port, args.no_browser = 8765, False
    try:
        if args.cmd in (None, "serve"):
            if serve is None:
                sys.exit("画面の起動は wfportal.py から行ってください。")
            serve(admin.serve_argv(args))
        else:
            args.fn(args)
    except BrokenPipeError:  # `| head` などで出力が途中で閉じられた場合
        sys.stderr.close()
