"""取得したデータの解析(JSON の揺れ・JavaScript 形式・lzma 展開)"""
from __future__ import annotations

import json
import lzma
import re


def parse_export_json(text: str) -> dict:
    """Public Export は文字列内に生の改行/制御文字を含むため、緩く読む。"""
    return json.loads(text.replace("\r", "").replace("\n", ""), strict=False)


def parse_json_bytes(raw: bytes):
    """先頭の BOM や文字コードの違いを吸収して JSON を読む。

    公式の weeklyRivensPC.json は名前に反して JSON ではなく、JavaScript の書き方
    (キーに引用符なし・文字列が '...')なので、JSON として読めなければ parse_js_literal で読む。
    """
    text = raw.decode("utf-8-sig", "replace")
    try:
        return json.loads(text)
    except ValueError as e:
        try:
            return parse_js_literal(text)
        except ValueError:
            raise e from None


def parse_js_literal(text: str):
    """JavaScript のデータの書き方(オブジェクト・配列・文字列・数値・true/false/null)を読む。

    eval は使わず、データとして許す書き方だけを1文字ずつ解釈する。対応するもの:
    引用符なしのキー / '...' と "..." の文字列 / 末尾の余分なカンマ / // と /* */ のコメント /
    undefined・NaN・Infinity (null として扱う)
    """
    n, i = len(text), 0
    esc = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0", "/": "/", "\\": "\\", "'": "'", '"': '"'}

    def err(msg):
        line = text.count("\n", 0, i) + 1
        return ValueError(f"{msg} (行 {line}, {i} 文字目)")

    def skip():
        nonlocal i
        while i < n:
            c = text[i]
            if c in " \t\r\n﻿":
                i += 1
            elif text.startswith("//", i):
                j = text.find("\n", i)
                i = n if j < 0 else j + 1
            elif text.startswith("/*", i):
                j = text.find("*/", i + 2)
                if j < 0:
                    raise err("コメントが閉じていません")
                i = j + 2
            else:
                break

    def string():
        nonlocal i
        q = text[i]
        i += 1
        out = []
        while i < n:
            c = text[i]
            if c == q:
                i += 1
                return "".join(out)
            if c == "\\":
                i += 1
                if i >= n:
                    break
                c = text[i]
                if c == "u":
                    out.append(chr(int(text[i + 1:i + 5], 16)))
                    i += 5
                    continue
                if c == "x":
                    out.append(chr(int(text[i + 1:i + 3], 16)))
                    i += 3
                    continue
                if c == "\n":  # 行の継続
                    i += 1
                    continue
                out.append(esc.get(c, c))
                i += 1
                continue
            out.append(c)
            i += 1
        raise err("文字列が閉じていません")

    def word():
        nonlocal i
        m = re.compile(r"[A-Za-z_$][\w$]*|[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?|[+-]?Infinity").match(text, i)
        if not m:
            raise err("読めない文字があります")
        i = m.end()
        return m.group(0)

    def value():
        nonlocal i
        skip()
        if i >= n:
            raise err("データが途中で終わっています")
        c = text[i]
        if c == "{":
            i += 1
            obj = {}
            while True:
                skip()
                if i < n and text[i] == "}":
                    i += 1
                    return obj
                key = string() if text[i] in "'\"" else word()
                skip()
                if i >= n or text[i] != ":":
                    raise err("':' がありません")
                i += 1
                obj[key] = value()
                skip()
                if i < n and text[i] == ",":
                    i += 1
                elif i < n and text[i] == "}":
                    continue
                else:
                    raise err("',' か '}' がありません")
        if c == "[":
            i += 1
            arr = []
            while True:
                skip()
                if i < n and text[i] == "]":
                    i += 1
                    return arr
                arr.append(value())
                skip()
                if i < n and text[i] == ",":
                    i += 1
                elif i < n and text[i] == "]":
                    continue
                else:
                    raise err("',' か ']' がありません")
        if c in "'\"":
            return string()
        w = word()
        if w in ("true", "false"):
            return w == "true"
        if w in ("null", "undefined", "NaN") or w.lstrip("+-") == "Infinity":
            return None
        try:
            return float(w) if any(ch in w for ch in ".eE") else int(w)
        except ValueError:
            raise err(f"読めない値です: {w}")

    result = value()
    skip()
    if i < n:
        raise err("データの後ろに余分な文字があります")
    return result


def decompress_lzma_alone(raw: bytes) -> bytes:
    """旧形式 .lzma (LZMA_Alone) を展開する。

    公式の index_*.txt.lzma は「ヘッダーに展開後サイズあり」かつ「終端マーカーあり」の形式で、
    Windows 版 Python に同梱される古い liblzma (5.4 未満) では lzma.decompress が
    "Corrupt input data" で失敗する。そのため 13 バイトのヘッダーを自前で読み、
    本体を RAW 形式の LZMA1 として展開する(RAW は終端マーカーの有無を問わない)。
    """
    if len(raw) < 13:
        raise lzma.LZMAError("LZMA データが短すぎます")
    props, dict_size = raw[0], int.from_bytes(raw[1:5], "little")
    size = int.from_bytes(raw[5:13], "little")
    if props >= 9 * 5 * 5:
        raise lzma.LZMAError("LZMA ヘッダーが不正です")
    pb, rest = divmod(props, 45)
    lp, lc = divmod(rest, 9)
    filt = {"id": lzma.FILTER_LZMA1, "dict_size": max(dict_size, 4096), "lc": lc, "lp": lp, "pb": pb}
    dec = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=[filt])
    out = dec.decompress(raw[13:])
    if size != 0xFFFF_FFFF_FFFF_FFFF:  # サイズが書かれていれば、それ以降(余分なデータ)は捨てる
        if len(out) < size:
            raise lzma.LZMAError(f"展開結果が不足しています ({len(out)} / {size} バイト)")
        out = out[:size]
    return out


def decompress_lzma(raw: bytes) -> bytes:
    try:
        return lzma.decompress(raw)
    except lzma.LZMAError:
        return decompress_lzma_alone(raw)
