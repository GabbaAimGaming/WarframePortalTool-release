"""公式 Public Export の取得と名前辞書の作成"""
from __future__ import annotations

from wfp.core.common import EXPORT_BASE, EXPORT_GITHUB, EXPORT_PREFIXES
from wfp.core.names import names_from_exports
from wfp.fetch import decode, net


def fetch_export(lang: str) -> list[dict]:
    """公式サイトから直接取得する(予備)。"""
    raw = net.http_get(f"{EXPORT_BASE}/index_{lang}.txt.lzma")
    text = decode.decompress_lzma(raw).decode("utf-8", "replace")
    docs = []
    for line in text.splitlines():
        if line.startswith(EXPORT_PREFIXES):
            print(f"  取得: {line.split('!')[0]}")
            docs.append(decode.parse_export_json(net.http_get(f"{EXPORT_BASE}/Manifest/{line}").decode("utf-8", "replace")))
    return docs


def fetch_export_github(lang: str) -> list[dict]:
    """calamity-inc/warframe-public-export (展開済み JSON) から取得する。"""
    docs = []
    for prefix in EXPORT_PREFIXES:
        print(f"  取得: {prefix}_{lang}.json")
        docs.append(decode.parse_export_json(net.http_get(f"{EXPORT_GITHUB}/{prefix}_{lang}.json", timeout=120).decode("utf-8", "replace")))
    return docs


def fetch_names(docs_out: dict | None = None) -> dict:
    """名前辞書を作る。docs_out を渡すと、取得した Export (en / ja) と取得元をそこに入れる(シミュレータ用データに使う)"""
    errors = []
    for label, fetch in (("GitHub (calamity-inc/warframe-public-export)", fetch_export_github),
                         ("公式 Public Export", fetch_export)):
        print(f"  取得元: {label}")
        try:
            en_docs, ja_docs = fetch("en"), fetch("ja")
            names = names_from_exports(en_docs, ja_docs)
            names["source"] = label
            if docs_out is not None:
                docs_out.update(en=en_docs, ja=ja_docs, source=label)
            return names
        except Exception as e:  # noqa: BLE001
            print(f"  失敗: {e}")
            errors.append(f"{label}: {e}")
    raise RuntimeError(" / ".join(errors))
