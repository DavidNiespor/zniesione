"""Pełny stack: klucze i konfiguracja serwera WireGuard tworzone przez portal, secrets.yaml, kopie zapasowe."""
import base64
import os
import sqlite3
from datetime import datetime, timedelta

from conftest import Client
from zniesione import backup, create_app, services as sv


def test_x25519_rfc7748_vectors():
    # RFC 7748, rozdział 6.1: klucz publiczny Alice i Boba z klucza prywatnego
    base = (9).to_bytes(32, "little")
    alice = bytes.fromhex("77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a")
    bob = bytes.fromhex("5dab087e624a8a4b79e17f8b83800ee66f3bb1292618b6fd1c2f8b27ff88e0eb")
    assert sv.x25519(alice, base).hex() == "8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a"
    assert sv.x25519(bob, base).hex() == "de9edb7d7b7dc1b4d35b61c2ece435373f8343c85b78674dadfc7e146f882b4f"
    assert sv.x25519(alice, sv.x25519(bob, base)) == sv.x25519(bob, sv.x25519(alice, base))  # wspólny sekret
    priv, pub = sv.wg_keypair()
    assert len(base64.b64decode(priv)) == 32 and sv.x25519(base64.b64decode(priv), base) == base64.b64decode(pub)


def test_portal_writes_wireguard_server_config(tmp_path):
    conf = tmp_path / "wireguard" / "wg0.conf"
    a = create_app({"DATABASE": str(tmp_path / "w.db"), "TESTING": True, "WG_CONF": str(conf)})
    assert "[Interface]" in conf.read_text() and "Address = 10.8.0.1/24" in conf.read_text() and "[Peer]" not in conf.read_text()
    if os.name != "nt":
        assert oct(conf.stat().st_mode)[-3:] == "600"
    c = Client(a)
    c.post("/api/auth/register", {"email": "r@x.pl", "password": "haslo12345", "farm_name": "F"})
    d1 = c.post("/api/my/device-orders", {"model": "tr4"}).get_json()["id"]
    c.post("/api/my/device-orders", {"model": "trs3", "tunnel": "ts"})      # Tailscale: bez wpisu w WireGuard
    text = conf.read_text()
    dev = next(x for x in c.get("/api/my/devices").get_json() if x["id"] == d1)
    assert text.count("[Peer]") == 1 and f"# {dev['code']}" in text and f"AllowedIPs = {dev['ip']}/32" in text
    assert "wg_pub" not in str(c.get("/api/my/devices").get_json())        # klucze nie wychodzą przez API rolnika
    server_priv = text.split("PrivateKey = ")[1].split()[0]
    create_app({"DATABASE": str(tmp_path / "w.db"), "TESTING": True, "WG_CONF": str(conf)})   # restart
    assert conf.read_text().split("PrivateKey = ")[1].split()[0] == server_priv                # te same klucze


def test_admin_gets_esphome_secrets_matching_server(tmp_path):
    from werkzeug.security import generate_password_hash
    from zniesione import db as dbm
    conf = tmp_path / "wg0.conf"
    a = create_app({"DATABASE": str(tmp_path / "s.db"), "TESTING": True, "WG_CONF": str(conf)})
    with a.app_context():
        dbm.get().execute("INSERT INTO users(email,pw,role) VALUES('admin@x.pl',?,'admin')", (generate_password_hash("adminadmin"),))
        dbm.get().commit()
    adm, farmer = Client(a), Client(a)
    adm.post("/api/auth/login", {"email": "admin@x.pl", "password": "adminadmin"})
    farmer.post("/api/auth/register", {"email": "r@x.pl", "password": "haslo12345", "farm_name": "F"})
    did = farmer.post("/api/my/device-orders", {"model": "tr4"}).get_json()["id"]
    assert farmer.get(f"/api/admin/devices/{did}/secrets").status_code == 403
    s = adm.get(f"/api/admin/devices/{did}/secrets").get_data(as_text=True)
    priv = s.split('wg_privkey: "')[1].split('"')[0]
    pub = base64.b64encode(sv.x25519(base64.b64decode(priv), (9).to_bytes(32, "little"))).decode()
    assert f"PublicKey = {pub}" in conf.read_text()                          # klucz sterownika zgadza się z serwerem
    server_pub = s.split('wg_server_pubkey: "')[1].split('"')[0]
    server_priv = conf.read_text().split("PrivateKey = ")[1].split()[0]
    assert base64.b64encode(sv.x25519(base64.b64decode(server_priv), (9).to_bytes(32, "little"))).decode() == server_pub
    assert adm.get("/api/admin/devices/999/secrets").status_code == 404
    assert "wg_priv" not in adm.get("/api/admin/config").get_data(as_text=True)


def test_backup_is_consistent_and_old_copies_are_removed(tmp_path):
    db = tmp_path / "z.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE t(x)"), con.execute("INSERT INTO t VALUES (42)"), con.commit()
    out = tmp_path / "kopie"
    old = backup.backup_once(str(db), str(out), 14, now=datetime.now() - timedelta(days=20))
    (out / "notatka.txt").write_text("zostaw")
    new = backup.backup_once(str(db), str(out), 14)
    assert not os.path.exists(old) and os.path.exists(out / "notatka.txt")
    assert sqlite3.connect(new).execute("SELECT x FROM t").fetchone() == (42,)
    con.close()
