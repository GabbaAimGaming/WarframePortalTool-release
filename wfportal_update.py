#!/usr/bin/env python3
"""wfportal_update - 起動時の自動更新 (標準ライブラリのみ / Python 3.9+)

    python wfportal_update.py            新しい版があれば、変わったファイルだけ取得して置き換える
    python wfportal_update.py --check    確認だけする(置き換えない)
    python wfportal_update.py --json     結果を JSON の1行で出す(画面の「最新バージョンがあるかチェックする」が使う。--check とも組める)

配布用の公開リポジトリ(REPO)にある release/manifest_<版>.json (版 = lite / with_python) と、
このフォルダの version.json を比べ、GitHub の方がバージョンが新しいときだけ更新する。
(開発は非公開のリポジトリで行い、main に push すると GitHub Actions が公開リポジトリへ配布物を置く。
 build/publish.py と .github/workflows/release.yml を参照)

- マニフェストには、版ごとの全ファイルの SHA-256 が載っている。中身が違うファイルだけを取得し、
  すべて取得して SHA-256 が一致したことを確かめてから、まとめて置き換える(途中で失敗したら何も変えない)
- tips/ のメモは利用者が編集するので、自分で書き換えたメモ・自分で消したメモはそのまま残す
  (前回の更新内容を update_state.json に覚えておき、配布したままのメモだけを更新する)
- python/ (同梱の Python)・assets/ (ロゴ素材)・データ置き場 (~/.wfportal) には触らない
- 起動用の start_wfportal.bat は実行中に書き換えられないので start_wfportal.bat.new に置き、
  終了コード 10 を返す。bat 側でそれを入れ替えて起動し直す
- ネットワークにつながらない・GitHub が見られないときは何もせず、そのまま起動する
- git で管理しているフォルダ(.git がある)では動かない(git pull で更新する)
- 自動更新を止めるには、このフォルダに NO_AUTO_UPDATE という名前のファイルを置くか、
  環境変数 WFPORTAL_NO_UPDATE=1 を設定する

終了コード: 0 = 最新 / 更新した、1 = 確認・更新できなかった(起動は続けてよい)、
            10 = 更新した上で、起動用 bat を入れ替える必要がある
            (画面から手動で更新して start_wfportal.bat.new が残っているときも、次の起動で 10 を返して入れ替えさせる)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path
from urllib.parse import quote

REPO = "GabbaAimGaming/WarframePortalTool-release"  # 配布用の公開リポジトリ
BRANCH = "main"
DEFAULT_BASE = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}"
APP_DIR = Path(__file__).resolve().parent

VERSION_FILE = "version.json"
STATE_FILE = "update_state.json"
BAT = "start_wfportal.bat"
BAT_NEW = BAT + ".new"
EDITIONS = ("source", "lite", "with_python")
EXIT_OK, EXIT_FAILED, EXIT_RESTART = 0, 1, 10
# 確認・更新の結果の状態(--json の state。画面の文字は web/i18n の appupd.state.<状態>)
STATE_OFF, STATE_GIT, STATE_BROKEN, STATE_FAILED = "off", "git", "broken", "failed"
STATE_LATEST, STATE_OLDER, STATE_NEWER, STATE_UPDATED = "latest", "older", "newer", "updated"

MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
# 更新で触らない場所 (同梱 Python・ロゴ素材・配布用の出力・git)
# userdata/ は uninstall.bat がデータ置き場を zip にして退避する場所(利用者のデータ。更新で触らない)
UNMANAGED = ("python/", "assets/", "dist/", "release/", ".git/", ".github/", "userdata/")
# 利用者が編集するメモ。配布したままのものだけ更新し、編集・削除したものは残す
USER_FILES = ("tips/",)
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) wfportal-updater/1.0"
VERSION_RE = re.compile(r"^\d+\.\d{2}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class UpdateError(Exception):
    pass


# --------------------------------------------------------------------------
# 小さな道具
# --------------------------------------------------------------------------

def parse_version(v) -> tuple[int, int]:
    """"1.10" -> (1, 10)。表記は 1.00 / 1.10 / 1.20 ... (小数点以下2桁)"""
    if not isinstance(v, str) or not VERSION_RE.match(v):
        raise UpdateError(f"バージョンの書き方が不正です: {v!r}")
    major, minor = v.split(".")
    return int(major), int(minor)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_rel(path) -> str:
    """マニフェストに書かれたパスを確かめる(フォルダの外や、管理しない場所は受け付けない)"""
    if not isinstance(path, str) or not path or "\\" in path or ":" in path or path.startswith("/") or "\x00" in path:
        raise UpdateError(f"不正なパスです: {path!r}")
    if any(part in ("", ".", "..") for part in path.split("/")):
        raise UpdateError(f"不正なパスです: {path!r}")
    if path.startswith(UNMANAGED) or path in (STATE_FILE, BAT_NEW):
        raise UpdateError(f"更新の対象外のパスです: {path!r}")
    return path


def base_url() -> str:
    """取得元。既定は GitHub。環境変数 WFPORTAL_UPDATE_URL で変えられる(テスト・ミラー用)"""
    return os.environ.get("WFPORTAL_UPDATE_URL", DEFAULT_BASE).rstrip("/")


def fetch(url: str, limit: int = MAX_FILE_BYTES, timeout: int = 15) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise UpdateError(f"ファイルが大きすぎます: {url}")
    return data


def read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def write_json(p: Path, obj) -> None:
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def local_version(d: Path) -> dict:
    v = read_json(d / VERSION_FILE) or {}
    return {"version": v.get("version"), "edition": v.get("edition")}


# --------------------------------------------------------------------------
# マニフェストと更新の計画
# --------------------------------------------------------------------------

def load_manifest(edition: str) -> dict:
    if edition not in EDITIONS:
        raise UpdateError(f"版の名前が不正です: {edition!r}")
    try:
        m = json.loads(fetch(f"{base_url()}/release/manifest_{edition}.json", limit=MAX_MANIFEST_BYTES).decode("utf-8-sig"))
    except ValueError as e:
        raise UpdateError(f"マニフェストを読めません: {e}") from None
    return check_manifest(m, edition)


def check_manifest(m, edition: str) -> dict:
    if not isinstance(m, dict) or m.get("edition") != edition or not isinstance(m.get("files"), dict):
        raise UpdateError("マニフェストの形式が不正です")
    parse_version(m.get("version"))
    for path, info in m["files"].items():
        safe_rel(path)
        if not isinstance(info, dict) or not SHA_RE.match(str(info.get("sha256", ""))):
            raise UpdateError(f"マニフェストの形式が不正です: {path}")
        src = info.get("src") or path
        if not isinstance(src, str) or ".." in src.split("/") or src.startswith("/") or "\\" in src:
            raise UpdateError(f"マニフェストの取得元が不正です: {path}")
    return m


def plan_update(d: Path, manifest: dict, state: dict | None) -> dict:
    """取得するもの・消すもの・残すもの(利用者が編集したメモ)を決める"""
    prev = (state or {}).get("files") or {}
    download, delete, kept = [], [], []
    files = manifest["files"]
    for path, info in files.items():
        if path == VERSION_FILE:
            continue  # version.json は最後に書く
        target = d / path
        exists = target.is_file()
        local = sha256_file(target) if exists else None
        if local == info["sha256"]:
            continue
        if path.startswith(USER_FILES):
            if exists and not (prev.get(path) and local == prev[path]):
                kept.append(path)   # 自分で書き換えたメモ(または前回の記録が無い)は残す
                continue
            if not exists and path in prev:
                kept.append(path)   # 自分で消したメモは戻さない
                continue
        download.append((path, info))
    for path, old_sha in prev.items():
        if path in files or path == VERSION_FILE:
            continue
        try:
            safe_rel(path)
        except UpdateError:
            continue
        target = d / path
        # 新しい版で無くなったファイル。配布したままなら消す(編集したものは残す)
        if target.is_file() and sha256_file(target) == old_sha:
            delete.append(path)
    return {"download": download, "delete": delete, "kept": kept}


def apply_update(d: Path, manifest: dict, plan: dict, log=print) -> bool:
    """計画どおりに置き換える。すべて取得・検証できてから置き換える。bat を置き換えるなら True"""
    tmp = Path(tempfile.mkdtemp(prefix=".wfupdate_", dir=d))
    try:
        staged = []
        for i, (path, info) in enumerate(plan["download"]):
            src = info.get("src") or path
            data = fetch(f"{base_url()}/{quote(src, safe='/')}")
            if sha256_bytes(data) != info["sha256"]:
                raise UpdateError(f"{path} の内容がマニフェストと一致しません(GitHub 側の更新中の可能性があります。少し時間をおいて起動し直してください)")
            f = tmp / str(i)
            f.write_bytes(data)
            staged.append((path, f))
        bat = False
        for path, f in staged:
            dest = d / (BAT_NEW if path == BAT else path)
            bat = bat or path == BAT
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.replace(f, dest)
            log(f"    更新: {path}")
        for path in plan["delete"]:
            try:
                (d / path).unlink()
                log(f"    削除: {path}")
            except OSError:
                pass
        for path in plan["kept"]:
            log(f"    そのまま: {path}(自分で編集・削除したメモ)")
        write_json(d / STATE_FILE, {"version": manifest["version"], "edition": manifest["edition"],
                                    "files": {p: i["sha256"] for p, i in manifest["files"].items()}})
        write_json(d / VERSION_FILE, {"version": manifest["version"], "edition": manifest["edition"]})
        return bat
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------

def examine(d: Path, log=print) -> dict:
    """更新の確認(置き換えない)。{"state": 状態(STATE_*), "current": いまの版, "remote": 公開の版, "manifest", "plan"}
    plan は新しい版があるときだけ。画面の「最新バージョンがあるかチェックする」(--json)と起動時の更新で共通"""
    if os.environ.get("WFPORTAL_NO_UPDATE") == "1" or (d / "NO_AUTO_UPDATE").exists():
        log("自動更新はオフになっています。")
        return {"state": STATE_OFF}
    if (d / ".git").exists():
        log("git で管理しているフォルダなので、自動更新はしません(git pull で更新してください)。")
        return {"state": STATE_GIT}
    cur = local_version(d)
    try:
        current = parse_version(cur["version"])
        if cur["edition"] not in EDITIONS:
            raise UpdateError(f"版の名前が不正です: {cur['edition']!r}")
    except UpdateError as e:
        log(f"version.json を読めないため、自動更新はしません({e})。")
        return {"state": STATE_BROKEN}
    out = {"state": STATE_FAILED, "current": cur["version"]}
    log(f"更新を確認しています(いまの版: v{cur['version']})...")
    try:
        manifest = load_manifest(cur["edition"])
    except (OSError, UpdateError) as e:  # urllib のエラー(接続できない・404 など)は OSError
        log(f"  更新を確認できませんでした: {e}  ※いまの版のまま起動します")
        return out
    out.update(remote=manifest["version"], manifest=manifest)
    remote = parse_version(manifest["version"])
    if remote == current:
        log("  最新の版です。")
        return {**out, "state": STATE_LATEST}
    if remote < current:  # 古い版で上書きはしない(戻したいときは、番号を上げた版として公開する)
        log(f"  公開されている版(v{manifest['version']})より、この版(v{cur['version']})の方が新しいため、更新しません。")
        return {**out, "state": STATE_OLDER}
    plan = plan_update(d, manifest, read_json(d / STATE_FILE))
    log(f"  新しい版 v{manifest['version']} があります(取得 {len(plan['download'])} 件・削除 {len(plan['delete'])} 件)")
    return {**out, "state": STATE_NEWER, "plan": plan}


def update(d: Path = APP_DIR, check_only: bool = False, log=print) -> dict:
    """確認して、新しい版があれば置き換える。返り値は examine と同じ形(置き換えたら state = STATE_UPDATED・bat = 入れ替えが要るか)"""
    res = examine(d, log)
    if res["state"] != STATE_NEWER:
        return res
    plan = res["plan"]
    if check_only:
        for path, _ in plan["download"]:
            log(f"    取得する: {path}")
        for path in plan["delete"]:
            log(f"    削除する: {path}")
        return res
    try:
        bat = apply_update(d, res["manifest"], plan, log)
    except (OSError, UpdateError) as e:
        log(f"  更新できませんでした: {e}  ※いまの版のまま起動します")
        return {**res, "state": STATE_FAILED}
    log(f"  v{res['remote']} に更新しました。")
    return {**res, "state": STATE_UPDATED, "bat": bat}


def exit_code(d: Path, res: dict, check_only: bool, log=print) -> int:
    """終了コード。起動用 bat の入れ替えが要るとき(今回の更新・前回の手動の更新の残り start_wfportal.bat.new)は EXIT_RESTART"""
    if res["state"] in (STATE_FAILED, STATE_BROKEN):
        code = EXIT_FAILED
    else:
        code = EXIT_RESTART if res.get("bat") else EXIT_OK
    if not check_only and code != EXIT_RESTART and (d / BAT_NEW).is_file():
        # 画面から手動で更新したときの bat は、起動し直すまで入れ替えられないので残っている(古い bat は 10 のときだけ入れ替える)
        log("  前回の更新の起動用ファイルを入れ替えます。")
        return EXIT_RESTART
    return code


def report(res: dict) -> dict:
    """--json で出す形(画面の API が読む)。文は入れず、状態のキーと版・件数だけ"""
    plan = res.get("plan") or {}
    return {"state": res["state"], "current": res.get("current"), "remote": res.get("remote"),
            "download": len(plan.get("download", ())), "delete": len(plan.get("delete", ()))}


def run(d: Path = APP_DIR, check_only: bool = False, log=print) -> int:
    return exit_code(d, update(d, check_only, log), check_only, log)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Warframe Portal Tool の自動更新")
    ap.add_argument("--check", action="store_true", help="確認だけする(置き換えない)")
    ap.add_argument("--dir", help="ツールのフォルダ(既定: このファイルのあるフォルダ)")
    ap.add_argument("--json", action="store_true", help="進み具合を出さず、最後に結果を JSON の1行で出す(画面の API 用)")
    a = ap.parse_args(argv)
    d = Path(a.dir).resolve() if a.dir else APP_DIR
    if not a.json:
        return run(d, check_only=a.check)
    res = update(d, a.check, log=lambda *_: None)
    print(json.dumps(report(res), ensure_ascii=False))
    return exit_code(d, res, a.check, log=lambda *_: None)


if __name__ == "__main__":
    sys.exit(main())
