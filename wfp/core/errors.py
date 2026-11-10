"""文がテキスト指定の例外: TextError(入力の誤り。ValueError の仲間)・TextFailure(取得・処理の失敗。RuntimeError の仲間)・error_text。

str() は日本語の文(CLI 用)、text はテキスト指定(API が ApiError(error_text(e)) で画面へ渡す)。
2026-11-10 に core/common から分けた(D2)。import してよい wfp は core.i18n まで
"""
from __future__ import annotations

from wfp.core.i18n import render_ja


class _TextMessage:
    """文がテキスト指定の例外の共通部分。str() は日本語の文(CLI 用)、text はテキスト指定(API が画面へ渡す)"""

    def __init__(self, text):
        self.text = text
        super().__init__(render_ja(text))


class TextError(_TextMessage, ValueError):
    """入力・値の誤り(ValueError の仲間)。文はテキスト指定"""


class TextFailure(_TextMessage, RuntimeError):
    """取得・処理の失敗(RuntimeError の仲間)。文はテキスト指定"""


def error_text(e: BaseException):
    """例外の文: テキスト指定があればそれ(TextError)、無ければ str(e)(API の ApiError にそのまま渡せる)"""
    return getattr(e, "text", None) or str(e)
