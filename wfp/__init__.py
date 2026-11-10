"""wfportal の中身(ロジック・取得・保存・CLI・API)。

  core/   定数(const)・OCR の読み替えの表(ocr_chars)・文字の正規化(text)・テキスト指定と日本語の文(i18n)・ログ(log)・
          テキスト指定の例外(errors)・共通(common)・名前のあいまい一致(matcher)・名前辞書・機能ロジック
  drops/  ドロップ表・入手先
  fetch/  外部データの取得・解析
  store/  データ置き場の読み書き
  cli/    CLI のコマンド
  api/    画面向けの /api/*

層のルール(tests/test_layers.py で検査):
  - core.const(定数)・core.ocr_chars(OCR の読み替えの表)は wfp の他のモジュールを import しない。core.text(正規化)はその2つだけ。
    core.i18n(テキスト指定・日本語の文)は core.const だけ。core.log・core.errors は core.i18n まで。core.common は core.errors まで。
    core.names は core.common まで(並び: const・ocr_chars → text → i18n → log・errors → common → names)
  - drops / fetch / store が import してよいのは core.const・core.ocr_chars・core.text・core.i18n・core.log・core.errors・core.common・
    core.names と自分のパッケージ内だけ
  - core の機能ロジックは cli / api を import しない。cli と api はお互いを import しない
  - wfp の中から入口(wfportal.py / wfportal_ui.py / wfportal_update.py)は import しない
  - まだ wfp の外にある機能(wfportal_baro / builder / msscan / ocr / rivenscan)を import してよいのは cli / api だけ
    (2026-11-10 に core.update の例外をなくした)
  - wfp の外の機能どうしは import しない(共用するものは core へ。例: core.matcher の NameMatcher)。
    World State は wfp に移した(fetch.worldstate・core.worldstate)
  - ネット・ファイルに触る関数(fetch/・store/ の関数)は、モジュールごと import して呼ぶ
    (例: from wfp.fetch import net → net.http_get(...))。テストの差し替え先を1か所にするため
"""
