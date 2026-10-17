#!/usr/bin/env python3
"""Minimaler Webserver für die Energie-Tafel.
Liefert www/ nur unter dem geheimen Pfad /<TAFEL_TOKEN>/ aus, alles andere 404. Keine Caches, damit data.json immer frisch ist."""
import os, sys, http.server, posixpath

TOKEN = os.environ.get("TAFEL_TOKEN", "").strip("/")
PORT = int(os.environ.get("TAFEL_PORT", "8787"))
ROOT = os.path.abspath(os.environ.get("TAFEL_ROOT", "."))
if not TOKEN:
    sys.exit("TAFEL_TOKEN fehlt")

class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)
    def translate_path(self, path):
        path = path.split("?", 1)[0].split("#", 1)[0]
        prefix = "/" + TOKEN
        if path != prefix and not path.startswith(prefix + "/"):
            return os.path.join(ROOT, "__forbidden__")
        rel = path[len(prefix):] or "/"
        if rel == "/":
            rel = "/index.html"
        rel = posixpath.normpath(rel)
        full = os.path.join(ROOT, rel.lstrip("/"))
        return full if full.startswith(ROOT) else os.path.join(ROOT, "__forbidden__")
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Robots-Tag", "noindex")
        super().end_headers()
    def log_message(self, fmt, *args):
        if "404" in str(args):
            return
        super().log_message(fmt, *args)

http.server.ThreadingHTTPServer.allow_reuse_address = True
with http.server.ThreadingHTTPServer(("0.0.0.0", PORT), H) as s:
    print(f"Tafel auf Port {PORT}, Pfad /{TOKEN}/", flush=True)
    s.serve_forever()
