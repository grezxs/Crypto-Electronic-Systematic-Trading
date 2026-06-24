"""Local web-terminal server (zero dependencies, stdlib only).

Serves the `frontend/` static terminal AND the two bridge endpoints the bot
shares state through, so the live data connection works locally without Vercel:

    GET  /api/state    -> runtime/state.json   (written by StatePublisher)
    POST /api/control  -> runtime/control.json  (read by the bot's ControlBridge)
    GET  /(.*)         -> frontend/<path>       (index.html, fonts, ...)

Run:  python scripts/serve_frontend.py            # http://localhost:8000
      python scripts/serve_frontend.py --port 9000

This is the local equivalent of the Vercel routes in vercel.json. The bot
(`python main.py`) and this server share the same `runtime/` JSON files, so the
terminal shows the bot's real live state and its buttons control the bot.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))  # so /api/backtest can import the real backtester
_bt_cache: dict = {}
_FRONTEND = _ROOT / "frontend"
_STATE = _ROOT / "runtime" / "state.json"
_CONTROL = _ROOT / "runtime" / "control.json"

_CTYPE = {
    ".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript",
    ".json": "application/json", ".otf": "font/otf", ".ttf": "font/ttf",
    ".woff": "font/woff", ".woff2": "font/woff2", ".png": "image/png",
    ".jpg": "image/jpeg", ".svg": "image/svg+xml", ".ico": "image/x-icon",
}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body=b"", ctype="application/json", extra=None):
        self.send_response(code)
        if body:
            self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/state":
            if not _STATE.exists():
                return self._send(204)
            try:
                return self._send(200, _STATE.read_bytes(), "application/json")
            except Exception:
                return self._send(503)
        if path == "/api/backtest":
            q = parse_qs(urlparse(self.path).query)
            sym = q.get("symbol", ["BTC/USDT"])[0]
            tf = q.get("tf", ["1d"])[0]
            bars = q.get("bars", ["180"])[0]
            source = q.get("source", ["mainnet"])[0]
            key = (sym, tf, bars, source)
            if key in _bt_cache:
                return self._send(200, _bt_cache[key], "application/json")
            try:
                from src.part8_backtest.web import run_for_ui
                payload = json.dumps(run_for_ui(sym, tf, int(bars), source)).encode()
                _bt_cache[key] = payload
                return self._send(200, payload, "application/json")
            except Exception as exc:
                return self._send(500, json.dumps({"error": str(exc)}).encode(), "application/json")
        # static files from frontend/
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (_FRONTEND / rel).resolve()
        if not str(target).startswith(str(_FRONTEND.resolve())) or not target.is_file():
            return self._send(404, b"not found", "text/plain")
        return self._send(200, target.read_bytes(), _CTYPE.get(target.suffix, "application/octet-stream"))

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/api/control":
            return self._send(404, b"not found", "text/plain")
        try:
            length = int(self.headers.get("Content-Length", 0))
            cmd = json.loads(self.rfile.read(length) or b"{}")
            payload = {
                "trading_enabled": bool(cmd.get("trading_enabled", True)),
                "kill_switch": bool(cmd.get("kill_switch", False)),
                "updated": time.time(),
            }
            _CONTROL.parent.mkdir(parents=True, exist_ok=True)
            tmp = _CONTROL.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload))
            os.replace(tmp, _CONTROL)
            return self._send(200, b'{"ok":true}', "application/json")
        except Exception as exc:
            return self._send(400, json.dumps({"error": str(exc)}).encode(), "application/json")

    def log_message(self, *_):
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description="Local web-terminal server (frontend + bridge API)")
    ap.add_argument("--port", type=int, default=int(os.environ.get("FRONTEND_PORT", 8000)))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-open", action="store_true", help="do not auto-open the browser")
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://localhost:{args.port}"
    print(f"web terminal -> {url}  (serving {_FRONTEND})")
    print("  /api/state  <- runtime/state.json   /api/control -> runtime/control.json")
    # auto-open the browser shortly after the server starts listening (skip when
    # bound to 0.0.0.0 for remote sharing, or when DASHBOARD_NO_OPEN is set)
    if not args.no_open and args.host in ("127.0.0.1", "localhost") and not os.environ.get("DASHBOARD_NO_OPEN"):
        import webbrowser
        import threading
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
