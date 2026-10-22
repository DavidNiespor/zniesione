"""Logika bez zależności od Flaska: harmonogramy, termostat, YAML, adresy IP, silnik sterowania."""
import re
import urllib.request
from datetime import datetime, timedelta

from . import catalog as cat
from . import db as dbm

OFFLINE_S = 300
DEFAULTS = {"wg_endpoint": "wg.zniesione.pl", "wg_port": "51820", "net": "10.8.0"}


def cfg(db, k):
    r = db.execute("SELECT v FROM config WHERE k=?", (k,)).fetchone()
    return r["v"] if r else DEFAULTS[k]


def valid_hm(t):
    return isinstance(t, str) and bool(re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t))


def _m(t):
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def day_ok(code, wd):  # wd: poniedziałek=0
    return code == "a" or (code == "w" and wd < 5) or (code == "e" and wd >= 5)


def sched_active(s, now):
    m, a, b = now.hour * 60 + now.minute, _m(s["t_on"]), _m(s["t_off"])
    if a == b:
        return False
    if a < b:
        return day_ok(s["days"], now.weekday()) and a <= m < b
    if m >= a:  # okno przez północ: dzień rozpoczęcia decyduje o dniach
        return day_ok(s["days"], now.weekday())
    if m < b:
        return day_ok(s["days"], (now - timedelta(days=1)).weekday())
    return False


def thermo(kind, temp, thr, cur):
    """Termostat z histerezą 1 °C. Wentylacja: włącz powyżej progu. Grzanie: włącz poniżej progu."""
    if kind in cat.COOL:
        return True if temp > thr else False if temp <= thr - 1 else cur
    return True if temp < thr else False if temp >= thr + 1 else cur


def desired(kind, scheds, rule, temp, now, cur):
    if rule and rule["enabled"] and temp is not None:
        return thermo(kind, temp, rule["threshold"], cur)
    act = [s for s in scheds if s["enabled"]]
    if act:
        return any(sched_active(s, now) for s in act)
    return None


def alloc_ip(db):
    net = cfg(db, "net")
    used = {r["ip"] for r in db.execute("SELECT ip FROM devices")}
    for i in range(10, 251):
        if f"{net}.{i}" not in used:
            return f"{net}.{i}"
    raise RuntimeError("Brak wolnych adresów w podsieci")


def esphome_yaml(dev, chans, db):
    m = cat.MODELS[dev["model"]]
    ep, port, net = cfg(db, "wg_endpoint"), cfg(db, "wg_port"), cfg(db, "net")
    if m.get("shelly"):
        return (f"# {m['name']} nie używa ESPHome. Ustawienia w panelu Shelly (Settings, MQTT):\n"
                f"# Serwer MQTT:      {ep}:8883\n# Identyfikator:    {dev['code']}\n"
                f"# Prefiks tematów:  kurnik/{dev['code']}\n# TLS:              włączone\n"
                "# Aktualizacje firmware: panel Shelly\n")
    tun = ("external_components:\n  - source: github://Csontikka/esphome-tailscale\n\ntailscale:\n"
           "  # klucz uwierzytelniający i opcje: README komponentu esphome-tailscale\n"
           if dev["tunnel"] == "ts" else
           f"wireguard:\n  address: {dev['ip']}\n  private_key: !secret wg_privkey\n  peer_endpoint: {ep}\n"
           f"  peer_port: {port}\n  peer_public_key: !secret wg_server_pubkey\n  peer_allowed_ips:\n"
           f"    - {net}.1/32\n  peer_persistent_keepalive: 25s\n")
    link = ("ethernet:\n  type: W5500\n  # clk_pin, mosi_pin, miso_pin, cs_pin, interrupt_pin, reset_pin: wg dokumentacji Waveshare\n\n"
            if m.get("eth") else "wifi:\n  ssid: !secret wifi_ssid\n  password: !secret wifi_password\n\n")
    if "relays" in m:
        sw = "switch:\n" + "".join(f"  - platform: gpio\n    id: {c['key']}\n    pin: GPIO{p}\n    name: {c['name']}\n"
                                    for c, p in zip(chans, m["relays"]))
    elif "sr" in m:
        s = m["sr"]
        sw = (f"sn74hc595:\n  - id: sr_hub\n    data_pin: {s['data']}\n    clock_pin: {s['clock']}\n"
              f"    latch_pin: {s['latch']}\n    sr_count: 1\n\nswitch:\n" +
              "".join(f"  - platform: gpio\n    id: {c['key']}\n    name: {c['name']}\n    pin:\n"
                      f"      sn74hc595: sr_hub\n      number: {i}\n" for i, c in enumerate(chans)))
    else:
        sw = "# Przekaźniki i wejścia: piny wg dokumentacji Waveshare\n"
    return (f"esphome:\n  name: {dev['code']}\n  friendly_name: Kurnik {dev['code']}\n\nesp32:\n  board: {m['board']}\n\n"
            f"{link}api:\n  encryption:\n    key: !secret api_key\n\nota:\n  - platform: esphome\n    password: !secret ota_password\n\n"
            f"web_server:\n  port: 80\n\ntime:\n  - platform: sntp\n\n{tun}\n{sw}"
            "\n# Czujnik temperatury i wilgotności (np. SHT31): podłącz do wolnych pinów, nie do pinów przekaźników\n")


