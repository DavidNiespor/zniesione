"""Firmware z panelu admina: prawdziwy proces deploy/esphome-builder/builder.py z atrapą ESPHome (bez kompilatora)."""
import os
import socket
import subprocess
import sys
import time

import pytest

from conftest import online_device

ROOT = os.path.join(os.path.dirname(__file__), "..")
FAKE = '''import os, sys
args = sys.argv[1:]
cfg = args[-1]; name = os.path.basename(cfg)[:-5]
print("INFO Reading configuration", cfg)
assert open(os.path.join(os.path.dirname(cfg), "secrets.yaml")).read().count("wifi_ssid")
if args[0] == "compile":
    d = os.path.join(os.path.dirname(cfg), ".esphome", "build", name, ".pioenvs", name)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "firmware.factory.bin"), "wb").write(b"\\xe9FIRMWARE-" + name.encode())
    print("INFO Successfully compiled program.")
else:
    print("INFO Uploading to", args[args.index("--device") + 1]); print("INFO OTA successful")
'''


@pytest.fixture
def builder(tmp_path):
    fake = tmp_path / "fake_esphome.py"
    fake.write_text(FAKE)
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    env = {**os.environ, "BUILDER_TOKEN": "tok", "CONFIG_DIR": str(tmp_path / "cfg"), "PORT": str(port),
           "ESPHOME_CMD": f'"{sys.executable}" "{fake}"'}
    p = subprocess.Popen([sys.executable, os.path.join(ROOT, "deploy", "esphome-builder", "builder.py")], env=env)
    url = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield url
    p.kill()


def wait_done(admin, did):
    for _ in range(100):
        st = admin.get(f"/api/admin/devices/{did}/firmware").get_json()
        if st["status"] in ("ok", "error"):
            return st
        time.sleep(0.1)
    raise AssertionError(st)


def test_compile_usb_manifest_and_ota_upload(app, admin, farmer, builder):
    app.config.update(BUILDER_URL=builder, BUILDER_TOKEN="tok")
    from zniesione import services as sv
    app.config["BUILDER_CALL"] = sv.builder_call
    did, _ = online_device(app, admin, farmer, model="tr4")
    url = f"/api/admin/devices/{did}/firmware"
    assert farmer[0].post(url, {"action": "compile"}).status_code == 403
    assert admin.get(url).get_json() == {"status": "none"}
    r = admin.post(url, {"action": "compile"})
    assert r.status_code == 409 and "Wi-Fi" in r.get_json()["error"]
    admin.patch(f"/api/admin/devices/{did}", {"wifi_ssid": "Kurnik", "wifi_password": "haslo1234"})
    assert admin.post(url, {"action": "flash"}).status_code == 400
    assert admin.post(url, {"action": "compile"}).status_code == 201
    st = wait_done(admin, did)
    assert st["status"] == "ok" and st["binary"] and "Successfully compiled" in st["log"]
    code = admin.get("/api/admin/devices").get_json()[0]["code"]
    b = admin.get(f"/api/admin/devices/{did}/firmware.bin")
    assert b.status_code == 200 and b.data == b"\xe9FIRMWARE-" + code.encode()
    m = admin.get(f"/api/admin/devices/{did}/manifest.json").get_json()
    assert m["builds"][0]["chipFamily"] == "ESP32" and m["builds"][0]["parts"][0]["path"].endswith("/firmware.bin")
    assert admin.post(url, {"action": "upload"}).status_code == 201                       # OTA przez WireGuard
    st = wait_done(admin, did)
    assert st["status"] == "ok" and "Uploading to 10.8.0.10" in st["log"]


def test_firmware_unavailable_cases(app, admin, farmer):
    c, _ = farmer
    sh = c.post("/api/my/device-orders", {"model": "shp"}).get_json()["id"]
    tr = c.post("/api/my/device-orders", {"model": "tr4"}).get_json()["id"]
    assert admin.post(f"/api/admin/devices/{tr}/firmware", {"action": "compile"}).status_code == 503   # brak BUILDER_URL
    app.config.update(BUILDER_URL="http://127.0.0.1:1", BUILDER_TOKEN="tok")
    assert admin.post(f"/api/admin/devices/{sh}/firmware", {"action": "compile"}).status_code == 409   # Shelly
    admin.patch(f"/api/admin/devices/{tr}", {"wifi_ssid": "K", "wifi_password": "haslo1234"})
    assert admin.post(f"/api/admin/devices/{tr}/firmware", {"action": "upload"}).status_code == 409    # offline
    r = admin.post(f"/api/admin/devices/{tr}/firmware", {"action": "compile"})
    assert r.status_code == 502 and "niedostępny" in r.get_json()["error"]
