"""文字認識の結果の形(エンジン共通の約束)と、言語で結果を選ぶ部品。

形(座標は元の画像のピクセル):
  {"width": W, "height": H, "scale": s, "engine": "winrt",
   "results": [{"lang": "en-US", "lines": [{"text": "...", "words": [{"text", "x", "y", "w", "h"}]}]}],
   "available": ["en-US", ...]}
engine が無い結果(前のキャッシュ・テストの JSON)は winrt のものとみなす。
"""
from __future__ import annotations

from wfp.core.const import OCR_ENGINE_WINRT, OCR_LANG_MULTI

WORD_KEYS = ("x", "y", "w", "h")


def result_engine(data: dict) -> str:
    """結果を作ったエンジン(書いていなければ winrt)"""
    return str(data.get("engine") or OCR_ENGINE_WINRT)


def _word_problem(word, width: float | None, height: float | None) -> str:
    """単語の形の誤り(無ければ空)"""
    if not isinstance(word, dict) or not isinstance(word.get("text"), str):
        return "word"
    if not all(isinstance(word.get(k), (int, float)) for k in WORD_KEYS):
        return "word box"
    if word["w"] < 0 or word["h"] < 0:
        return "word size"
    if width and (word["x"] < -1 or word["x"] + word["w"] > width + 1):
        return "word x"
    if height and (word["y"] < -1 or word["y"] + word["h"] > height + 1):
        return "word y"
    return ""


def check_result(data) -> str:
    """結果の形を確かめる。誤りの場所(開発者向けの短い文字列)を返し、合っていれば空。エンジンの出口で通す"""
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        return "results"
    width, height = data.get("width"), data.get("height")
    for res in data["results"]:
        if not isinstance(res, dict) or not isinstance(res.get("lines"), list):
            return "lines"
        for line in res["lines"]:
            if not isinstance(line, dict) or not isinstance(line.get("text"), str) or not isinstance(line.get("words"), list):
                return "line"
            for word in line["words"]:
                problem = _word_problem(word, width, height)
                if problem:
                    return problem
    return ""


def lang_matches(res: dict, lang_head: str) -> bool:
    """結果がその言語(頭の文字。例: "en")のものか。複数の言語を1回で読んだ結果(mul)はどの言語にも当たる"""
    lang = str(res.get("lang", "")).lower()
    return lang == OCR_LANG_MULTI or lang.startswith(lang_head.lower())


def pick_result(data_or_results, lang_head: str) -> dict | None:
    """結果の中から、その言語の結果を1つ選ぶ(無ければ None)。引数は結果全体か results の一覧"""
    results = data_or_results.get("results") or [] if isinstance(data_or_results, dict) else data_or_results
    return next((res for res in results if isinstance(res, dict) and lang_matches(res, lang_head)), None)
