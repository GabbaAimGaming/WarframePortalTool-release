"""wfportal の中身(ロジック・取得・保存・CLI・API)。

  core/   共通・名前辞書・機能ロジック
  drops/  ドロップ表・入手先
  fetch/  外部データの取得・解析
  store/  データ置き場の読み書き
  cli/    CLI のコマンド
  api/    画面向けの /api/*

層のルール(tests/test_layers.py で検査):
  - core.common は wfp の他のモジュールを import しない。core.names は core.common だけ
  - drops / fetch / store が import してよいのは core.common・core.names と自分のパッケージ内だけ
  - core の機能ロジックは cli / api を import しない。cli と api はお互いを import しない
  - wfp の中から入口(wfportal.py / wfportal_ui.py / wfportal_update.py)は import しない
  - まだ wfp の外にある機能(wfportal_baro / builder / ocr / worldstate)を import してよいのは cli / api だけ。
    例外: core.update は baro / builder を import してよい(wfp へ移すまでの一時的な扱い)
  - ネット・ファイルに触る関数(fetch/・store/ の関数)は、モジュールごと import して呼ぶ
    (例: from wfp.fetch import net → net.http_get(...))。テストの差し替え先を1か所にするため
"""
