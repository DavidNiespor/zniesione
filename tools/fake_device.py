"""Atrapa sterownika ESPHome do testów funkcjonalnych.
Uruchom: python tools/fake_device.py 9000, a portal z DEVICE_BASE=http://127.0.0.1:9000"""
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

STATE = {}


class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        m = re.fullmatch(r"/switch/([\w-]+)/turn_(on|off)", self.path)
        if not m:
            return self._send(404, {"error": "nieznana ścieżka"})
        STATE[m[1]] = m[2] == "on"
        print(f"{m[1]} -> {m[2]}", flush=True)
        self._send(200, {"id": m[1], "state": STATE[m[1]]})

    def do_GET(self):
        self._send(200, STATE)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 9000), H).serve_forever()
