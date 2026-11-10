"""文字の正規化(照合・検索のために表記をそろえる)をここに集める。目的ごとに関数を分ける:

- norm      名前の検索・照合の基本(全角/半角・大小・ひらがな→カタカナ・空白と記号を消す)。検索・Q&A・ビルドなど
- spaced    英字の照合用。norm と同じく記号を消すが、空白(と - _)は1つの空白で残す(単語の区切りを見るため。Q&A)
- fold_case 全角/半角・大小だけそろえる(文の全文検索。MOD 効果検索)
- fold_ocr  文字認識の読み違いに強い形(空白・長音・中黒・濁点を消し、小さいかな・似た漢字をそろえる。画面の読み取り)
- ocr_key   文字認識の英数字の取り違え(0/o・1/l/i・5/s)をそろえた照合キー(ビルド画像・画面の読み取り)

記号の集合は core.const(TEXT_PUNCT TEXT_SEP)、文字認識の読み替えの表は core.ocr_chars。wfp で import してよいのはこの2つだけ
"""
from __future__ import annotations

import re
import unicodedata

from wfp.core.const import TEXT_PUNCT, TEXT_SEP
from wfp.core.ocr_chars import OCR_CONFUSE, OCR_DASHES, OCR_KANA_FOLD, OCR_KEY_KEEP

_NORM_DROP = re.compile(f"[{TEXT_SEP}{TEXT_PUNCT}]")
_SPACED_DROP = re.compile(f"[{TEXT_PUNCT}]")
_SPACED_SEP = re.compile(f"[{TEXT_SEP}]+")
_OCR_DROP = re.compile("[\\s" + re.escape(OCR_DASHES + "ー・") + "]")
_OCR_DASH = re.compile("[" + re.escape(OCR_DASHES) + "]")
_OCR_KEY_DROP = re.compile(f"[^{OCR_KEY_KEEP}]")
_KANA_FOLD = str.maketrans(OCR_KANA_FOLD)
_CONFUSE = str.maketrans(OCR_CONFUSE)


def hira_to_kata(s: str) -> str:
    """ひらがなをカタカナにする(ぁ〜ゖ。ほかの字はそのまま)"""
    return "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in s)


def norm(s: str) -> str:
    """名前の検索・照合の基本形: NFKC(全角/半角)・小文字・ひらがな→カタカナ・空白と記号(TEXT_SEP TEXT_PUNCT)を消す"""
    return _NORM_DROP.sub("", hira_to_kata(unicodedata.normalize("NFKC", s).lower()))


def spaced(s: str) -> str:
    """英字の照合用: norm と同じく小文字にして記号を除くが、空白(と - _)は1つの空白で残す(「rhino prime armor」の区切りを見るため)"""
    s = _SPACED_DROP.sub("", unicodedata.normalize("NFKC", s).lower())
    return _SPACED_SEP.sub(" ", s).strip()


def fold_case(text: str) -> str:
    """全角/半角・大文字/小文字だけそろえる(NFKC + 小文字。記号・空白は残す。文の全文検索用)"""
    return unicodedata.normalize("NFKC", text).lower()


def fold_ocr(text: str) -> str:
    """読み違いに強い比較用の文字列: 空白・長音記号・中黒を消し、濁点・半濁点・小さいかな・似た漢字をそろえ、
    ひらがなはカタカナにする(英字は小文字)

    例: 「セ カ ン ダ ー リ」と「セカンダリ」、「工クストラ」と「エクストラ」、「クプロウ」と「クブロウ」、
        「パッドベイビ」と「バッド・ベイビー」、ひらがなの「べ」とカタカナの「ベ」は同じになる
    """
    text = _OCR_DROP.sub("", unicodedata.normalize("NFKC", text).lower())
    text = "".join(ch for ch in unicodedata.normalize("NFD", text) if ch not in "゙゚")
    return hira_to_kata(unicodedata.normalize("NFC", text).translate(_KANA_FOLD))


def ocr_key(s: str) -> str:
    """文字認識の照合用のキー: 大文字小文字・記号・空白を無視し、取り違えやすい文字(0/o, 1/l/i, 5/s)をそろえる。
    英数字に加えて、かな・漢字(日本語表示のアルケイン名)も残す。長音記号の揺れ(ー/－/-)もそろえる"""
    s = _OCR_DASH.sub("ー", unicodedata.normalize("NFKC", s).lower())
    return _OCR_KEY_DROP.sub("", s).translate(_CONFUSE)
