"""Budowanie i wgrywanie firmware ESPHome dla portalu zniesione.pl (kontener „esphome” w docker-compose.yml).

Działa we wspólnej sieci z portalem (127.0.0.1:6100), więc z zewnątrz jest niedostępny, a sterowniki widzi przez WireGuard.
Portal wysyła konfigurację (YAML + secrets), builder uruchamia `esphome compile` albo `esphome run` (kompilacja
i wgranie przez sieć OTA). Gotowy plik firmware.factory.bin portal podaje przeglądarce do wgrania przez USB.

API (nagłówek X-Builder-Token):
  POST /jobs                {"name", "yaml", "secrets", "action": "compile"|"upload", "ip"} -> {"id"}
  GET  /jobs/<id>           -> {"status": "running"|"ok"|"error", "action", "log", "binary": bool}
  GET  /jobs/<id>/firmware  -> plik firmware.factory.bin
Jednocześnie działa jedno zadanie (kompilacja ESP32 zajmuje dużo pamięci i procesora)."""
import json
import os
import re
import shlex
import subprocess
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = os.environ.get("BUILDER_TOKEN", "")
ROOT = os.environ.get("CONFIG_DIR", "/config")
ESPHOME = shlex.split(os.environ.get("ESPHOME_CMD", "esphome"))
JOBS, LOCK, RUN = {}, threading.Lock(), threading.Lock()


def factory_bin(name):
    """ESPHome zapisuje firmware w .esphome/build/<nazwa>/.pioenvs/<nazwa>/ (katalogi z kropką: glob ich nie widzi)."""
    found = [os.path.join(d, "firmware.factory.bin") for d, _, files in os.walk(os.path.join(ROOT, name, ".esphome", "build", name))
             if "firmware.factory.bin" in files]
    return max(found, key=os.path.getmtime) if found else None


def run_job(jid, name, action, ip):
    job = JOBS[jid]
    cfg = os.path.join(ROOT, name, name + ".yaml")
    cmd = ESPHOME + (["compile", cfg] if action == "compile" else ["run", "--no-logs", "--device", ip, cfg])
    with RUN:  # jedno zadanie naraz, reszta czeka w kolejce
        job["status"] = "running"
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
                                 cwd=os.path.join(ROOT, name))
            for line in p.stdout:
                job["log"] = (job["log"] + [line.rstrip()])[-300:]
            job["status"] = "ok" if p.wait() == 0 else "error"
        except OSError as e:
            job["log"].append(f"Nie udało się uruchomić ESPHome: {e}")
            job["status"] = "error"


class H(BaseHTTPRequestHandler):
    def send(self, code, obj=None, raw=None, ctype="application/json"):
        data = raw if raw is not None else json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        if not TOKEN or self.headers.get("X-Builder-Token") != TOKEN:
            self.send(401, {"error": "Brak autoryzacji"})
            return False
        return True

    def do_POST(self):
        if not self.authorized():
            return
        if self.path != "/jobs":
            return self.send(404, {"error": "Nie znaleziono"})
        try:
            b = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        except ValueError:
            return self.send(400, {"error": "Niepoprawny JSON"})
        name, action, ip = b.get("name", ""), b.get("action"), b.get("ip", "")
        if not re.fullmatch(r"[a-z0-9-]{1,40}", name or "") or action not in ("compile", "upload") \
                or not isinstance(b.get("yaml"), str) or not isinstance(b.get("secrets"), str):
            return self.send(400, {"error": "Potrzebne: name, yaml, secrets, action compile albo upload"})
        if action == "upload" and not re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", ip or ""):
            return self.send(400, {"error": "Do wgrania przez sieć potrzebny jest adres IP sterownika"})
        os.makedirs(os.path.join(ROOT, name), exist_ok=True)
        for fn, text in ((name + ".yaml", b["yaml"]), ("secrets.yaml", b["secrets"])):
            with open(os.path.join(ROOT, name, fn), "w", encoding="utf-8") as f:
                f.write(text)
        os.chmod(os.path.join(ROOT, name, "secrets.yaml"), 0o600)
        jid = uuid.uuid4().hex[:12]
        with LOCK:
            JOBS[jid] = {"status": "queued", "action": action, "name": name, "log": []}
        threading.Thread(target=run_job, args=(jid, name, action, ip), daemon=True).start()
        self.send(201, {"id": jid})

    def do_GET(self):
        if self.path == "/health":
            return self.send(200, {"ok": True})
        if not self.authorized():
            return
        m = re.fullmatch(r"/jobs/([0-9a-f]{12})(/firmware)?", self.path)
        job = JOBS.get(m.group(1)) if m else None
        if not job:
            return self.send(404, {"error": "Nie znaleziono zadania"})
        binary = factory_bin(job["name"]) if job["status"] == "ok" else None
        if m.group(2):
            if not binary:
                return self.send(404, {"error": "Firmware nie jest gotowe"})
            with open(binary, "rb") as f:
                return self.send(200, raw=f.read(), ctype="application/octet-stream")
        self.send(200, {"status": job["status"], "action": job["action"], "log": "\n".join(job["log"][-120:]), "binary": bool(binary)})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Ustaw BUILDER_TOKEN")
    ThreadingHTTPServer((os.environ.get("HOST", "127.0.0.1"), int(os.environ.get("PORT", "6100"))), H).serve_forever()
