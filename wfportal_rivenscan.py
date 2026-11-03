#!/usr/bin/env python3
"""wfportal_rivenscan - Riven の画像(MOD 画面・ロール直後の画面)から、武器・ランク・効果の値を読み取る(標準ライブラリのみ)

流れ:
  1. 画像を Windows の文字認識(wfportal_ocr.run_ocr_bytes)にかけ、行ごとの文字を受け取る(API 側で行う)
  2. 行を上から見て、効果の行の範囲を決める
       - 始まり: 「+」「-」付きの数値で始まる行か、効果名(対コーパスダメージ など)で始まる行
       - 終わり: 「MR 16」の行(無ければ最後まで)
       - 始まりの手前の行(最大 RSCAN_TITLE_LINES 行)が名前(武器名 + Riven の名前)。その上の 10〜18 の数字がドレイン
  3. 範囲の行をつないで、値(+168.1% / -56.2% / x0.56)と効果名(data/riven/stat_words.json)を順に拾い、組にする
       - ふつうは「値 → 効果名」の順。日本語の勢力ダメージは「対コーパスダメージ:x0.56」で「効果名 → 値」の順
       - 括弧の中(弓は x2・ヘビー攻撃は 2 倍)は捨てる
       - x0.56 のような倍率は (倍率 - 1) x 100 の % にする(表示が小数2桁なので許容差は RSCAN_MUL_TOL)
  4. 名前の頭を武器の一覧(シミュレータ用データの英名)と照合する。いちばん長く一致した武器
  5. ドレイン(右上の数字)からランクを推定する: ランク = ドレイン - RSCAN_DRAIN_BASE(10〜18 のときだけ)

日本語・英語の文字認識の結果があれば両方を読み、効果を多く拾えたほうを使う(武器名は英語の結果を優先)。
グレードの計算は wfportal_builder.riven_grade。ここは読み取るだけ。
"""
from __future__ import annotations

import re
import unicodedata

import wfportal_ocr as ocr
from wfportal_builder import RIVEN_STAT_INDEX
from wfportal_msscan import fold

# --------------------------------------------------------------------------
# 定数(ゲームの表示が変わったら、ここを直す)
# --------------------------------------------------------------------------

RSCAN_TITLE_LINES = 3      # 効果の行の手前で、名前として見る行の数
RSCAN_DRAIN_BASE = 10      # Riven のドレインはランク 0 で 10、ランク 8 で 18
RSCAN_DRAIN_MAX = 18
RSCAN_MUL_TOL = 0.5        # 倍率(x0.56)から直した % の許容差(倍率が小数2桁で丸めてあるため)
RSCAN_END = re.compile(r"(?:^|\s)MR\s*\d|CONFIRM|確認", re.I)   # 効果の行の終わり(MR の行・ロール直後の確認ボタン)

# 符号の読み違い: 日本語の文字認識は「+」を「十」、「-」を「ー」「一」と読むことがある(数字の直前だけ直す)
_SIGN_FIX = [(re.compile(r"[十＋](?=\s*\d)"), "+"), (re.compile(r"[ー一−–—‐－](?=\s*\d)"), "-")]
_PAREN = re.compile(r"\([^()]*\)")
# 値: 符号付きの数値(% や単位は見ない) / 倍率(x0.56。小数点が必須。「x2」は弓などの注記なので拾わない)
_VALUE = re.compile(r"(?P<sign>[+-])\s*(?P<num>\d+(?:[.,]\d+)?)|(?<![a-z])[x×]\s*(?P<mul>\d+[.,]\d+)", re.I)
_DRAIN = re.compile(r"(?<!\d)(\d{2})(?!\d)")


