"""画面サーバー: 127.0.0.1 だけで待ち受け、画面(HTML)と /api/* を返す

/api/* の経路は各グループ(search・personal・info・admin・tips・sim)の ROUTES から集める。
ページを足すときは、そのグループに処理と ROUTES の1行を足せばよい(ここは触らなくてよい)。
"""
from __future__ import annotations

import argparse
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import wfportal_builder as wb
from wfp.api import admin, info, ocr, pages, personal, qa, search, sim, tips
from wfp.api.store import ApiError, Raw, Store
from wfp.core import common
from wfp.core.const import API_FETCH_SITES, REQUEST_MAX_BYTES, SERVER_HEADERS
from wfp.core.i18n import txt
from wfp.fetch import logos
from wfp.store import build_images, datadir, userdb

GROUPS = (search, personal, info, admin, tips, sim, qa, ocr)


def collect_routes(groups=GROUPS) -> tuple[dict, dict]:
    """各グループの ROUTES を (完全一致, 前方一致) に分けて集める。同じ経路が2か所にあればエラー"""
    exact, prefix = {}, {}
    for g in groups:
        for (method, path), fn in g.ROUTES.items():
            table = prefix if path.endswith("/") else exact
            if (method, path) in table:
                raise RuntimeError(f"経路が重複しています: {method} {path}")
            table[(method, path)] = fn
    return exact, prefix


def ui_page(c: "Request") -> Raw:
    """メイン画面: web/ctrl.html・menu.html・view.html・i18n.html を組み立てた1枚(wfp/api/pages.py)"""
    return Raw(pages.ui_html(), "text/html; charset=utf-8")


def builder_page(c: "Request") -> Raw:
    """シミュレータ: web/wfportal_builder.html に i18n.html と言語の表を差し込んだもの(wfp/api/pages.py)"""
    return Raw(pages.builder_html(), "text/html; charset=utf-8")


def logo(c: "Request") -> Raw:
    """各自の PC に取得した公式ファンキットのロゴ(同梱はしていない)"""
    ld = logos.find_logos_dir(c.store.d)
    if ld is None:
        raise ApiError(txt("err.logo.none"), 404)
    return Raw((ld / "LotusFlower.png").read_bytes(), "image/png", "private, max-age=86400")


# 画面とロゴ(/api/* より先に見る)
PAGES = {
    ("GET", "/"): ui_page,
    ("GET", "/index.html"): ui_page,
    # シミュレータ(メニューの「シミュレータ」の中に表示する。単独のページとしても開ける)
    ("GET", "/builder"): builder_page,
    ("GET", "/simulator"): builder_page,
    ("GET", "/logo.png"): logo,
}


