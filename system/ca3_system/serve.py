"""Serve the CA3 local UI and its generated artifact bundle."""

from __future__ import annotations

import argparse
import functools
import json
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .pipeline import build_case_bundle

SYSTEM_ROOT = Path(__file__).resolve().parents[1]


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local CA3 investigation system")
    parser.add_argument(
        "--config",
        help="Optional local artifact-adapter config. Without it, serve the synthetic demo.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    output = build_case_bundle(args.config) if args.config else SYSTEM_ROOT / "static" / "data"
    static_root = SYSTEM_ROOT / "static"
    handler = functools.partial(Handler, directory=str(static_root))
    server = ThreadingHTTPServer((args.host, args.port), handler)
    url = f"http://{args.host}:{args.port}/"
    print(json.dumps({"url": url, "run": str(output)}, indent=2))
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
