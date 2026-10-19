"""ビルド管理"""
from __future__ import annotations

from wfp.core.common import norm


def find_build(builds: list[dict], name: str) -> dict | None:
    hits = [b for b in builds if norm(b["name"]) == norm(name)] or [b for b in builds if norm(name) in norm(b["name"])]
    return hits[0] if len(hits) == 1 else None
