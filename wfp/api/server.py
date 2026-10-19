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
from wfp.api import admin, info, pages, personal, search, sim, tips
from wfp.api.store import ApiError, Raw, Store
from wfp.core import common
from wfp.fetch import logos
from wfp.store import build_images, datadir

GROUPS = (search, personal, info, admin, tips, sim)


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


def page(name: str):
    return lambda c: Raw((common.APP_DIR / "web" / name).read_bytes(), "text/html; charset=utf-8")


def ui_page(c: "Request") -> Raw:
    """メイン画面: web/ctrl.html・menu.html・view.html を組み立てた1枚(wfp/api/pages.py)"""
    return Raw(pages.ui_html(), "text/html; charset=utf-8")


def logo(c: "Request") -> Raw:
    """各自の PC に取得した公式ファンキットのロゴ(同梱はしていない)"""
    ld = logos.find_logos_dir(c.store.d)
    if ld is None:
        raise ApiError("ロゴ素材が未取得です。", 404)
    return Raw((ld / "LotusFlower.png").read_bytes(), "image/png", "private, max-age=86400")


# 画面とロゴ(/api/* より先に見る)
PAGES = {
    ("GET", "/"): ui_page,
    ("GET", "/index.html"): ui_page,
    # シミュレータ(メニューの「シミュレータ」の中に表示する。単独のページとしても開ける)
    ("GET", "/builder"): page("wfportal_builder.html"),
    ("GET", "/simulator"): page("wfportal_builder.html"),
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

    def body(self) -> dict:
        h = self.handler.headers
        if "application/json" not in (h.get("Content-Type") or ""):
            raise ApiError("Content-Type は application/json にしてください。", 415)
        n = int(h.get("Content-Length") or 0)
        if n > 1_000_000:
            raise ApiError("リクエストが大きすぎます。", 413)
        try:
            return json.loads(self.handler.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            raise ApiError("JSON を読み取れません。")

    def empty_body(self) -> None:
        """本文を使わない POST でも、形式(JSON)の検査はする。戻り値は常に None"""
        self.body()

    def image(self) -> bytes:
        h = self.handler.headers
        if not (h.get("Content-Type") or "").startswith("image/"):
            raise ApiError("画像ファイルを送ってください。", 415)
        n = int(h.get("Content-Length") or 0)
        if n > build_images.IMAGE_MAX_BYTES:
            raise ApiError(f"画像が大きすぎます(上限 {build_images.IMAGE_MAX_BYTES // 1024 // 1024}MB)。", 413)
        return self.handler.rfile.read(n)


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
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _guard(self) -> bool:
            """DNSリバインディング/他サイトからの操作を防ぐ"""
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
            if host not in ("127.0.0.1", "localhost"):
                self._json({"error": "forbidden"}, 403)
                return False
            origin = self.headers.get("Origin")
            if origin and urlparse(origin).netloc != self.headers.get("Host"):
                self._json({"error": "forbidden"}, 403)
                return False
            return True

        def _dispatch(self, method: str):
            if not self._guard():
                return
            try:
                req = Request(self, store, tips_path)
                fn = find(method, req.path)
                if fn is None:
                    return self._json({"error": "not found"}, 404)
                out = fn(req)
                if isinstance(out, Raw):
                    return self._send(200, out.body, out.ctype, out.cache)
                return self._json(out)
            except (ApiError, wb.BuilderError) as e:
                self._json({"error": str(e)}, e.status)
            except (BrokenPipeError, ConnectionResetError):
                pass  # ブラウザ側が先に接続を閉じた
            except Exception as e:  # noqa: BLE001
                print(f"[エラー] {method} {self.path}: {e!r}")  # 起動した画面にも残す
                self._json({"error": f"内部エラー: {e}"}, 500)

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
