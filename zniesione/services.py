"""Logika bez zależności od Flaska: harmonogramy, termostat, YAML, adresy IP, silnik sterowania."""
import math
import os
import re
import urllib.request
from datetime import datetime, time, timedelta, timezone

from . import catalog as cat
from . import db as dbm

OFFLINE_S = 300
RETRY_S = 30          # odstęp ponowienia po błędzie urządzenia
DAY_S = 86400
MODES = ("time", "sunrise", "sunset")
KEEP = object()
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


def sun_times(lat, lon, d):
    """Wschód i zachód słońca w dniu d (algorytm NOAA, dokładność ok. 1 min).
    Zwraca parę datetime w UTC albo None, gdy słońce tego dnia nie wschodzi lub nie zachodzi."""
    g = 2 * math.pi / 365 * (d.timetuple().tm_yday - 1)
    eq = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                   - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    la = math.radians(lat)
    cos_ha = (math.cos(math.radians(90.833)) / max(math.cos(la) * math.cos(decl), 1e-9)
              - math.tan(la) * math.tan(decl))
    if not -1 <= cos_ha <= 1:
        return None
    ha = math.degrees(math.acos(cos_ha))
    mid = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    return tuple(mid + timedelta(minutes=720 - 4 * (lon + k * ha) - eq) for k in (1, -1))


def local_sun(lat, lon, d):
    """sun_times w czasie lokalnym serwera, porównywalne z datetime.now()."""
    st = sun_times(lat, lon, d)
    return st and tuple(t.astimezone().replace(tzinfo=None) for t in st)


def farm_sun(lat, lon):
    return (lambda day: local_sun(lat, lon, day)) if lat is not None and lon is not None else None


def _get(s, k, default):
    return s[k] if k in s.keys() and s[k] is not None else default


def _point(mode, hm, off, day, sun):
    if mode == "time":
        return _m(hm) * 60
    st = sun(day) if sun else None
    if not st:
        return None
    t = st[0 if mode == "sunrise" else 1]
    return min(max(t.hour * 3600 + t.minute * 60 + t.second + off * 60, 0), DAY_S - 60)


def window(s, day, sun=None):
    """Okno harmonogramu w dniu `day`: (początek, koniec) w sekundach od północy, koniec może wypaść po północy.
    sun(day) zwraca lokalny (wschód, zachód) albo None."""
    a = _point(_get(s, "mode", "time"), s["t_on"], _get(s, "offset_min", 0), day, sun)
    if a is None:
        return None
    if _get(s, "duration_s", None):
        return a, a + s["duration_s"]
    b = _point(_get(s, "off_mode", "time"), s["t_off"], _get(s, "off_offset_min", 0), day, sun)
    if b is None or a == b:
        return None
    return a, b if b > a else b + DAY_S


def sched_window(s, now, sun=None):
    """Trwające okno (początek, koniec) jako datetime albo None. O dniach tygodnia decyduje dzień rozpoczęcia."""
    for back in (0, 1):
        day = (now - timedelta(days=back)).date()
        w = window(s, day, sun)
        if w and day_ok(s["days"], day.weekday()):
            mid = datetime.combine(day, time())
            start, end = mid + timedelta(seconds=w[0]), mid + timedelta(seconds=w[1])
            if start <= now < end:
                return start, end
    return None


def sched_active(s, now, sun=None):
    return sched_window(s, now, sun) is not None


def thermo(kind, temp, thr, cur):
    """Termostat z histerezą 1 °C. Wentylacja: włącz powyżej progu. Grzanie: włącz poniżej progu."""
    if kind in cat.COOL:
        return True if temp > thr else False if temp <= thr - 1 else cur
    return True if temp < thr else False if temp >= thr + 1 else cur


def rule_on(kind, rule, temp):
    return bool(rule and rule["enabled"] and temp is not None and kind in cat.COOL | cat.HEAT)


def desired(kind, scheds, rule, temp, now, cur, sun=None):
    if rule_on(kind, rule, temp):
        return thermo(kind, temp, rule["threshold"], cur)
    act = [s for s in scheds if s["enabled"]]
    if act:
        return any(sched_active(s, now, sun) for s in act)
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
    base = os.environ.get("DEVICE_BASE") or f"http://{dev['ip']}"  # DEVICE_BASE: atrapa urządzenia w testach
    url = f"{base}/switch/{ch}/turn_{'on' if state else 'off'}"
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=b"", method="POST"), timeout=4)
        return True, None
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def log(db, dev_id, ch, state, src, ok, now):
    db.execute("INSERT INTO log(device_id,ch,state,src,ok,at) VALUES(?,?,?,?,?,?)",
               (dev_id, ch, int(state), src, int(ok), now.isoformat()))


def command(app, dev, ch, state, src, now=None, off_at=KEEP):
    """Wysyła polecenie i zapisuje stan. off_at: zaplanowane wyłączenie (datetime) przy włączeniu; wyłączenie je czyści."""
    now = now or datetime.now()
    ok, err = app.config["SEND"](dict(dev), ch["key"], state)
    db = dbm.get()
    log(db, dev["id"], ch["key"], state, src, ok, now)
    if ok:
        if not state:
            off_at = None
        if off_at is KEEP:
            db.execute("UPDATE channels SET state=? WHERE id=?", (int(state), ch["id"]))
        else:
            db.execute("UPDATE channels SET state=?, off_at=? WHERE id=?",
                       (int(state), off_at and off_at.isoformat(), ch["id"]))
    db.commit()
    return ok, err


