"""文字認識(OCR)のエンジン。2026-11-20 に wfportal_ocr.py の「Windows の文字認識を呼ぶ」部分から分けた。

  result  結果の形の約束(check_result)と、言語で結果を選ぶ(pick_result)
  engine  エンジンの共通の形(OcrEngine・OcrRequest)・選び方(select_engine)・画像のバイト列の文字認識(run_ocr_bytes)
  winrt   Windows OCR(ocr/winocr.ps1)

層: core の機能ロジックと同じ段(core のいちばん下の層・drops / fetch / store・自分のパッケージを使ってよい)。
cli / api と wfp の外の機能(wfportal_ocr など)は import しない。解析(wfportal_ocr・msscan・rivenscan)はエンジンに
関係なく result の形だけに頼る。設計は claude/ocr_engine_plan.md。
"""
