#!/usr/bin/env python3
"""wfportal - Warframe ポータルツール (標準ライブラリのみ / Python 3.9+)

  python wfportal.py update                  公式データを取得(初回と更新時)
  python wfportal.py item ニューロード        素材 -> どこで何%で出るか(逆引き)
  python wfportal.py area 地球                エリア -> 出現ステージごとの素材一覧
  python wfportal.py cycle                    昼夜サイクルとリセットまでの時間 (cycle sync で公式データと時刻合わせ)
  python wfportal.py baro                     バロ吉入手一覧 (Void 商人の商品と所持の照合)
  python wfportal.py mods                     MOD 入手一覧 (入手先と所持チェック)
  python wfportal.py arcane                   アルケイン所持一覧 (所持チェックとランク)
  python wfportal.py riven ルビコ              Riven 相場 (公式の週次統計)
  python wfportal.py mastery                  マスター一覧 (Warframe・武器などのマスター済みチェック)
  python wfportal.py build list               ビルド管理
  python wfportal.py build analyze 画像.png     ビルド画像の自動解析 (Windows の文字認識)
  python wfportal.py logos                    公式ファンキットのロゴ素材を取得 (初回起動時に自動)

非公式のファンツールです。Digital Extremes Ltd. とは関係ありません。

データ置き場は既定で ~/.wfportal (環境変数 WFPORTAL_DIR か --data-dir で変更可)。
"""
from __future__ import annotations

from wfp.cli.main import main as cli_main


def serve(argv: list[str]) -> None:
    """画面サーバーを起動する(serve / 引数なし)"""
    from wfp.api import server  # 画面を使わない場合は読み込まない
    server.main(argv)


def main(argv: list[str] | None = None) -> None:
    cli_main(argv, serve=serve)


if __name__ == "__main__":
    main()
