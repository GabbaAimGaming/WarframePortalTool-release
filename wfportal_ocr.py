#!/usr/bin/env python3
"""wfportal_ocr - ビルド画像の自動解析 (Windows 標準の文字認識 + 名前一覧との照合 / 標準ライブラリのみ)

流れ:
  1. ocr/winocr.ps1 で Windows.Media.Ocr を呼び、文字と位置(行・単語ごとの枠)を JSON で受け取る
  2. 読み取った文字を、公式の名前一覧(MOD・アルケイン・フレーム/武器)と照合して読み間違いを補正する
       - 単語の並びを少しずつずらして候補を作る(長い MOD 名が2行に折り返す場合も1つにまとめる)
  3. 結果から次を求める
       - 対象(フレーム・武器): 名前一覧に一致する中で、いちばん大きい文字
       - MOD: 画面上の並び(上の段から、左から順)
       - フォーマ数: 画面に「フォーマ 3」などの表示があればその値。無ければ、各 MOD カードのドレイン(消費
         キャパシティ)から極性が一致しているスロットを数えて推定する(一致すると消費が半分になるため)

Windows 以外や文字認識が使えない環境では OcrUnavailable を送出する。解析(2〜3)は OCR の結果(JSON)
さえあればどこでも動くので、テストや不具合報告の再現に使える。
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

from wfp.core.common import BUILD_TYPES, POLARITY_EN, TextError, txt
from wfp.core.loader import load_names
from wfp.core.names import Names
from wfp.store import build_images

HERE = Path(__file__).resolve().parent
PS_SCRIPT = HERE / "ocr" / "winocr.ps1"
DEFAULT_LANGS = "en-US,ja-JP"  # MOD 名は英語、「フォーマ」などの表示は日本語の場合がある


class OcrUnavailable(TextError):
    """文字認識が使えない・失敗した。文はテキスト指定(画面は表示中の言語、CLI は日本語)"""


# --------------------------------------------------------------------------
# 1. Windows の文字認識を呼ぶ
# --------------------------------------------------------------------------

def find_powershell() -> str | None:
    """Windows PowerShell 5.1 (powershell.exe)。PowerShell 7 (pwsh) は WinRT を読めないので使わない"""
    if os.name != "nt":
        return None
    root = os.environ.get("SystemRoot", r"C:\Windows")
    p = Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(p) if p.exists() else shutil.which("powershell.exe")


def _run_ps(args: list[str], timeout: int) -> dict:
    fake = os.environ.get("WFPORTAL_OCR_FAKE")  # テスト用: 保存した OCR 結果(JSON)を返す
    if fake:
        data = json.loads(Path(fake).read_text(encoding="utf-8-sig"))
        data = data[0] if isinstance(data, list) else data
        return {"available": [r.get("lang") for r in data.get("results", [])]} if "-ListLanguages" in args else data
    ps = find_powershell()
    if not ps:
        raise OcrUnavailable(txt("err.ocr.windows"))
    if not PS_SCRIPT.exists():
        raise OcrUnavailable(txt("err.ocr.script", path=str(PS_SCRIPT)))
    fd, out = tempfile.mkstemp(suffix=".json", prefix="wfocr_")
    os.close(fd)
    try:
        cmd = [ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(PS_SCRIPT), "-Out", out, *args]
        flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW: 黒い画面を出さない
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=flags)
        except subprocess.TimeoutExpired:
            raise OcrUnavailable(txt("err.ocr.timeout", sec=str(timeout)))
        text = Path(out).read_text(encoding="utf-8-sig") if Path(out).stat().st_size else ""
        data = json.loads(text) if text else {}
        if proc.returncode != 0 or "error" in data:
            msg = data.get("error") or proc.stderr.decode("utf-8", "replace").strip() or f"exit {proc.returncode}"
            raise OcrUnavailable(txt("err.ocr.failed", msg=msg))
        return data
    finally:
        try:
            os.unlink(out)
        except OSError:
            pass


def ocr_languages(timeout: int = 30) -> list[str]:
    return _run_ps(["-ListLanguages"], timeout).get("available") or []


def run_ocr(image: Path, langs: str = DEFAULT_LANGS, scale: float = 2.0, timeout: int = 120) -> dict:
    return _run_ps(["-Image", str(image), "-Langs", langs, "-Scale", str(scale)], timeout)


def run_ocr_bytes(data: bytes, cache_dir: Path | None = None, **kw) -> dict:
    """画像のバイト列を文字認識する。cache_dir を渡すと同じ画像の結果を使い回す"""
    digest = hashlib.sha1(data).hexdigest()
    cached = cache_dir / f"{digest}.json" if cache_dir else None
    if cached and cached.exists():
        try:
            return json.loads(cached.read_text(encoding="utf-8"))
        except ValueError:
            pass
    ext = build_images.image_ext(data) or "png"
    fd, tmp = tempfile.mkstemp(suffix=f".{ext}", prefix="wfimg_")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        result = run_ocr(Path(tmp), **kw)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    if cached:
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


# --------------------------------------------------------------------------
# 2. 名前一覧との照合
# --------------------------------------------------------------------------

_CONFUSE = str.maketrans({"0": "o", "1": "l", "i": "l", "|": "l", "5": "s", "8": "b", "$": "s"})


def name_key(s: str) -> str:
    """照合用のキー: 大文字小文字・記号・空白を無視し、OCR で取り違えやすい文字(0/o, 1/l/i, 5/s)をそろえる"""
    s = unicodedata.normalize("NFKC", s).lower()
    # 英数字に加えて、かな・漢字(日本語表示のアルケイン名)も残す。長音記号の揺れ(ー/－/-)もそろえる
    s = re.sub(r"[\-‐－―]", "ー", s)
    return re.sub(r"[^a-z0-9&\u3040-\u30ff\u4e00-\u9fff]", "", s).translate(_CONFUSE)


class NameMatcher:
    """名前一覧に対するあいまい一致。長さの近い候補だけを比べるので 1000 件程度なら十分速い"""

    def __init__(self, entries: list[tuple[str, str, object]]):  # (種類, 名前, 付随情報)
        self.exact: dict[str, tuple] = {}
        self.by_len: dict[int, list[tuple]] = {}
        for kind, name, info in entries:
            k = name_key(name)
            if len(k) < 3 or k in self.exact:
                continue
            self.exact[k] = (kind, name, info)
            self.by_len.setdefault(len(k), []).append((k, kind, name, info))

    @staticmethod
    def threshold(n: int) -> float:
        return 1.01 if n <= 4 else 0.9 if n <= 7 else 0.86  # 短い名前は完全一致のみ

    def match(self, text: str):
        k = name_key(text)
        if len(k) < 3:
            return None
        if k in self.exact:
            kind, name, info = self.exact[k]
            return 1.0, kind, name, info, k
        need = self.threshold(len(k))
        if need > 1:
            return None
        sm = SequenceMatcher(autojunk=False)
        sm.set_seq2(k)
        best = None
        for n in range(int(len(k) * 0.8), int(len(k) * 1.25) + 2):
            for kk, kind, name, info in self.by_len.get(n, ()):
                sm.set_seq1(kk)
                if sm.real_quick_ratio() < need or sm.quick_ratio() < need:
                    continue
                r = sm.ratio()
                if r >= need and (best is None or r > best[0]):
                    best = (r, kind, name, info, kk)
        return best


def build_matcher(names: Names) -> NameMatcher:
    entries = [("mod", m["en"], m) for m in names.mods]
    entries += [("arcane", a, None) for a in names.arcanes]
    entries += [("item", it["en"], it) for it in names.items]
    m = NameMatcher(entries)
    # 日本語版ではアルケイン名だけ日本語で表示される(例: アルケイン エナージャイズ)。日本語の読み取り結果と照合する
    m.ja = NameMatcher([("arcane", names.ja(a), a) for a in names.arcanes if names.ja(a) != a])
    return m


# --------------------------------------------------------------------------
# 3. 解析
# --------------------------------------------------------------------------

def _box(words: list[dict]) -> tuple[float, float, float, float]:
    x0 = min(w["x"] for w in words)
    y0 = min(w["y"] for w in words)
    x1 = max(w["x"] + w["w"] for w in words)
    y1 = max(w["y"] + w["h"] for w in words)
    return x0, y0, x1 - x0, y1 - y0


def _median(v: list[float], default: float = 10.0) -> float:
    v = sorted(v)
    return v[len(v) // 2] if v else default


def _split_slash(w: dict) -> list[dict]:
    """「アップグレード/NOVA」のように / でつながった単語を分ける(位置は文字数で按分)"""
    t = w["text"]
    if "/" not in t.strip("/"):
        return [w]
    parts, out, pos = t.split("/"), [], 0
    per = w["w"] / max(len(t), 1)
    for part in parts:
        if part.strip():
            out.append({**w, "text": part, "x": w["x"] + pos * per, "w": len(part) * per})
        pos += len(part) + 1
    return out


def _segments(lines: list[dict]) -> list[list[dict]]:
    """1行の中でも大きく離れた単語は別の塊にする(となりの MOD カードの名前が同じ行に並ぶため)"""
    segs = []
    for line in lines:
        words = sorted((p for w in line.get("words", []) if w.get("text", "").strip() for p in _split_slash(w)), key=lambda w: w["x"])
        if not words:
            continue
        h = _median([w["h"] for w in words])
        cur = [words[0]]
        for w in words[1:]:
            gap = w["x"] - (cur[-1]["x"] + cur[-1]["w"])
            if gap > 1.1 * h:
                segs.append(cur)
                cur = [w]
            else:
                cur.append(w)
        segs.append(cur)
    return segs


def _candidates(segs: list[list[dict]]):
    """照合する候補: 各塊の連続する単語(最大6語)と、真下に折り返した2行の組み合わせ"""
    for si, seg in enumerate(segs):
        for i in range(len(seg)):
            for j in range(i + 1, min(len(seg), i + 6) + 1):
                ws = seg[i:j]
                yield " ".join(w["text"] for w in ws), ws
    boxes = [_box(s) for s in segs]
    for a, (ax, ay, aw, ah) in enumerate(boxes):
        for b, (bx, by, bw, bh) in enumerate(boxes):
            if a == b or not (0.7 < bh / max(ah, 1) < 1.4):
                continue
            gap = by - (ay + ah)
            if -0.3 * ah <= gap <= 1.0 * ah and abs((ax + aw / 2) - (bx + bw / 2)) < 0.6 * max(aw, bw):
                ws = segs[a] + segs[b]
                yield " ".join(w["text"] for w in ws), ws


_DIGIT_FIX = str.maketrans({"O": "0", "o": "0", "D": "0", "l": "1", "I": "1", "|": "1", "S": "5", "B": "8"})


def _number(text: str) -> int | None:
    """1〜2 桁の数字。ドレイン表示の "^14" "7—" "8Y" のように、極性の記号がくっついていても読む"""
    t = text.strip()
    m = re.fullmatch(r"[^\w]{0,2}([0-9OoDlI|SB]{1,2})[^\d]{0,2}", t)
    if not m:
        return None
    d = m.group(1).translate(_DIGIT_FIX)
    return int(d) if d.isdigit() else None


def _inventory_top(results: list[dict]) -> float | None:
    """画面下半分の「所持 MOD 一覧」の始まり(検索欄の位置)。これより下の MOD はビルドに含めない"""
    ys = []
    for r in results:
        for line in r.get("lines") or []:
            text = line.get("text", "").replace(" ", "")
            if (text.startswith("検索") or re.match(r"(?i)^search", text)) and line.get("words"):
                ys.append(_box(line["words"])[1])
    return min(ys) if ys else None


_RANK_RE = re.compile(r"^[\[(|lI]?\s*([0-9OoDlI]{1,2})\s*[\])|lI1]?$")


def read_header_forma(results: list[dict], anchor: tuple | None) -> dict | None:
    """画面上部「アップグレード/NOVA PRIME [30] (アイコン) (アイコン) 6」の最後の数字(フォーマ数)を読む。

    anchor: 装備名の枠 (x, y, w, h)。無ければ「アップグレード / UPGRADE」の行を探す。
    装備名の右側・同じ高さにある文字を左から見て、ランク([30] など)の次に来る 1〜2 桁の数字を採る。
    右上の所持金(48,012,058 など)はカンマ付き・桁が多いので拾わない。
    """
    if anchor is None:
        for r in results:
            for line in r.get("lines") or []:
                ws = line.get("words") or []
                for i, w in enumerate(ws):
                    if "アップグレード" in w.get("text", "") or re.search(r"(?i)upgrade", w.get("text", "")):
                        x, y, ww, hh = _box(ws)
                        anchor = (w["x"], y, w["w"], hh)
                        break
                if anchor:
                    break
            if anchor:
                break
    if anchor is None:
        return None
    ax, ay, aw, ah = anchor
    cy = ay + ah / 2
    for r in results:
        row = []
        for line in r.get("lines") or []:
            for w in line.get("words") or []:
                wcy = w["y"] + w["h"] / 2
                if abs(wcy - cy) <= 0.6 * ah and w["x"] >= ax + aw - 0.2 * ah:
                    row.append(w)
        row.sort(key=lambda w: w["x"])
        rank_end = None
        for w in row:
            t = w["text"].replace(" ", "")
            if rank_end is None:
                # "[30]" が "[", "30", "]" に分かれることもある
                m = _RANK_RE.match(t)
                if m and m.group(1).translate(_DIGIT_FIX).isdigit() and 0 <= int(m.group(1).translate(_DIGIT_FIX)) <= 40:
                    rank_end = w["x"] + w["w"]
                    rank = int(m.group(1).translate(_DIGIT_FIX))
                continue
            if t in ("]", ")", "|"):
                rank_end = w["x"] + w["w"]
                continue
            if w["x"] - rank_end > 8 * ah:
                break  # 離れすぎ(右上の所持金など)
            if "," in t or len(re.sub(r"\D", "", t)) > 2:
                break
            n = _number(t) if len(t) <= 4 else None
            if n is not None:
                return {"value": n, "rank": rank, "read": t, "lang": r.get("lang")}
    return None


def _drain_status(m: dict, shown: int) -> str | None:
    """MOD が最大ランクとして、表示されたドレインからスロットの極性の状態を判定する"""
    base, rank = m.get("drain"), m.get("max_rank")
    if base is None or rank is None or m.get("type") in ("AURA", "STANCE"):
        return None  # オーラ・スタンスはキャパシティを増やす側なので判定しない
    full = int(base) + int(rank)
    if full <= 0:
        return None
    half = math.floor(full / 2 + 0.5)
    more = math.floor(full * 1.25 + 0.5)
    if shown == half:
        return "match"
    if shown == full:
        return "neutral"
    if shown == more:
        return "mismatch"
    return None


FORMA_PATTERNS = [
    r"フォーマ\s*[x×:：]?\s*(\d{1,2})", r"(\d{1,2})\s*[x×]?\s*回?\s*フォーマ",
    r"forma(?:ed)?\s*[x×:]?\s*(\d{1,2})", r"(\d{1,2})\s*[x×]\s*forma", r"polari[sz]ed\s*[x×:]?\s*(\d{1,2})",
]


def analyze(ocr: dict, names: Names, matcher: NameMatcher | None = None) -> dict:
    """OCR の結果(winocr.ps1 の JSON)から、対象・MOD・フォーマ数を求める"""
    matcher = matcher or build_matcher(names)
    results = ocr.get("results") or []
    # 英語の結果で名前を照合する(無ければ最初の言語)
    main = next((r for r in results if str(r.get("lang", "")).startswith("en")), results[0] if results else {"lines": []})
    lines = main.get("lines") or []
    for i, line in enumerate(lines):
        for j, w in enumerate(line.get("words", [])):
            w["_id"] = (i, j)
    segs = _segments(lines)

    found = []
    for text, ws in _candidates(segs):
        hit = matcher.match(text)
        if hit:
            score, kind, name, info, key = hit
            found.append({"kind": kind, "name": name, "info": info, "score": score, "text": text,
                          "ids": {w["_id"] for w in ws}, "box": _box(ws), "weight": len(key) * score ** 4})
    # 日本語の読み取り結果からアルケイン名を探す
    ja_matcher = getattr(matcher, "ja", None)
    ja_res = next((r for r in results if str(r.get("lang", "")).startswith("ja")), None)
    if ja_matcher and ja_res and ja_res is not main:
        for i, line in enumerate(ja_res.get("lines") or []):
            for j, w in enumerate(line.get("words", [])):
                w["_id"] = ("ja", i, j)
        for text, ws in _candidates(_segments(ja_res.get("lines") or [])):
            hit = ja_matcher.match(text)
            if hit:
                score, kind, _ja, en_name, key = hit
                found.append({"kind": "arcane", "name": en_name, "info": None, "score": score, "text": text,
                              "ids": {w["_id"] for w in ws}, "box": _box(ws), "weight": len(key) * score ** 4})
    # 重なる候補は「長い名前 × 一致度」の大きい方を採る(例: "Primed Continuity" と "Continuity")
    found.sort(key=lambda f: -f["weight"])
    used: set = set()
    picked, arc_seen = [], set()
    for f in found:
        if f["ids"] & used:
            continue
        if f["kind"] == "arcane":  # 英語と日本語の両方で読めた場合は1つにまとめる
            if f["name"].lower() in arc_seen:
                continue
            arc_seen.add(f["name"].lower())
        used |= f["ids"]
        picked.append(f)
    # 画面下半分の所持 MOD 一覧(検索欄より下)は、装備中の MOD ではないので除く
    inv_top = _inventory_top(results)
    if inv_top is not None:
        picked = [f for f in picked if f["kind"] == "item" or f["box"][1] < inv_top - 2]

    # 対象: 名前一覧の装備に一致する中で、いちばん大きい文字
    items = [f for f in picked if f["kind"] == "item"]
    target = max(items, key=lambda f: (f["box"][3] * (0.5 + f["score"] / 2), f["score"]), default=None)

    # MOD・アルケイン: 上の段から、左から順に並べる
    mods = [f for f in picked if f["kind"] in ("mod", "arcane")]
    h = _median([f["box"][3] for f in mods])
    mods.sort(key=lambda f: f["box"][1] + f["box"][3] / 2)
    rows, row_y = [], None
    for f in mods:
        cy = f["box"][1] + f["box"][3] / 2
        if row_y is None or cy - row_y > 2.5 * h:
            rows.append([])
            row_y = cy
        rows[-1].append(f)
    mods = [f for row in rows for f in sorted(row, key=lambda f: f["box"][0])]

    # ドレイン(カード右上の数字)を各 MOD に対応づける: 名前の上側・近くにある 1〜2 桁の数字
    numbers = []
    for line in lines:
        for w in line.get("words", []):
            n = _number(w.get("text", ""))
            if n is not None and 0 < n <= 30 and w["_id"] not in used:
                numbers.append((n, w))
    # カードの幅と段の間隔は、となり合う MOD 名の間隔から見積もる(画面の解像度によらないように)
    cxs = lambda row: sorted(f["box"][0] + f["box"][2] / 2 for f in row if f["kind"] == "mod")
    pitch_x = _median([b - a for row in rows for a, b in zip(cxs(row), cxs(row)[1:])], 16 * h)
    row_cy = [_median([f["box"][1] + f["box"][3] / 2 for f in row]) for row in rows]
    pitch_y = _median([b - a for a, b in zip(row_cy, row_cy[1:])], 12 * h)
    taken = set()
    for f in sorted(mods, key=lambda f: -f["score"]):
        if f["kind"] != "mod":
            continue
        x, y, w_, h_ = f["box"]
        cx, cy = x + w_ / 2, y + h_ / 2
        best = None
        for n, w in numbers:
            if w["_id"] in taken:
                continue
            dx = (w["x"] + w["w"] / 2) - cx
            dy = (w["y"] + w["h"] / 2) - cy
            # 自分のカードの範囲(左右はカード幅の6割、上は段の間隔の9割まで)にある数字だけを見る
            if abs(dx) > 0.6 * pitch_x or not (-0.9 * pitch_y <= dy <= 0.5 * h_):
                continue
            d = math.hypot(dx / pitch_x, dy / pitch_y)
            if best is None or d < best[0]:
                best = (d, n, w)
        if best:
            taken.add(best[2]["_id"])
            f["drain"] = best[1]
            f["slot"] = _drain_status(f["info"], best[1])

    out_mods = []
    for f in mods:
        m = f["info"] or {}
        pol = m.get("polarity", "")
        out_mods.append({
            "en": f["name"], "ja": names.ja(f["name"]), "kind": f["kind"], "score": round(f["score"], 3),
            "read": f["text"], "type": m.get("type", ""), "polarity": POLARITY_EN.get(pol, pol) if pol else "",
            "drain": f.get("drain"), "slot": f.get("slot"),
        })

    # フォーマ数: 画面上部の「装備名 [ランク] (アイコン) 数字」 -> 「フォーマ 3」などの表示 -> ドレインから推定
    forma = {"value": None, "source": None, "estimate": None, "polarized": []}
    head = read_header_forma(results, target["box"] if target else None)
    if head:
        forma.update(value=head["value"], source="display", read=head["read"], rank=head["rank"])
    all_text = " ".join(l.get("text", "") for r in results for l in (r.get("lines") or []))
    for pat in ([] if head else FORMA_PATTERNS):
        mt = re.search(pat, all_text, flags=re.I)
        if mt and 0 <= int(mt.group(1)) <= 40:
            forma.update(value=int(mt.group(1)), source="display", read=mt.group(0))
            break
    polarized = [m["polarity"] for m in out_mods if m["slot"] == "match" and m["polarity"]]
    judged = [m for m in out_mods if m["slot"]]
    if judged:
        forma["estimate"] = len(polarized)
        forma["polarized"] = polarized
        if forma["value"] is None:
            forma.update(value=len(polarized), source="estimate")

    return {
        "target": {"en": target["name"], "ja": names.ja(target["name"]), "type": (target["info"] or {}).get("type", "other"),
                   "score": round(target["score"], 3), "read": target["text"]} if target else None,
        "mods": out_mods, "forma": forma,
        "lines": [l.get("text", "") for l in lines],
        "langs": [r.get("lang") for r in results],
    }


def merge(analyses: list[dict]) -> dict:
    """複数の画像(MOD 画面とアルケイン画面など)の結果をまとめる"""
    targets = [a["target"] for a in analyses if a.get("target")]
    target = max(targets, key=lambda t: t["score"], default=None)
    mods, seen = [], set()
    for a in analyses:
        for m in a.get("mods", []):
            if m["en"].lower() not in seen:
                seen.add(m["en"].lower())
                mods.append(m)
    shown = [a["forma"]["value"] for a in analyses if a["forma"].get("source") == "display"]
    polarized = [p for m in mods if m["slot"] == "match" and m["polarity"] for p in [m["polarity"]]]
    judged = any(m["slot"] for m in mods)
    if shown:
        disp = max((a for a in analyses if a["forma"].get("source") == "display"), key=lambda a: a["forma"]["value"])
        forma = {"value": max(shown), "source": "display", "rank": disp["forma"].get("rank"),
                 "estimate": len(polarized) if judged else None, "polarized": polarized}
    elif judged:
        forma = {"value": len(polarized), "source": "estimate", "estimate": len(polarized), "polarized": polarized}
    else:
        forma = {"value": None, "source": None, "estimate": None, "polarized": []}
    return {"target": target, "mods": mods, "forma": forma, "images": len(analyses)}


def polarity_summary(polarized: list[str]) -> str:
    counts: dict[str, int] = {}
    for p in polarized:
        counts[p] = counts.get(p, 0) + 1
    return ", ".join(f"{p}×{n}" for p, n in sorted(counts.items(), key=lambda x: (-x[1], x[0])))


# --------------------------------------------------------------------------
# コマンドライン: python wfportal.py build analyze 画像 ... から呼ばれる
# --------------------------------------------------------------------------

def print_analysis(r: dict) -> None:
    t = r.get("target")
    print(f"対象   : {t['ja']} ({t['en']}) [{BUILD_TYPES.get(t['type'], t['type'])}] 一致度 {t['score']:.0%}" if t else "対象   : 読み取れませんでした")
    f = r["forma"]
    if f["value"] is None:
        print("フォーマ: 読み取れませんでした")
    else:
        how = (f"ゲーム内の表示: 装備名 [{f['rank']}] の後ろの数字" if f.get("rank") is not None else "ゲーム内の表示") \
            if f["source"] == "display" else "推定(極性が一致しているスロットの数)"
        print(f"フォーマ: {f['value']}  ({how})")
    if f.get("polarized"):
        print(f"極性    : {polarity_summary(f['polarized'])}  (MOD が最大ランクの前提で、ドレインから判定)")
    arcs = [m for m in r["mods"] if m["kind"] == "arcane"]
    if arcs:
        print("アルケイン: " + ", ".join(m["en"] for m in arcs))
    print(f"MOD    : {len(r['mods']) - len(arcs)} 件")
    mark = {"match": "極性一致", "neutral": "極性なし", "mismatch": "極性不一致"}
    for i, m in enumerate([m for m in r["mods"] if m["kind"] != "arcane"], 1):
        extra = [m["polarity"]] if m["polarity"] else []
        if m.get("drain") is not None:
            extra.append(f"ドレイン {m['drain']}" + (f" = {mark[m['slot']]}" if m.get("slot") else ""))
        if m["score"] < 1:
            extra.append(f"一致度 {m['score']:.0%} / 読み取り「{m['read']}」")
        print(f"  {i:>2}. {m['ja']}" + (f"  ({' / '.join(extra)})" if extra else ""))


def main_analyze(paths: list[str], data_dir: Path, raw: bool = False, save_ocr: str | None = None, ocr_json: str | None = None) -> None:
    names = load_names(data_dir)
    if not names.mods:
        sys.exit("MOD の情報がありません。先に `python wfportal.py update` を実行してください。")
    matcher = build_matcher(names)
    analyses, dumps = [], []
    sources = [("json", p) for p in ([ocr_json] if ocr_json else [])] + [("img", p) for p in paths]
    if not sources:
        sys.exit("画像ファイルを指定してください。")
    for kind, p in sources:
        try:
            if kind == "json":
                ocr = json.loads(Path(p).read_text(encoding="utf-8-sig"))
                ocr = ocr if isinstance(ocr, list) else [ocr]
            else:
                ocr = [run_ocr(Path(p).expanduser())]
        except OcrUnavailable as e:
            sys.exit(str(e))
        except (OSError, ValueError) as e:
            sys.exit(f"{p} を読めませんでした: {e}")
        for o in ocr:
            dumps.append(o)
            if raw:
                for r in o.get("results", []):
                    print(f"--- {p} [{r.get('lang')}] ---")
                    for line in r.get("lines", []):
                        print("  " + line.get("text", ""))
            analyses.append(analyze(o, names, matcher))
    if save_ocr:
        Path(save_ocr).write_text(json.dumps(dumps, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"OCR の結果を保存しました: {save_ocr}")
    if not names.items:
        print("※ 装備名の一覧がありません。「データ更新」を実行すると、フレーム・武器名も読み取れるようになります。")
    print_analysis(merge(analyses) if len(analyses) > 1 else {**analyses[0], "images": 1})
