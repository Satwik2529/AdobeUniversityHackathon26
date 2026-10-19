#!/usr/bin/env python3
"""Serve a fixture site locally so the audit can be run offline and deterministically.

Static files alone cannot reproduce the failures that live in HTTP behaviour: a CDN that
answers 403 to non-browser agents, a deep link that bounces to the homepage, a header-only
noindex. Each fixture therefore carries an optional `_rules.json` describing server-side
behaviour, and this server applies it.

Rules format (all keys optional):
{
  "redirects": {"/path": {"to": "/", "code": 302}},
  "drop_query":  true,                       // redirect target omits the query string
  "status":      {"/path": 404},
  "headers":     {"/path": {"X-Robots-Tag": "noindex"}},
  "ua_block":    {"allow_substrings": ["Mozilla/5.0 (Windows"], "status": 403,
                  "body": "Forbidden"},
  "delay_ms":    0
}

Usage:
  fixture_server.py --dir tests/fixtures/F00-clean-control [--port 8099]

Exit codes: 0 clean shutdown, 2 bad arguments, 3 the fixture directory is unusable.
"""
import argparse
import json
import os
import posixpath
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".xml": "application/xml; charset=utf-8",
    ".json": "application/json",
    ".js": "application/javascript",
    ".png": "image/png",
    ".pdf": "application/pdf",
}


def make_handler(root, rules):
    class Handler(BaseHTTPRequestHandler):
        server_version = "FixtureServer/1.0"
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # keep test output clean
            pass

        def _send(self, status, body=b"", extra_headers=None, content_type="text/html"):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for key, value in (extra_headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _resolve(self, path):
            """Map a URL path to a file inside the fixture, safely."""
            clean = posixpath.normpath(urlsplit(path).path)
            if clean.endswith("/"):
                clean += "index.html"
            if clean in ("/", "//", "."):
                clean = "/index.html"
            if clean.endswith("/index.html") is False and os.path.isdir(
                    os.path.join(root, clean.lstrip("/"))):
                clean = clean.rstrip("/") + "/index.html"
            candidate = os.path.normpath(os.path.join(root, clean.lstrip("/")))
            if not candidate.startswith(root):
                return None  # traversal attempt
            return candidate

        def _handle(self):
            if rules.get("delay_ms"):
                time.sleep(rules["delay_ms"] / 1000.0)

            path = urlsplit(self.path).path
            query = urlsplit(self.path).query
            agent = self.headers.get("User-Agent", "")

            block = rules.get("ua_block")
            if block:
                allowed = any(s in agent for s in block.get("allow_substrings", []))
                if not allowed:
                    body = block.get("body", "Forbidden").encode("utf-8")
                    self._send(block.get("status", 403), body,
                               content_type="text/html; charset=utf-8")
                    return

            forced = (rules.get("status") or {}).get(path)
            if forced:
                self._send(forced, b"<html><body><h1>Error</h1></body></html>")
                return

            redirect = (rules.get("redirects") or {}).get(path)
            if redirect:
                target = redirect.get("to", "/")
                if query and not rules.get("drop_query"):
                    target = "%s?%s" % (target, query)
                self._send(redirect.get("code", 302), b"",
                           extra_headers={"Location": target})
                return

            candidate = self._resolve(path)
            if candidate is None or not os.path.isfile(candidate):
                self._send(404, b"<html><body><h1>Not found</h1></body></html>")
                return

            with open(candidate, "rb") as handle:
                body = handle.read()
            extension = os.path.splitext(candidate)[1]
            headers = dict((rules.get("headers") or {}).get(path, {}))
            self._send(200, body, headers,
                       content_type=CONTENT_TYPES.get(extension, "application/octet-stream"))

        do_GET = _handle
        do_HEAD = _handle

    return Handler


class FixtureServer(object):
    """Context-manager wrapper so tests can start and stop servers cleanly."""

    def __init__(self, directory, port=8099, host="localhost"):
        self.directory = os.path.abspath(directory)
        rules_path = os.path.join(self.directory, "_rules.json")
        self.rules = {}
        if os.path.isfile(rules_path):
            with open(rules_path, "r", encoding="utf-8") as handle:
                self.rules = json.load(handle)
        # The fixtures contain absolute URLs (canonical tags, sitemap locations). Binding
        # the host and port those URLs declare is what lets same-site and canonical checks
        # behave exactly as they would against a real origin.
        self.httpd = ThreadingHTTPServer(
            ("127.0.0.1", port), make_handler(self.directory, self.rules))
        self.httpd.allow_reuse_address = True
        self.port = self.httpd.server_address[1]
        self.base_url = "http://%s:%d" % (host, self.port)
        self._thread = None

    def __enter__(self):
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
        if self._thread:
            self._thread.join(timeout=5)
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description="Serve one fixture site locally.")
    parser.add_argument("--dir", required=True, help="fixture directory")
    parser.add_argument("--port", type=int, default=8099, help="port (default 8099)")
    args = parser.parse_args(argv)

    if not os.path.isdir(args.dir):
        sys.stderr.write("Error: not a directory: %s\n" % args.dir)
        return 3

    with FixtureServer(args.dir, args.port) as server:
        print("Serving %s at %s (ctrl-c to stop)" % (args.dir, server.base_url))
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\nstopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
