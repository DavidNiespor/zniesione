import sqlite3
from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, pw TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN('admin','farmer')), farm_id INTEGER);
CREATE TABLE IF NOT EXISTS farms(id INTEGER PRIMARY KEY, name TEXT NOT NULL, city TEXT DEFAULT '', zip TEXT DEFAULT '',
  breed TEXT DEFAULT '', descr TEXT DEFAULT '', price10 REAL DEFAULT 0, stock INTEGER DEFAULT 0, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY, farm_id INTEGER NOT NULL, name TEXT NOT NULL, phone TEXT NOT NULL,
  qty INTEGER NOT NULL, mode TEXT NOT NULL, pickup TEXT NOT NULL, total REAL NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS devices(id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, model TEXT NOT NULL, farm_id INTEGER,
  tunnel TEXT NOT NULL, ip TEXT UNIQUE NOT NULL, stage INTEGER NOT NULL DEFAULT 0, api_key TEXT UNIQUE NOT NULL,
  addr TEXT DEFAULT '', online INTEGER DEFAULT 0, last_seen TEXT);
CREATE TABLE IF NOT EXISTS channels(id INTEGER PRIMARY KEY, device_id INTEGER NOT NULL, key TEXT NOT NULL, name TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'other', state INTEGER NOT NULL DEFAULT 0, UNIQUE(device_id,key));
CREATE TABLE IF NOT EXISTS schedules(id INTEGER PRIMARY KEY, device_id INTEGER NOT NULL, ch TEXT NOT NULL,
  t_on TEXT NOT NULL, t_off TEXT NOT NULL, days TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS rules(id INTEGER PRIMARY KEY, device_id INTEGER NOT NULL, ch TEXT NOT NULL,
  threshold REAL NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, UNIQUE(device_id,ch));
CREATE TABLE IF NOT EXISTS readings(id INTEGER PRIMARY KEY, device_id INTEGER NOT NULL, t REAL, h REAL, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS log(id INTEGER PRIMARY KEY, device_id INTEGER NOT NULL, ch TEXT NOT NULL, state INTEGER NOT NULL,
  src TEXT NOT NULL, ok INTEGER NOT NULL, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS config(k TEXT PRIMARY KEY, v TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS flocks(id INTEGER PRIMARY KEY, farm_id INTEGER NOT NULL, name TEXT NOT NULL,
  birds INTEGER NOT NULL DEFAULT 0, breed TEXT NOT NULL DEFAULT '', since TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS eggs(id INTEGER PRIMARY KEY, farm_id INTEGER NOT NULL, kind TEXT NOT NULL,
  packs INTEGER NOT NULL DEFAULT 0, at TEXT NOT NULL, sale_id INTEGER, eggs INTEGER NOT NULL DEFAULT 0,
  damaged INTEGER NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS clients(id INTEGER PRIMARY KEY, farm_id INTEGER NOT NULL, name TEXT NOT NULL,
  phone TEXT NOT NULL DEFAULT '', phone_key TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '',
  address TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '', price10 REAL, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sales(id INTEGER PRIMARY KEY, farm_id INTEGER NOT NULL, client_id INTEGER, order_id INTEGER,
  at TEXT NOT NULL, packs INTEGER NOT NULL, price10 REAL NOT NULL, discount REAL NOT NULL DEFAULT 0, total REAL NOT NULL,
  method TEXT NOT NULL, paid REAL NOT NULL DEFAULT 0, notes TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS subscriptions(id INTEGER PRIMARY KEY, farm_id INTEGER NOT NULL, client_id INTEGER NOT NULL,
  eggs INTEGER NOT NULL, every_days INTEGER NOT NULL, next_date TEXT NOT NULL, method TEXT NOT NULL DEFAULT 'later',
  active INTEGER NOT NULL DEFAULT 1, notes TEXT NOT NULL DEFAULT '', created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS expenses(id INTEGER PRIMARY KEY, farm_id INTEGER NOT NULL, date TEXT NOT NULL, category TEXT NOT NULL,
  name TEXT NOT NULL, qty REAL NOT NULL DEFAULT 1, unit TEXT NOT NULL DEFAULT 'szt', unit_price REAL NOT NULL DEFAULT 0,
  total REAL NOT NULL, supplier TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS equipment(id INTEGER PRIMARY KEY, farm_id INTEGER NOT NULL, name TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT '', bought TEXT NOT NULL DEFAULT '', price REAL NOT NULL DEFAULT 0,
  state TEXT NOT NULL DEFAULT 'ok', next_check TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY, farm_id INTEGER NOT NULL, client_id INTEGER NOT NULL, at TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN('sale','payment','refund','correction')), amount REAL NOT NULL, method TEXT NOT NULL DEFAULT '',
  sale_id INTEGER, note TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS feed_items(id INTEGER PRIMARY KEY, farm_id INTEGER NOT NULL, name TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT 'grain', unit TEXT NOT NULL DEFAULT 'kg', stock REAL NOT NULL DEFAULT 0, min_stock REAL NOT NULL DEFAULT 0,
  price REAL NOT NULL DEFAULT 0, protein REAL, energy REAL, calcium REAL, notes TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS feed_moves(id INTEGER PRIMARY KEY, farm_id INTEGER NOT NULL, item_id INTEGER NOT NULL, at TEXT NOT NULL,
  kind TEXT NOT NULL, qty REAL NOT NULL, price REAL, mix_id INTEGER, expense_id INTEGER, note TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS recipes(id INTEGER PRIMARY KEY, farm_id INTEGER NOT NULL, name TEXT NOT NULL, season TEXT NOT NULL DEFAULT 'all',
  active INTEGER NOT NULL DEFAULT 0, notes TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS recipe_items(id INTEGER PRIMARY KEY, recipe_id INTEGER NOT NULL, item_id INTEGER NOT NULL, percent REAL NOT NULL);
CREATE TABLE IF NOT EXISTS mixes(id INTEGER PRIMARY KEY, farm_id INTEGER NOT NULL, at TEXT NOT NULL, recipe_id INTEGER, kg REAL NOT NULL,
  notes TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS photos(id INTEGER PRIMARY KEY, farm_id INTEGER NOT NULL, building_id INTEGER, flock_id INTEGER,
  file TEXT NOT NULL, caption TEXT NOT NULL DEFAULT '', created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS archive_days(id INTEGER PRIMARY KEY, farm_id INTEGER NOT NULL, day TEXT NOT NULL, hens INTEGER NOT NULL DEFAULT 0,
  broody INTEGER NOT NULL DEFAULT 0, eggs INTEGER NOT NULL DEFAULT 0, logged INTEGER NOT NULL DEFAULT 1, losses INTEGER NOT NULL DEFAULT 0,
  stock INTEGER NOT NULL DEFAULT 0, orders INTEGER NOT NULL DEFAULT 0, home INTEGER NOT NULL DEFAULT 0, sales TEXT NOT NULL DEFAULT '[]',
  revenue REAL NOT NULL DEFAULT 0, expense REAL NOT NULL DEFAULT 0, expense_type TEXT NOT NULL DEFAULT '', paid_out INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS buildings(id INTEGER PRIMARY KEY, farm_id INTEGER NOT NULL, name TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS kb(id INTEGER PRIMARY KEY, title TEXT NOT NULL, category TEXT NOT NULL DEFAULT '', body TEXT NOT NULL,
  published INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL, updated TEXT NOT NULL);
"""
# Kolumny dodane po pierwszym wydaniu: dopisywane do istniejących baz przy starcie.
COLUMNS = [
    ("farms", "lat", "REAL"), ("farms", "lon", "REAL"),
    ("devices", "door_run_s", "INTEGER NOT NULL DEFAULT 20"), ("devices", "door", "TEXT"),
    ("devices", "door_want", "INTEGER"), ("devices", "wg_priv", "TEXT"), ("devices", "wg_pub", "TEXT"),
    ("orders", "client_id", "INTEGER"),
    ("farms", "eggs", "INTEGER NOT NULL DEFAULT 0"),      # jaja w magazynie (szt.), dobre
    ("farms", "reserved", "INTEGER NOT NULL DEFAULT 0"),  # z tego zarezerwowane dla stałych klientów (szt.)
    ("sales", "eggs", "INTEGER NOT NULL DEFAULT 0"), ("sales", "source", "TEXT NOT NULL DEFAULT 'offer'"),
    ("sales", "subscription_id", "INTEGER"),
    ("farms", "unsorted", "INTEGER NOT NULL DEFAULT 0"),  # zebrane, czekają na sortowanie (szt.)
    ("eggs", "dirty", "INTEGER NOT NULL DEFAULT 0"), ("eggs", "who", "TEXT NOT NULL DEFAULT ''"),
    ("farms", "remind_on", "INTEGER NOT NULL DEFAULT 1"), ("farms", "remind_hour", "INTEGER NOT NULL DEFAULT 19"),
    ("farms", "remind_sent", "TEXT NOT NULL DEFAULT ''"),
    ("devices", "esp_api_key", "TEXT"), ("devices", "esp_ota_password", "TEXT"),
    ("devices", "sensor", "TEXT NOT NULL DEFAULT ''"), ("devices", "sensor_pins", "TEXT NOT NULL DEFAULT ''"),
    ("devices", "wifi_ssid", "TEXT NOT NULL DEFAULT ''"), ("devices", "wifi_password", "TEXT NOT NULL DEFAULT ''"),
    ("devices", "fw_job", "TEXT NOT NULL DEFAULT ''"),
    ("users", "name", "TEXT NOT NULL DEFAULT ''"), ("users", "owner", "INTEGER NOT NULL DEFAULT 1"),
    ("farms", "dirty", "INTEGER NOT NULL DEFAULT 0"),      # brudne jaja: nie do sklepu, ale do sprzedaży na miejscu lub rozdania
    ("eggs", "pool", "TEXT NOT NULL DEFAULT ''"), ("eggs", "building_id", "INTEGER"),
    ("flocks", "building_id", "INTEGER"), ("devices", "building_id", "INTEGER"),
    ("orders", "due_date", "TEXT NOT NULL DEFAULT ''"),
    ("farms", "archive_name", "TEXT NOT NULL DEFAULT ''"), ("farms", "archive_at", "TEXT NOT NULL DEFAULT ''"),
    ("eggs", "user_id", "INTEGER"), ("sales", "user_id", "INTEGER"), ("ledger", "user_id", "INTEGER"),
    ("feed_moves", "user_id", "INTEGER"), ("mixes", "user_id", "INTEGER"), ("expenses", "user_id", "INTEGER"),
    ("channels", "off_at", "TEXT"), ("channels", "want", "INTEGER"),
    ("schedules", "mode", "TEXT NOT NULL DEFAULT 'time'"), ("schedules", "offset_min", "INTEGER NOT NULL DEFAULT 0"),
    ("schedules", "off_mode", "TEXT NOT NULL DEFAULT 'time'"), ("schedules", "off_offset_min", "INTEGER NOT NULL DEFAULT 0"),
    ("schedules", "duration_s", "INTEGER"),
]


AUTHORED = ("eggs", "sales", "ledger", "feed_moves", "mixes", "expenses")  # wpisy z informacją, kto je zrobił


def set_user(db, uid):
    """Tymczasowe wyzwalacze tego połączenia dopisują user_id do każdego nowego wpisu (kto zbierał, kto sprzedał...)."""
    db.execute("CREATE TEMP TABLE IF NOT EXISTS cur_user(uid INTEGER)")
    db.execute("DELETE FROM temp.cur_user")
    db.execute("INSERT INTO temp.cur_user VALUES(?)", (uid,))
    for t in AUTHORED:
        db.execute(f"CREATE TEMP TRIGGER IF NOT EXISTS {t}_author AFTER INSERT ON main.{t} WHEN NEW.user_id IS NULL "
                   f"BEGIN UPDATE {t} SET user_id=(SELECT uid FROM cur_user) WHERE id=NEW.id; END")


def by_sql(alias):
    """Kolumna by_name: imię albo e-mail osoby, która zrobiła wpis."""
    return f"(SELECT COALESCE(NULLIF(u.name,''), u.email) FROM users u WHERE u.id={alias}.user_id) AS by_name"


def get():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


def init_app(app):
    @app.teardown_appcontext
    def close(_):
        d = g.pop("db", None)
        if d:
            d.close()
    with app.app_context():
        db = get()
        db.executescript(SCHEMA)
        migrate(db)
        db.commit()


def migrate(db):
    ddl = db.execute("SELECT sql FROM sqlite_master WHERE name='eggs'").fetchone()[0]
    if "CHECK(kind IN('collect','sale'))" in ddl:  # stary dziennik jaj (tylko opakowania): przebudowa na sztuki
        cols = {r[1] for r in db.execute("PRAGMA table_info(eggs)")}
        db.executescript("ALTER TABLE eggs RENAME TO eggs_old;" + SCHEMA[SCHEMA.index("CREATE TABLE IF NOT EXISTS eggs"):].split(";")[0] + ";")
        db.execute("INSERT INTO eggs(id,farm_id,kind,packs,at,sale_id,eggs) SELECT id,farm_id,kind,packs,at,"
                   + ("sale_id" if "sale_id" in cols else "NULL") + ",packs*10 FROM eggs_old")
        db.execute("DROP TABLE eggs_old")
    added = set()
    for table, col, ddl in COLUMNS:
        if col not in {r[1] for r in db.execute(f"PRAGMA table_info({table})")}:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
            added.add((table, col))
    if ("farms", "eggs") in added:  # dotychczasowe opakowania w sklepie to jaja w magazynie
        db.execute("UPDATE farms SET eggs=stock*10")
    if ("sales", "eggs") in added:
        db.execute("UPDATE sales SET eggs=packs*10")
