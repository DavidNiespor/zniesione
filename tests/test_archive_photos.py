"""Archiwum z arkusza Google (tylko podgląd), zdjęcia gospodarstwa i budynki ze stadami w sklepie."""
import io
from datetime import date, timedelta

from conftest import H, Client

# dane zmyślone, układ kolumn jak w arkuszu: sprzedaż w kolumnach z ceną za sztukę w nagłówku
SHEET = """,,,99,1,"50,00%",,,,,,,"x",,,,,
Dzień = 01.01.2025,Ilość Kur,Ilość Kwok,Ilość Jajek,Straty,Nieśność ,MAGAZYN,Zamówienia,DOM,"1,2",1,0,Suma,WYPŁACONO,Typ Wydatku,Wydatki,Podsumowanie,Column 18
01.08.2024,10,2,6,,"75,00%",,,,,,,"0,00 zł",,,,"0,00 zł",
02.08.2024,10,2,,,,,,,,,,"0,00 zł",,,,"0,00 zł",
03.08.2024,10,2,8,1,"100,00%",20,,4,10,5,3,"17,00 zł",TAK,Pasza,"1 250,50 zł","-1 233,50 zł",
04.09.2024,12,0,0,,"0,00%",,,,,,,"0,00 zł",,,,"-1 233,50 zł",
,10,0,8,,"80%",30,,,,,,"0,00 zł",,,,"x",
01.01.2099,10,,,,,,,,,,,"0,00 zł",,,,"0,00 zł",
"""


def up(c, url, data):
    return c.c.post(url, data=data, content_type="multipart/form-data", headers=H)


def test_archive_import_summary_and_isolation(app, farmer, farmer2):
    c, _ = farmer
    assert c.get("/api/my/archive").get_json() == {"empty": True}
    assert up(c, "/api/my/archive", {"file": (io.BytesIO(b"a,b\n1,2\n"), "x.csv")}).status_code == 400
    r = up(c, "/api/my/archive", {"file": (io.BytesIO(SHEET.encode("utf-8")), "Chicken.csv")})
    assert r.status_code == 201 and r.get_json() == {"days": 3, "first": "2024-08-01", "last": "2024-09-04"}
    a = c.get("/api/my/archive").get_json()
    t = a["totals"]
    assert (t["eggs"], t["losses"], t["home"], t["sold"], t["given"]) == (14, 1, 4, 15, 3)
    assert (t["revenue"], t["expenses"], t["profit"]) == (17.0, 1250.5, -1233.5)
    assert a["by_price"] == {"0.0": 3, "1.0": 5, "1.2": 10}
    aug = a["monthly"][0]
    assert (aug["month"], aug["eggs"], aug["logged"], aug["laying"]) == ("2024-08", 14, 2, 87.5)   # 14 jaj / (8 + 8) niosek
    assert a["monthly"][1]["laying"] == 0.0 and a["expenses"] == [{"day": "2024-08-03", "type": "Pasza", "amount": 1250.5}]
    assert a["name"] == "Chicken.csv" and len(a["days_list"]) == 3
    assert farmer2[0].get("/api/my/archive").get_json() == {"empty": True}
    # archiwum nie zmienia stanów jaj portalu
    assert c.get("/api/my/eggs?days=1").get_json()["stock"]["eggs"] == 0
    up(c, "/api/my/archive", {"file": (io.BytesIO(SHEET.encode("cp1250")), "znowu.csv")})            # CSV z Excela, ponowny import
    assert c.get("/api/my/archive").get_json()["days"] == 3
    assert c.delete("/api/my/archive").status_code == 200 and c.get("/api/my/archive").get_json() == {"empty": True}


PNG = bytes([137, 80, 78, 71, 13, 10, 26, 10]) + b"\x00" * 40


def test_photos_buildings_and_flocks_in_shop(app, farmer, farmer2, anon):
    c, fid = farmer
    b = c.post("/api/my/buildings", {"name": "Kurnik A"}).get_json()
    fl = c.post("/api/my/flocks", {"name": "Zielononóżki", "birds": 12, "breed": "Zielononóżka", "building_id": b["id"]}).get_json()
    c.post("/api/my/flocks", {"name": "Bez budynku", "birds": 3})
    assert up(c, "/api/my/photos", {"file": (io.BytesIO(b"<svg>"), "x.svg")}).status_code == 400
    assert up(c, "/api/my/photos", {"file": (io.BytesIO(PNG), "a.png"), "building_id": "999"}).status_code == 400
    other = farmer2[0].post("/api/my/buildings", {"name": "Obcy"}).get_json()
    assert up(c, "/api/my/photos", {"file": (io.BytesIO(PNG), "a.png"), "building_id": str(other["id"])}).status_code == 400
    pb = up(c, "/api/my/photos", {"file": (io.BytesIO(PNG), "a.png"), "building_id": str(b["id"]), "caption": "Wybieg"}).get_json()
    pf = up(c, "/api/my/photos", {"file": (io.BytesIO(PNG), "b.png"), "flock_id": str(fl["id"])}).get_json()
    pg = up(c, "/api/my/photos", {"file": (io.BytesIO(PNG), "c.png")}).get_json()
    shop = anon.get(f"/api/farms/{fid}").get_json()
    assert [p["id"] for p in shop["photos"]] == [pg["id"]]
    k = shop["buildings"][0]
    assert (k["name"], k["photos"][0]["caption"], k["flocks"][0]["name"], k["flocks"][0]["birds"]) == ("Kurnik A", "Wybieg", "Zielononóżki", 12)
    assert k["flocks"][0]["photos"][0]["id"] == pf["id"] and [x["name"] for x in shop["flocks"]] == ["Bez budynku"]
    r = anon.get(pb["url"])
    assert r.status_code == 200 and r.mimetype == "image/png" and r.headers["X-Content-Type-Options"] == "nosniff"
    assert farmer2[0].delete(f"/api/my/photos/{pb['id']}").status_code == 404
    assert c.patch(f"/api/my/photos/{pb['id']}", {"caption": "Kurnik od frontu"}).get_json()["caption"] == "Kurnik od frontu"
    assert c.delete(f"/api/my/photos/{pb['id']}").status_code == 200 and anon.get(pb["url"]).status_code == 404


def test_building_egg_summary_and_device_building(app, admin, farmer):
    from conftest import online_device
    c, _ = farmer
    b = c.post("/api/my/buildings", {"name": "Kurnik A"}).get_json()
    c.post("/api/my/flocks", {"name": "Nioski", "birds": 10, "building_id": b["id"]})
    c.post("/api/my/eggs", {"kind": "collect", "eggs": 7, "building_id": b["id"]})
    c.post("/api/my/eggs", {"kind": "collect", "eggs": 20, "building_id": b["id"], "date": (date.today() - timedelta(days=20)).isoformat()})
    x = c.get("/api/my/buildings").get_json()[0]
    assert (x["eggs_7d"], x["eggs_30d"], x["laying_7d"]) == (7, 27, 10.0)
    d, _ = online_device(app, admin, farmer)
    assert c.patch(f"/api/my/devices/{d}", {"building_id": b["id"]}).status_code == 200
    assert c.get("/api/my/buildings").get_json()[0]["devices"][0]["id"] == d
    assert [x["building_id"] for x in c.get("/api/my/devices").get_json()] == [b["id"]]