class WordTable:
    """効果名の辞書(data/riven/stat_words.json)。照合は fold した文字で、位置ごとにいちばん長い語"""

    def __init__(self, raw: object):
        self.words: list[tuple[str, str]] = []   # (fold した語, 効果のキー)。長い順
        self.errors: list[str] = []
        stats = raw.get("stats") if isinstance(raw, dict) else None
        if not isinstance(stats, dict):
            self.errors.append("stats がありません")
            return
        seen: dict[str, str] = {}
        for key, langs in stats.items():
            if key not in RIVEN_STAT_INDEX:
                self.errors.append(f"知らない効果のキー: {key}")
                continue
            if not isinstance(langs, dict):
                self.errors.append(f"{key}: 形が違います")
                continue
            for lang_words in langs.values():
                for word in lang_words if isinstance(lang_words, list) else []:
                    k = fold(str(word))
                    if not k:
                        continue
                    if k in seen and seen[k] != key:
                        self.errors.append(f"同じ語が2つの効果にあります: {word}({seen[k]} / {key})")
                    seen[k] = key
        self.words = sorted(seen.items(), key=lambda kv: -len(kv[0]))

    def find(self, text: str) -> list[tuple[int, str, str]]:
        """fold した文字の中の効果名を左から拾う。[(位置, キー, 語)]"""
        out, i = [], 0
        while i < len(text):
            hit = next(((w, k) for w, k in self.words if text.startswith(w, i)), None)
            if hit:
                out.append((i, hit[1], hit[0]))
                i += len(hit[0])
            else:
                i += 1
        return out

    def starts(self, text: str) -> bool:
        t = fold(text)
        return any(t.startswith(w) for w, _ in self.words)


def clean(text: str) -> str:
    """行の文字をそろえる: NFKC(全角 -> 半角)・符号の読み違い・日本語の字の間の空白を消す"""
    s = unicodedata.normalize("NFKC", text)
    for pat, rep in _SIGN_FIX:
        s = pat.sub(rep, s)
    # 日本語の文字認識は1字ずつ空白で区切るので、英数字どうしの間以外の空白を消す
    s = re.sub(r"(?<=[^\x00-\x7f])\s+|\s+(?=[^\x00-\x7f])", "", s)
    return s.strip()


def _line_texts(result: dict) -> list[str]:
    return [clean(str(line.get("text") or "")) for line in result.get("lines") or []]


def _starts_value(line: str) -> bool:
    m = _VALUE.match(line)
    return bool(m and m.group("sign"))


def split_lines(lines: list[str], table: WordTable) -> tuple[list[str], list[str], list[str]]:
    """(名前より上の行, 名前の行, 効果の行)。効果の行が見つからなければ効果の行は空"""
    end = next((i for i, s in enumerate(lines) if RSCAN_END.search(s)), len(lines))
    start = next((i for i in range(end) if _starts_value(lines[i]) or table.starts(lines[i])), None)
    if start is None:
        return lines[:end], [], []
    top = max(0, start - RSCAN_TITLE_LINES)
    return lines[:top], lines[top:start], lines[start:end]


def parse_stats(stat_lines: list[str], table: WordTable) -> tuple[list[dict], list[str]]:
    """効果の行から [{key, value, tol, text}] と、組にできなかった文字の一覧"""
    text = _PAREN.sub(" ", " ".join(stat_lines))
    events: list[tuple[str, object, str]] = []   # ("value", (値, 許容差, 倍率か), 元の字) / ("word", キー, 元の字)
    pos = 0
    for m in _VALUE.finditer(text):
        for _, key, word in table.find(fold(text[pos:m.start()])):
            events.append(("word", key, word))
        if m.group("mul"):
            mul = float(m.group("mul").replace(",", "."))
            events.append(("value", ((mul - 1) * 100, RSCAN_MUL_TOL, True), m.group(0)))
        else:
            v = float(m.group("num").replace(",", "."))
            events.append(("value", (-v if m.group("sign") == "-" else v, None, False), m.group(0)))
        pos = m.end()
    for _, key, word in table.find(fold(text[pos:])):
        events.append(("word", key, word))

    stats, leftover = [], []
    pending_value, pending_word = None, None
    for kind, data, raw in events:
        if kind == "value":
            value, tol, is_mul = data
            if is_mul and pending_word:     # 「対コーパスダメージ:x0.56」(効果名が先)
                stats.append(_stat(pending_word[0], value, tol, pending_word[1] + " " + raw))
                pending_word = None
                continue
            if pending_value:
                leftover.append(pending_value[2])
            pending_value = (value, tol, raw)
        else:
            if pending_value:
                stats.append(_stat(data, pending_value[0], pending_value[1], pending_value[2] + " " + raw))
                pending_value = None
            else:
                if pending_word:
                    leftover.append(pending_word[1])
                pending_word = (data, raw)
    if pending_value:
        leftover.append(pending_value[2])
    if pending_word:
        leftover.append(pending_word[1])
    return stats, leftover


