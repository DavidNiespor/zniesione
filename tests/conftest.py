import pytest
from werkzeug.security import generate_password_hash

from zniesione import create_app, db as dbm

H = {"X-Requested-With": "zniesione"}


class Client:
    def __init__(self, app):
        self.c = app.test_client()

    def req(self, m, url, json=None, **kw):
        return getattr(self.c, m)(url, json=json, headers={**H, **kw.pop("headers", {})}, **kw)

    def get(self, u, **k):
        return self.c.get(u, **k)

    def post(self, u, j=None, **k):
        return self.req("post", u, j, **k)

    def put(self, u, j=None):
        return self.req("put", u, j)

    def patch(self, u, j=None):
        return self.req("patch", u, j)

    def delete(self, u):
        return self.req("delete", u)


@pytest.fixture
def app(tmp_path):
    a = create_app({"DATABASE": str(tmp_path / "t.db"), "TESTING": True, "SECRET_KEY": "t"})
    a.sent = []

    def fake(dev, ch, state):
        a.sent.append((dev["code"], ch, state))
        return a.config.get("SEND_OK", True), None if a.config.get("SEND_OK", True) else "timeout"
    a.config["SEND"] = fake
    with a.app_context():
        dbm.get().execute("INSERT INTO users(email,pw,role) VALUES('admin@x.pl',?,'admin')", (generate_password_hash("adminadmin"),))
        dbm.get().commit()
    return a


@pytest.fixture
def anon(app):
    return Client(app)


def make(app, email, farm="Farma"):
    c = Client(app)
    r = c.post("/api/auth/register", {"email": email, "password": "haslo12345", "farm_name": farm, "city": "Opole", "zip": "45-001"})
    assert r.status_code == 201
    return c, r.get_json()["farm_id"]


@pytest.fixture
def farmer(app):
    return make(app, "a@x.pl", "Farma A")


@pytest.fixture
def farmer2(app):
    return make(app, "b@x.pl", "Farma B")


@pytest.fixture
def admin(app):
    c = Client(app)
    assert c.post("/api/auth/login", {"email": "admin@x.pl", "password": "adminadmin"}).status_code == 200
    return c


def online_device(app, admin, farmer, model="trs3", kinds=None):
    """Zamawia sterownik, prowadzi go do etapu 3 i oznacza jako online (odczyt)."""
    c, fid = farmer
    did = c.post("/api/my/device-orders", {"model": model, "addr": "kurnik 1"}).get_json()["id"]
    for s in (1, 2, 3):
        assert admin.patch(f"/api/admin/devices/{did}", {"stage": s}).status_code == 200
    key = None
    with app.app_context():
        key = dbm.get().execute("SELECT api_key FROM devices WHERE id=?", (did,)).fetchone()[0]
    assert Client(app).post("/api/device/readings", {"t": 20, "h": 60}, headers={"X-Api-Key": key}).status_code == 200
    for k, kind in (kinds or {}).items():
        assert c.patch(f"/api/my/devices/{did}/channels/{k}", {"kind": kind}).status_code == 200
    return did, key
