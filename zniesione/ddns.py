"""Rekord DNS dla WireGuard w Cloudflare (kontener „dns” w docker-compose.yml): python -m zniesione.ddns
Ustawia rekord A WG_HOST (np. wg.zniesione.pl) na publiczny adres IP serwera, bez proxy Cloudflare (WireGuard
przez nie nie przejdzie), i sprawdza go co DDNS_EVERY_MIN minut, więc działa też przy zmiennym adresie IP.
Wymaga CF_API_TOKEN z uprawnieniem Zone → DNS → Edit dla tej domeny."""
import json
import os
import re
import time
import urllib.request

API = "https://api.cloudflare.com/client/v4"


def call(method, path, token, body=None, opener=urllib.request.urlopen):
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with opener(req, timeout=15) as r:
        out = json.loads(r.read())
    if not out.get("success"):
        raise RuntimeError(f"Cloudflare API: {out.get('errors')}")
    return out["result"]


def public_ip(opener=urllib.request.urlopen):
    with opener(urllib.request.Request("https://1.1.1.1/cdn-cgi/trace"), timeout=15) as r:
        m = re.search(r"^ip=(\d{1,3}(?:\.\d{1,3}){3})$", r.read().decode(), re.M)
    if not m:
        raise RuntimeError("Nie udało się ustalić publicznego adresu IPv4 serwera")
    return m[1]


def sync(token, name, ip, opener=urllib.request.urlopen):
    """Tworzy albo poprawia rekord A. Zwraca 'created', 'updated' albo 'unchanged'."""
    parts, zone = name.split("."), None
    for i in range(len(parts) - 1):  # wg.zniesione.pl -> szukamy strefy zniesione.pl
        found = call("GET", f"/zones?name={'.'.join(parts[i:])}", token, opener=opener)
        if found:
            zone = found[0]["id"]
            break
    if not zone:
        raise RuntimeError(f"Token nie ma dostępu do strefy dla {name}")
    rec = call("GET", f"/zones/{zone}/dns_records?type=A&name={name}", token, opener=opener)
    body = {"type": "A", "name": name, "content": ip, "ttl": 120, "proxied": False,
            "comment": "WireGuard dla sterowników zniesione.pl (ustawiane automatycznie)"}
    if not rec:
        call("POST", f"/zones/{zone}/dns_records", token, body, opener)
        return "created"
    if rec[0]["content"] != ip or rec[0].get("proxied"):
        call("PUT", f"/zones/{zone}/dns_records/{rec[0]['id']}", token, body, opener)
        return "updated"
    return "unchanged"


def main():
    token, name = os.environ.get("CF_API_TOKEN", ""), os.environ.get("WG_HOST", "")
    every = float(os.environ.get("DDNS_EVERY_MIN", "10")) * 60
    if not token or not name:
        print("Brak CF_API_TOKEN lub WG_HOST: rekord DNS dla WireGuard ustaw ręcznie (docs/WDROZENIE.md).", flush=True)
    while True:
        if token and name:
            try:
                ip = public_ip()
                print(f"{name} -> {ip}: {sync(token, name, ip)}", flush=True)
            except Exception as e:  # noqa: BLE001  sieć lub API: spróbujemy przy następnym obiegu
                print("Błąd aktualizacji DNS:", e, flush=True)
        time.sleep(every)  # osobny proces kontenera, nie wątek portalu


if __name__ == "__main__":
    main()
