#!/usr/bin/env python3
"""ЕдаВыгодно: безопасный API-каркас каталога.

Источники магазинов намеренно не сканируются автоматически. Подключайте только
официальный API/партнёрский фид с разрешением сети.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from pathlib import Path
import json, sqlite3, os, csv, io, secrets
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get("EDAV_DB", ROOT / "edav.db"))
HOST = os.environ.get("EDAV_HOST", "127.0.0.1")
PORT = int(os.environ.get("EDAV_PORT", "8787"))
ADMIN_TOKEN = os.environ.get("EDAV_ADMIN_TOKEN", "")

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 name TEXT NOT NULL,
 store TEXT NOT NULL,
 category TEXT NOT NULL DEFAULT 'Другое',
 price REAL NOT NULL CHECK(price > 0),
 unit TEXT DEFAULT '',
 city TEXT NOT NULL,
 region TEXT DEFAULT '',
 observed_at TEXT NOT NULL,
 source TEXT NOT NULL,
 source_url TEXT DEFAULT '',
 status TEXT NOT NULL DEFAULT 'imported'
);
CREATE INDEX IF NOT EXISTS idx_products_city_store ON products(city, store);
CREATE INDEX IF NOT EXISTS idx_products_name ON products(name);
"""

def connect():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con

def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def providers_status():
    # No credentials or officially documented consumer catalog APIs are configured yet.
    return [
        {"store":"Пятёрочка","status":"not_connected","method":"Официальный партнёрский фид/API — требуется подтверждение доступа","catalog":"https://5ka.ru/catalog/"},
        {"store":"Магнит","status":"not_connected","method":"Найденная публичная документация Магнита относится к партнёрскому Market/B2B API, не к общедоступному розничному каталогу","catalog":"https://magnit.ru/catalog"},
        {"store":"Перекрёсток","status":"not_connected","method":"Официальный каталог доступен на сайте; для автоматического доступа нужен согласованный интерфейс/фид","catalog":"https://www.perekrestok.ru/catalog"}
    ]

class Handler(BaseHTTPRequestHandler):
    server_version = "EdavygodnoAPI/0.1"

    def send_json(self, code, payload):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", os.environ.get("EDAV_CORS_ORIGIN", "http://localhost:5500"))
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Admin-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self):
        self.send_json(200, {"ok": True})

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        if parsed.path == "/api/health":
            return self.send_json(200, {"ok":True,"service":"edavygodno-api","version":"0.1","time":utcnow()})
        if parsed.path == "/api/providers":
            return self.send_json(200, {"providers":providers_status(),"note":"Статус not_connected означает, что живые цены этой сети ещё не загружаются."})
        if parsed.path == "/api/catalog":
            city = qs.get("city", [""])[0].strip()
            store = qs.get("store", [""])[0].strip()
            q = qs.get("q", [""])[0].strip()
            if not city:
                return self.send_json(400, {"error":"Укажи city — город, для которого нужны цены."})
            sql = "SELECT * FROM products WHERE city = ?"
            args = [city]
            if store:
                sql += " AND store = ?"; args.append(store)
            if q:
                sql += " AND name LIKE ?"; args.append("%"+q+"%")
            sql += " ORDER BY store, name LIMIT 500"
            with connect() as con:
                rows = [dict(r) for r in con.execute(sql, args).fetchall()]
            return self.send_json(200, {"city":city,"count":len(rows),"products":rows,"generated_at":utcnow()})
        return self.send_json(404, {"error":"Not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/catalog/import":
            return self.send_json(404, {"error":"Not found"})
        if not ADMIN_TOKEN:
            return self.send_json(503, {"error":"Импорт выключен: сначала задай EDAV_ADMIN_TOKEN в окружении сервера."})
        supplied = self.headers.get("X-Admin-Token", "")
        if not secrets.compare_digest(supplied, ADMIN_TOKEN):
            return self.send_json(403, {"error":"Недостаточно прав."})
        try:
            length = int(self.headers.get("Content-Length","0"))
            if length <= 0 or length > 5_000_000:
                return self.send_json(413, {"error":"Размер запроса должен быть от 1 байта до 5 МБ."})
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            items = payload.get("products", [])
            if not isinstance(items, list) or len(items) > 5000:
                return self.send_json(400, {"error":"products должен быть массивом не более 5000 позиций."})
            added, skipped = 0, 0
            with connect() as con:
                for item in items:
                    try:
                        name = str(item["name"]).strip()
                        store = str(item["store"]).strip()
                        city = str(item["city"]).strip()
                        price = float(str(item["price"]).replace(",","."))
                        if not name or not store or not city or price <= 0: raise ValueError()
                        con.execute("""INSERT INTO products
                        (name,store,category,price,unit,city,region,observed_at,source,source_url,status)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        (name,store,str(item.get("category","Другое")),price,str(item.get("unit","")),
                         city,str(item.get("region","")),str(item.get("observed_at") or utcnow()),
                         str(item.get("source","official_feed")),str(item.get("source_url","")),
                         str(item.get("status","imported"))))
                        added += 1
                    except (KeyError,ValueError,TypeError):
                        skipped += 1
            return self.send_json(200, {"added":added,"skipped":skipped,"city_scope":"Цены не смешиваются между городами."})
        except json.JSONDecodeError:
            return self.send_json(400, {"error":"Некорректный JSON."})

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))

if __name__ == "__main__":
    connect().close()
    print(f"ЕдаВыгодно API: http://{HOST}:{PORT}")
    print("Проверка: /api/health | Каталог: /api/catalog?city=Москва")
    ThreadingHTTPServer((HOST,PORT), Handler).serve_forever()
