"""Rekordy DNS w Cloudflare ustawiane automatycznie (kontener „dns” w docker-compose.yml): python -m zniesione.ddns

- WG_HOST (np. wg.zniesione.pl): rekord A na publiczny adres IP serwera, bez proxy (WireGuard przez nie nie przejdzie).
- MAIL_DOMAIN (np. zniesione.pl): poczta: A mail.<domena>, MX, SPF, DMARC i DKIM (klucz z serwera poczty, DKIM_FILE).
  Istniejących rekordów SPF i DMARC nie nadpisuje (mogą być ustawione świadomie), tylko ostrzega w logach.
Sprawdza wszystko co DDNS_EVERY_MIN minut, więc działa też przy zmiennym adresie IP.
Wymaga CF_API_TOKEN z uprawnieniem Zone → DNS → Edit dla tej domeny."""
import json
import os
import re
import time
import urllib.parse
import urllib.request

API = "https://api.cloudflare.com/client/v4"
NOTE = "zniesione.pl: ustawiane automatycznie"


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


def zone_of(token, name, opener=urllib.request.urlopen):
    parts = name.split(".")
    for i in range(len(parts) - 1):  # wg.zniesione.pl -> szukamy strefy zniesione.pl
        found = call("GET", f"/zones?name={'.'.join(parts[i:])}", token, opener=opener)
        if found:
            return found[0]["id"]
    raise RuntimeError(f"Token nie ma dostępu do strefy dla {name}")


def norm(content):
    """Treść rekordu bez cudzysłowów TXT (Cloudflare może zwracać długie TXT jako kilka napisów w cudzysłowach)."""
    c = (content or "").strip()
    parts = re.findall(r'"((?:[^"\\]|\\.)*)"', c)
    return "".join(parts) if parts and c.startswith('"') else c


def records(token, zone, rtype, name, opener=urllib.request.urlopen):
    q = urllib.parse.urlencode({"type": rtype, "name": name})
    return call("GET", f"/zones/{zone}/dns_records?{q}", token, opener=opener)


def upsert(token, zone, rtype, name, content, opener=urllib.request.urlopen, match=None, priority=None, create_only=False):
    """Tworzy albo poprawia rekord. Zwraca 'created', 'updated', 'unchanged' albo 'kept' (inny, zostawiony)."""
    recs = [r for r in records(token, zone, rtype, name, opener) if not match or match(norm(r["content"]))]
    body = {"type": rtype, "name": name, "content": content, "ttl": 300 if rtype != "A" else 120, "comment": NOTE}
    if rtype == "A":
        body["proxied"] = False
    if priority is not None:
        body["priority"] = priority
    if not recs:
        call("POST", f"/zones/{zone}/dns_records", token, body, opener)
        return "created"
    r = recs[0]
    if norm(r["content"]).rstrip(".") == content and not r.get("proxied") and (priority is None or r.get("priority") == priority):
        return "unchanged"
    if create_only:
        return "kept"
    call("PUT", f"/zones/{zone}/dns_records/{r['id']}", token, body, opener)
    return "updated"


def sync(token, name, ip, opener=urllib.request.urlopen):
    """Rekord A dla WireGuard."""
    return upsert(token, zone_of(token, name, opener), "A", name, ip, opener)


def dkim_value(path):
    """Klucz publiczny DKIM z pliku mail.txt docker-mailservera (format strefy BIND, treść w cudzysłowach)."""
    try:
        with open(path, encoding="utf-8") as f:
            v = "".join(re.findall(r'"([^"]*)"', f.read())).strip()
    except OSError:
        return None
    return v if "p=" in v else None


def sync_mail(token, domain, ip, dkim_path, opener=urllib.request.urlopen):
    """Rekordy poczty dla domeny. Zwraca listę (rekord, wynik) do logów."""
    zone, host, out = zone_of(token, domain, opener), f"mail.{domain}", []
    out.append((f"A {host}", upsert(token, zone, "A", host, ip, opener)))
    out.append((f"MX {domain}", upsert(token, zone, "MX", domain, host, opener, match=lambda c: c.rstrip(".") == host, priority=10)))
    others = [r["content"] for r in records(token, zone, "MX", domain, opener) if norm(r["content"]).rstrip(".") != host]
    if others:
        out.append((f"MX {domain}", "UWAGA: są też inne serwery MX (" + ", ".join(others) + "); np. wyłącz Cloudflare Email Routing"))
    spf = upsert(token, zone, "TXT", domain, "v=spf1 mx -all", opener, match=lambda c: c.startswith("v=spf1"), create_only=True)
    out.append((f"SPF {domain}", spf if spf != "kept" else "kept: istnieje inny SPF, sprawdź, czy zawiera „mx”"))
    dmarc = f"v=DMARC1; p=quarantine; rua=mailto:postmaster@{domain}"
    out.append((f"DMARC _dmarc.{domain}", upsert(token, zone, "TXT", f"_dmarc.{domain}", dmarc, opener,
                                                  match=lambda c: c.startswith("v=DMARC1"), create_only=True)))
    dk = dkim_value(dkim_path)
    out.append((f"DKIM mail._domainkey.{domain}", upsert(token, zone, "TXT", f"mail._domainkey.{domain}", dk, opener,
                                                         match=lambda c: c.startswith("v=DKIM1")) if dk
                else "czeka na klucz od serwera poczty"))
    return out


def main():
    token, wg, mail = (os.environ.get(k, "") for k in ("CF_API_TOKEN", "WG_HOST", "MAIL_DOMAIN"))
    every = float(os.environ.get("DDNS_EVERY_MIN", "10")) * 60
    dkim = os.environ.get("DKIM_FILE") or f"/dms/opendkim/keys/{mail}/mail.txt"
    if not token:
        print("Brak CF_API_TOKEN: rekordy DNS dla WireGuard i poczty ustaw ręcznie (docs/WDROZENIE.md).", flush=True)
    last = None
    while True:
        if token and (wg or mail):
            try:
                ip, lines = public_ip(), []
                if wg:
                    lines.append((f"A {wg}", sync(token, wg, ip)))
                if mail:
                    lines += sync_mail(token, mail, ip, dkim)
                report = "\n".join(f"{k} -> {v}" for k, v in lines)
                if report != last:  # w logach tylko zmiany, nie to samo co 10 minut
                    print(f"IP serwera {ip}\n{report}", flush=True)
                    last = report
            except Exception as e:  # noqa: BLE001  sieć lub API: spróbujemy przy następnym obiegu
                print("Błąd aktualizacji DNS:", e, flush=True)
        time.sleep(every)  # osobny proces kontenera, nie wątek portalu


if __name__ == "__main__":
    main()