def send_http(dev, ch, state):
    """Wysyła polecenie do urządzenia przez tunel. Ścieżkę zweryfikuj z web_server ESPHome na sprzęcie."""
    if dev["model"] == "shp":
        return False, "MQTT jeszcze nie zaimplementowane"
    url = f"http://{dev['ip']}/switch/{ch}/turn_{'on' if state else 'off'}"
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=b"", method="POST"), timeout=4)
        return True, None
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def log(db, dev_id, ch, state, src, ok, now):
    db.execute("INSERT INTO log(device_id,ch,state,src,ok,at) VALUES(?,?,?,?,?,?)",
               (dev_id, ch, int(state), src, int(ok), now.isoformat()))


def command(app, dev, ch, state, src, now=None):
    now = now or datetime.now()
    ok, err = app.config["SEND"](dict(dev), ch["key"], state)
    db = dbm.get()
    log(db, dev["id"], ch["key"], state, src, ok, now)
    if ok:
        db.execute("UPDATE channels SET state=? WHERE id=?", (int(state), ch["id"]))
    db.commit()
    return ok, err


def tick(app, now=None):
    """Jeden obieg silnika: porównuje stan pożądany z faktycznym i wysyła tylko różnice."""
    now = now or datetime.now()
    sent = []
    with app.app_context():
        db = dbm.get()
        for d in db.execute("SELECT * FROM devices WHERE stage=3 AND online=1").fetchall():
            if d["last_seen"] and (now - datetime.fromisoformat(d["last_seen"])).total_seconds() > OFFLINE_S:
                db.execute("UPDATE devices SET online=0 WHERE id=?", (d["id"],))
                continue
            r = db.execute("SELECT t FROM readings WHERE device_id=? ORDER BY id DESC LIMIT 1", (d["id"],)).fetchone()
            temp = r["t"] if r else None
            sch = db.execute("SELECT * FROM schedules WHERE device_id=?", (d["id"],)).fetchall()
            rules = {x["ch"]: x for x in db.execute("SELECT * FROM rules WHERE device_id=?", (d["id"],))}
            for c in db.execute("SELECT * FROM channels WHERE device_id=?", (d["id"],)).fetchall():
                want = desired(c["kind"], [s for s in sch if s["ch"] == c["key"]], rules.get(c["key"]),
                               temp, now, bool(c["state"]))
                if want is None or want == bool(c["state"]) or c["kind"] in ("door_open", "door_close"):
                    continue
                ok, _ = command(app, d, c, want, "auto", now)
                sent.append((d["code"], c["key"], want, ok))
        db.commit()
    return sent
