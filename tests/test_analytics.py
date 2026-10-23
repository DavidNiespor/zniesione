"""Kalendarz zamówień, analityka, eksport CSV farmy i kopia zapasowa całej bazy w panelu admina."""
import io
import zipfile
from datetime import date, timedelta

from conftest import H, Client


def test_order_due_date_and_calendar(app, farmer, anon):
    c, fid = farmer
    c.put("/api/my/farm", {"price10": 12, "stock": 0})
    c.post("/api/my/eggs", {"kind": "collect", "eggs": 100, "sorted": True})
    c.post("/api/my/eggs/allocation", {"offer_packs": 5, "reserved": 0})
    d = (date.today() + timedelta(days=2)).isoformat()
    for bad in ("2020-01-01", (date.today() + timedelta(days=61)).isoformat(), "jutro"):
        assert anon.post(f"/api/farms/{fid}/orders", {"name": "Jan", "phone": "600111222", "qty": 1, "due_date": bad}).status_code == 400
    oid = anon.post(f"/api/farms/{fid}/orders", {"name": "Jan", "phone": "600111222", "qty": 1, "due_date": d}).get_json()["id"]
    cid = c.post("/api/my/clients", {"name": "Zofia"}).get_json()["id"]
    c.post("/api/my/subscriptions", {"client_id": cid, "eggs": 30, "every_days": 7, "next_date": date.today().isoformat()})
    c.post("/api/my/sales", {"eggs": 10, "method": "cash"})
    cal = c.get(f"/api/my/calendar?month={d[:7]}").get_json()["days"]
    assert any(i["type"] == "order" and i["id"] == oid and i["due"] for i in cal[d])
    today = date.today().isoformat()
    if today[:7] == d[:7]:
        types = {i["type"] for i in cal[today]}
        assert {"sub", "sales", "collect"} <= types
    assert c.patch(f"/api/my/orders/{oid}", {"due_date": "2026-13-01"}).status_code == 400
    assert c.patch(f"/api/my/orders/{oid}", {"due_date": ""}).get_json()["due_date"] == ""
    assert farmer2_cannot(app, oid)
    assert c.get("/api/my/calendar?month=2026-1").status_code == 400


def farmer2_cannot(app, oid):
    c = Client(app)
    c.post("/api/auth/register", {"email": "z@x.pl", "password": "haslo12345", "farm_name": "Z", "city": "Opole", "zip": "45-001"})
    return c.patch(f"/api/my/orders/{oid}", {"due_date": ""}).status_code == 404


def test_analytics_series_and_people(app, farmer):
    c, _ = farmer
    c.post("/api/my/flocks", {"name": "Nioski", "birds": 20})
    c.post("/api/my/eggs", {"kind": "collect", "eggs": 15, "sorted": True})
    c.post("/api/my/eggs", {"kind": "collect", "eggs": 18, "sorted": True, "date": (date.today() - timedelta(days=1)).isoformat()})
    c.post("/api/my/sales", {"eggs": 10, "method": "cash", "price": 1})
    c.post("/api/my/expenses", {"date": date.today().isoformat(), "category": "Prąd", "name": "Prąd", "total": 40})
    a = c.get("/api/my/analytics?days=7").get_json()
    assert len(a["daily"]) == 7 and a["daily"][-1]["date"] == date.today().isoformat()
    assert (a["daily"][-1]["collected"], a["daily"][-1]["laying"], a["daily"][-2]["collected"]) == (15, 75.0, 18)
    assert a["totals"]["collected"] == 33 and a["totals"]["sold"] == 10
    assert a["monthly"][-1]["expenses"] == 40 and a["monthly"][-1]["revenue"] == a["totals"]["revenue"]
    assert a["people"][0]["collected"] == 33 and a["people"][0]["sales"] == 1
    assert c.get("/api/my/analytics?days=3").status_code == 400


def test_farm_export_zip_has_only_own_data(app, farmer, farmer2):
    c, _ = farmer
    c.post("/api/my/clients", {"name": "Zofia Kowalska"})
    farmer2[0].post("/api/my/clients", {"name": "Obcy Klient"})
    r = c.get("/api/my/export.zip")
    z = zipfile.ZipFile(io.BytesIO(r.data))
    assert {"clients.csv", "sales.csv", "eggs.csv", "recipe_items.csv"} <= set(z.namelist())
    txt = z.read("clients.csv").decode("utf-8-sig")
    assert "Zofia Kowalska" in txt and "Obcy" not in txt
    assert Client(app).get("/api/my/export.zip").status_code == 401


def test_admin_backup_download_and_restore(app, admin, farmer):
    c, _ = farmer
    c.post("/api/my/clients", {"name": "Przed kopią"})
    assert c.get("/api/admin/backup").status_code == 403
    data = admin.get("/api/admin/backup").data
    assert data[:16] == b"SQLite format 3\x00"
    c.post("/api/my/clients", {"name": "Po kopii"})
    up = lambda d: admin.c.post("/api/admin/restore", data=d, content_type="multipart/form-data", headers=H)
    assert up({"file": (io.BytesIO(data), "k.db")}).status_code == 400                         # bez potwierdzenia
    assert up({"file": (io.BytesIO(b"to nie baza"), "k.db"), "confirm": "PRZYWRÓĆ"}).status_code == 400
    assert up({"file": (io.BytesIO(data), "k.db"), "confirm": "PRZYWRÓĆ"}).status_code == 200
    assert admin.get("/api/me").status_code == 401                                           # sesja wyczyszczona
    names = [x["name"] for x in c.get("/api/my/clients").get_json()]
    assert "Przed kopią" in names and "Po kopii" not in names