class Request:
    """経路の処理に渡すリクエスト。本文は処理が必要としたときにだけ読む"""

    def __init__(self, handler: BaseHTTPRequestHandler, store: Store, tips_dir: Path):
        u = urlparse(handler.path)
        self.handler, self.store, self.tips, self.path = handler, store, tips_dir, u.path
        self.q = {k: v[0] for k, v in parse_qs(u.query).items()}

    def flag(self, k: str, default: bool = False) -> bool:
        return self.q.get(k, "1" if default else "0") == "1"

    def _length(self, limit: int, too_large) -> int:
        """本文の長さ(Content-Length。無ければ 0)。数字でない・負の数は 400、limit を超えたら too_large(テキスト指定)で 413"""
        raw = (self.handler.headers.get("Content-Length") or "0").strip()
        if not (raw.isascii() and raw.isdigit()):  # int() は "-1" "+5" "1_0" も通すので、数字だけかを先に見る
            raise ApiError(txt("err.req.bad_length"), 400)
        size = int(raw)
        if size > limit:
            raise ApiError(too_large, 413)
        return size

    def body(self) -> dict:
        h = self.handler.headers
        if "application/json" not in (h.get("Content-Type") or ""):
            raise ApiError(txt("err.req.json_type"), 415)
        size = self._length(REQUEST_MAX_BYTES, txt("err.req.too_large"))
        try:
            return json.loads(self.handler.rfile.read(size) or b"{}")
        except json.JSONDecodeError:
            raise ApiError(txt("err.req.bad_json"))

    def empty_body(self) -> None:
        """本文を使わない POST でも、形式(JSON)の検査はする。戻り値は常に None"""
        self.body()

    def image(self) -> bytes:
        h = self.handler.headers
        if not (h.get("Content-Type") or "").startswith("image/"):
            raise ApiError(txt("err.req.image_type"), 415)
        size = self._length(build_images.IMAGE_MAX_BYTES, txt("err.req.image_large", mb=str(build_images.IMAGE_MAX_BYTES // 1024 // 1024)))
        return self.handler.rfile.read(size)


def make_handler(store: Store, tips_dir: Path | None = None):
    tips_path = tips_dir or tips.tips_root()
    exact, prefix = collect_routes()

    def find(method: str, path: str):
        if fn := PAGES.get((method, path)) or exact.get((method, path)):
            return fn
        return next((fn for (m, p), fn in prefix.items() if m == method and path.startswith(p)), None)

    class Handler(BaseHTTPRequestHandler):
        server_version = "wfportal"

        def log_message(self, fmt, *args):  # 静かにする
            pass

        def _send(self, code: int, body: bytes, ctype: str, cache: str = "no-store"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            for name, value in SERVER_HEADERS.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _error(self, text, code: int):
            """サーバーの共通のエラー(経路の処理の外)。text はテキスト指定。応答の形は ApiError と同じ"""
            self._json(ApiError(text, code).payload(), code)

        def _guard(self) -> bool:
            """DNSリバインディング/他サイトからの操作を防ぐ"""
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
            if host not in ("127.0.0.1", "localhost"):
                self._error(txt("err.req.forbidden"), 403)
                return False
            origin = self.headers.get("Origin")
            if origin and urlparse(origin).netloc != self.headers.get("Host"):
                self._error(txt("err.req.forbidden"), 403)
                return False
            # ほかのサイトのページからの API の呼び出し(Origin が付かない GET も)。画面のページへの移動は止めない
            site = self.headers.get("Sec-Fetch-Site")
            if site and site not in API_FETCH_SITES and urlparse(self.path).path.startswith("/api/"):
                self._error(txt("err.req.forbidden"), 403)
                return False
            return True

        def _dispatch(self, method: str):
            if not self._guard():
                return
            try:
                req = Request(self, store, tips_path)
                fn = find(method, req.path)
                if fn is None:
                    return self._error(txt("err.req.no_route"), 404)
                out = fn(req)
                if isinstance(out, Raw):
                    return self._send(200, out.body, out.ctype, out.cache)
                return self._json(out)
            except ApiError as e:
                self._json(e.payload(), e.status)
            except wb.BuilderError as e:
                self._json({"error": str(e), "text": e.text}, e.status)
            except userdb.UserDbError as e:  # 利用者データが壊れていて戻せない・新しい版で作られている
                self._json({"error": str(e), "text": e.text}, 500)
            except (BrokenPipeError, ConnectionResetError):
                pass  # ブラウザ側が先に接続を閉じた
            except Exception as e:  # noqa: BLE001
                print(f"[エラー] {method} {self.path}: {e!r}")  # 起動した画面にも残す
                self._error(txt("err.internal", msg=str(e)), 500)

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def do_DELETE(self):
            self._dispatch("DELETE")

    return Handler


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="wfportal ローカルUI")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--data-dir")
    ap.add_argument("--no-open", action="store_true", help="ブラウザを自動で開かない")
    args = ap.parse_args(argv)

    store = Store(datadir.data_dir(args.data_dir))
    try:  # 起動したときに1回: 利用者データの検査・引っ越し・バックアップ。使えなければ知らせて、利用者データを使わないページは動かす
        userdb.ready(store.d)
    except userdb.UserDbError as e:
        print(f"[注意] {e}")
    userdb.start_backup_timer(store.d)
    server = None
    for port in range(args.port, args.port + 10):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(store))
            break
        except OSError:
            continue
    if server is None:
        raise SystemExit(f"ポート {args.port}〜{args.port + 9} が使用中です。--port で別の番号を指定してください。")
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Warframe Portal v{common.app_version()}: {url}  (終了は Ctrl+C)\nデータ: {store.d}")
    if not args.no_open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n終了します。")
    finally:
        server.server_close()