def _stat(key: str, value: float, tol: float | None, text: str) -> dict:
    out = {"key": key, "value": round(value, 4), "text": text}
    if tol is not None:
        out["tol"] = tol
    return out


def read_drain(lines: list[str]) -> int | None:
    """右上のドレインの数字(10〜18)。名前より上の行の短い行から探す"""
    for s in lines:
        if len(s) > 8:
            continue
        for m in _DRAIN.finditer(s):
            n = int(m.group(1))
            if RSCAN_DRAIN_BASE <= n <= RSCAN_DRAIN_MAX:
                return n
    return None


def match_weapon(title_lines: list[str], weapons: list[dict]) -> dict | None:
    """名前の行の頭(どの行から始めてもよい)にいちばん長く一致する武器。Riven の名前は英名なので英名で引く"""
    keys = sorted(((ocr.name_key(w["en"]), w) for w in weapons if w.get("en")), key=lambda kw: -len(kw[0]))
    best = None
    for j in range(len(title_lines)):
        head = ocr.name_key(" ".join(title_lines[j:]))
        hit = next(((k, w) for k, w in keys if k and head.startswith(k)), None)
        if hit and (best is None or len(hit[0]) > len(best[0])):
            best = hit
    return best[1] if best else None


def parse_result(result: dict, table: WordTable, weapons: list[dict]) -> dict:
    lines = _line_texts(result)
    above, title, stat_lines = split_lines(lines, table)
    stats, leftover = parse_stats(stat_lines, table)
    drain = read_drain(above + title)
    weapon = match_weapon(title, weapons) if title else None
    return {"lang": result.get("lang"), "title": " ".join(title), "weapon": weapon, "drain": drain,
            "stats": stats, "unknown": leftover, "lines": stat_lines}


def parse_riven(ocr_data: dict, table: WordTable, weapons: list[dict]) -> dict:
    """文字認識の結果(winocr.ps1 の JSON)から Riven を読む。効果を多く拾えた言語の結果を使い、武器・ドレインは
    無ければほかの言語の結果で補う(英語を優先)。

    返り値: {weapon: {en, ja, cat} | None, title, rank(推定。無ければ None), drain, stats: [{key, value, tol?, text}],
             unknown: [組にできなかった字], lang}"""
    parsed = [parse_result(r, table, weapons) for r in ocr_data.get("results") or []]
    if not parsed:
        return {"weapon": None, "title": "", "rank": None, "drain": None, "stats": [], "unknown": [], "lang": None}
    best = max(parsed, key=lambda p: (len(p["stats"]), -len(p["unknown"])))
    order = sorted(parsed, key=lambda p: 0 if str(p["lang"] or "").startswith("en") else 1)
    weapon = next((p["weapon"] for p in order if p["weapon"]), None)
    title = next((p["title"] for p in order if p["weapon"]), best["title"])
    drain = best["drain"] or next((p["drain"] for p in order if p["drain"]), None)
    return {"weapon": {"en": weapon["en"], "ja": weapon.get("ja") or weapon["en"], "cat": weapon.get("cat")} if weapon else None,
            "title": title, "drain": drain, "rank": drain - RSCAN_DRAIN_BASE if drain else None,
            "stats": best["stats"], "unknown": best["unknown"], "lang": best["lang"]}