def door(app, dev, action, src, now=None, out=None):
    """Impuls silnika drzwi: najpierw wyłącza przeciwny przekaźnik, potem włącza właściwy na door_run_s sekund.
    Wyłączenie wykonuje silnik na podstawie channels.off_at, więc przetrwa restart aplikacji i jest ponawiane."""
    now = now or datetime.now()
    db = dbm.get()
    ch = {c["kind"]: c for c in db.execute("SELECT * FROM channels WHERE device_id=? AND kind IN "
                                           "('door_open','door_close') ORDER BY id", (dev["id"],))}
    tgt, opp = (ch.get("door_open"), ch.get("door_close")) if action == "open" else \
        (ch.get("door_close"), ch.get("door_open"))
    if not tgt:
        return False, "Brak przekaźnika drzwi dla tej czynności"

    def run(c, state, **kw):
        ok, e = command(app, dev, c, state, src, now, **kw)
        if out is not None:
            out.append((dev["code"], c["key"], state, ok))
        return ok, e
    if opp and opp["state"]:
        ok, e = run(opp, False)
        if not ok:
            return False, e
    ok, e = run(tgt, True, off_at=now + timedelta(seconds=dev["door_run_s"]))
    if ok:
        db.execute("UPDATE devices SET door=? WHERE id=?", ("open" if action == "open" else "closed", dev["id"]))
    else:  # przekaźnik mógł zadziałać mimo błędu odpowiedzi: silnik i tak go wyłączy
        db.execute("UPDATE channels SET state=1, off_at=? WHERE id=?", (now.isoformat(), tgt["id"]))
    db.commit()
    return ok, e


def tick(app, now=None):
    """Jeden obieg silnika. Kolejno: zaplanowane wyłączenia (czas trwania, impulsy drzwi), harmonogram drzwi,
    pozostałe kanały. Silnik reaguje na zmianę stanu pożądanego (kolumna want), więc ręczna zmiana obowiązuje
    do następnej zmiany w harmonogramie lub termostacie. Nieudane polecenie nie zapisuje want i jest ponawiane
    po RETRY_S sekundach. Stan jest w bazie, więc restart aplikacji niczego nie gubi."""
    now = now or datetime.now()
    sent = []
    backoff = app.extensions.setdefault("zniesione_backoff", {})
    with app.app_context():
        db = dbm.get()
        for d in db.execute("SELECT d.*, f.lat, f.lon FROM devices d LEFT JOIN farms f ON f.id=d.farm_id "
                            "WHERE d.stage=3 AND d.online=1").fetchall():
            if d["last_seen"] and (now - datetime.fromisoformat(d["last_seen"])).total_seconds() > OFFLINE_S:
                db.execute("UPDATE devices SET online=0 WHERE id=?", (d["id"],))
                continue
            if backoff.get(d["id"], now) > now:
                continue
            n = len(sent)
            _tick_device(app, db, d, now, sent)
            if any(not x[3] for x in sent[n:]):
                backoff[d["id"]] = now + timedelta(seconds=RETRY_S)
        db.commit()
    return sent


def _tick_device(app, db, d, now, sent):
    def run(c, state, src, **kw):
        ok, _ = command(app, d, c, state, src, now, **kw)
        sent.append((d["code"], c["key"], state, ok))
        return ok

    def chans():
        return db.execute("SELECT * FROM channels WHERE device_id=? ORDER BY id", (d["id"],)).fetchall()
    for c in chans():
        if c["state"] and c["off_at"] and datetime.fromisoformat(c["off_at"]) <= now and not run(c, False, "timer"):
            return
    sun = farm_sun(d["lat"], d["lon"])
    sch = db.execute("SELECT * FROM schedules WHERE device_id=?", (d["id"],)).fetchall()
    kinds = {c["key"]: c["kind"] for c in chans()}
    ds = [s for s in sch if s["enabled"] and kinds.get(s["ch"]) == "door_open"]
    if ds:
        want = any(sched_active(s, now, sun) for s in ds)
        if d["door_want"] is None or bool(d["door_want"]) != want:
            if d["door"] != ("open" if want else "closed"):
                ok, _ = door(app, d, "open" if want else "close", "schedule", now, sent)
                if not ok:
                    return
            db.execute("UPDATE devices SET door_want=? WHERE id=?", (int(want), d["id"]))
    elif d["door_want"] is not None:
        db.execute("UPDATE devices SET door_want=NULL WHERE id=?", (d["id"],))
    r = db.execute("SELECT t FROM readings WHERE device_id=? ORDER BY id DESC LIMIT 1", (d["id"],)).fetchone()
    temp = r["t"] if r else None
    rules = {x["ch"]: x for x in db.execute("SELECT * FROM rules WHERE device_id=?", (d["id"],))}
    for c in chans():
        if c["kind"] in cat.DOORS:
            continue
        cs = [s for s in sch if s["ch"] == c["key"]]
        want = desired(c["kind"], cs, rules.get(c["key"]), temp, now, bool(c["state"]), sun)
        if want is None:
            if c["want"] is not None:
                db.execute("UPDATE channels SET want=NULL WHERE id=?", (c["id"],))
            continue
        if c["want"] is not None and bool(c["want"]) == want:
            continue
        if bool(c["state"]) != want:
            src, kw = ("thermostat" if rule_on(c["kind"], rules.get(c["key"]), temp) else "schedule"), {}
            if want and src == "schedule":  # czas trwania: wyłączenie zapisane w bazie
                ends = [w[1] for s in cs if s["enabled"] and _get(s, "duration_s", None)
                        and (w := sched_window(s, now, sun))]
                if ends:
                    kw["off_at"] = max(ends)
            if not run(c, want, src, **kw):
                return
        db.execute("UPDATE channels SET want=? WHERE id=?", (int(want), c["id"]))
