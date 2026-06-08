import os
import sqlite3
import threading
import time
import json
import logging
from datetime import datetime, timedelta

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DB_PATH = os.environ.get("DB_PATH", "gazebos.db")

AFISHA_URL = "https://bilet.mos.ru/api/newsfeed/v4/frontend/json/ru/afisha"
SLOTS_URL = "https://tickets.mos.ru/api/widget/v2/event/{ebs_id}/performances"

SPHERE_ID = "472299"

_proxy_url = os.environ.get("PROXY_URL", "")
PROXIES = {"http": _proxy_url, "https": _proxy_url} if _proxy_url else {"http": "", "https": ""}

_session = None
_session_lock = threading.Lock()


def get_session():
    global _session
    with _session_lock:
        if _session is None:
            _session = requests.Session()
            _session.proxies = PROXIES
            _session.headers["User-Agent"] = (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            )
        return _session


def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS gazebos (
            id INTEGER PRIMARY KEY,
            bilet_id INTEGER,
            ebs_id INTEGER UNIQUE,
            ebs_agent_uid TEXT,
            title TEXT,
            park TEXT,
            address TEXT
        )
    """)
    # migrate existing DBs that lack bilet_id
    cols = {r[1] for r in con.execute("PRAGMA table_info(gazebos)")}
    if "bilet_id" not in cols:
        con.execute("ALTER TABLE gazebos ADD COLUMN bilet_id INTEGER")
    if "image_url" not in cols:
        con.execute("ALTER TABLE gazebos ADD COLUMN image_url TEXT")
    if "has_mangal" not in cols:
        con.execute("ALTER TABLE gazebos ADD COLUMN has_mangal INTEGER NOT NULL DEFAULT 0")
    if "lat" not in cols:
        con.execute("ALTER TABLE gazebos ADD COLUMN lat REAL")
    if "lon" not in cols:
        con.execute("ALTER TABLE gazebos ADD COLUMN lon REAL")
    con.execute("""
        CREATE TABLE IF NOT EXISTS performances (
            id INTEGER PRIMARY KEY,
            gazebo_ebs_id INTEGER,
            perf_id INTEGER,
            date TEXT,
            start_dt TEXT,
            end_dt TEXT,
            free_seats INTEGER,
            price REAL,
            fetched_at REAL,
            UNIQUE(perf_id)
        )
    """)
    con.commit()
    con.close()


def fetch_gazebos_page(page: int) -> tuple[list, int]:
    filter_obj = {"&": {"=spheres.id": [SPHERE_ID]}}
    params = {
        "expand": "spheres,spots,foundation",
        "filter": json.dumps(filter_obj, ensure_ascii=False),
        "per-page": 50,
        "page": page,
        "sort": "occurrences.date_from",
    }
    r = get_session().get(AFISHA_URL, params=params, timeout=30)
    r.raise_for_status()
    total_pages = int(r.headers.get("X-Pagination-Page-Count", 1))
    data = r.json()
    # API may return {"items": [...], ...} or a bare list
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in ("items", "data", "events", "results"):
            if key in data and isinstance(data[key], list):
                items = data[key]
                break
        else:
            # fallback: first list value in the dict
            items = next((v for v in data.values() if isinstance(v, list)), [])
            if not items:
                log.warning("Unexpected API response structure: %s", list(data.keys()))
    else:
        items = []
    return items, total_pages


BILET_BASE = "https://bilet.mos.ru"


def _has_mangal(item: dict) -> bool:
    text = " ".join([
        item.get("text") or "",
        item.get("title") or "",
        item.get("ebs_title") or "",
    ]).lower()
    return "мангал" in text


def _extract_image(item: dict) -> str:
    img = item.get("image") or {}
    src = (img.get("small") or img.get("middle") or img.get("thumb") or {}).get("src", "")
    return BILET_BASE + src if src else ""


def upsert_gazebos(items: list):
    con = sqlite3.connect(DB_PATH)
    for item in items:
        foundation = item.get("foundation") or {}
        spots = item.get("spots") or [{}]
        spot = spots[0] if spots else {}
        address = spot.get("address", "")
        lat = float(spot["lat"]) if spot.get("lat") else None
        lon = float(spot["lon"]) if spot.get("lon") else None
        con.execute(
            """
            INSERT INTO gazebos (bilet_id, ebs_id, ebs_agent_uid, title, park, address, image_url, has_mangal, lat, lon)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ebs_id) DO UPDATE SET
                bilet_id=excluded.bilet_id,
                ebs_agent_uid=excluded.ebs_agent_uid,
                title=excluded.title,
                park=excluded.park,
                address=excluded.address,
                image_url=excluded.image_url,
                has_mangal=excluded.has_mangal,
                lat=excluded.lat,
                lon=excluded.lon
            """,
            (
                item.get("id"),
                item.get("ebs_id"),
                item.get("ebs_agent_uid"),
                item.get("title", ""),
                foundation.get("title", ""),
                address,
                _extract_image(item),
                int(_has_mangal(item)),
                lat,
                lon,
            ),
        )
    con.commit()
    con.close()


def fetch_slots(ebs_id: int, agent_id: str, date_from: str, date_to: str) -> list:
    d0 = datetime.strptime(date_from, "%Y-%m-%d")
    d1 = datetime.strptime(date_to, "%Y-%m-%d")
    days = max(1, (d1 - d0).days + 1)
    params = {
        "date_from": date_from,
        "date_to": "",
        "performances_limit_by_days": days,
        "agent_id": agent_id,
    }
    url = SLOTS_URL.format(ebs_id=ebs_id)
    r = get_session().get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def upsert_slots(gazebo_ebs_id: int, days_data: list):
    con = sqlite3.connect(DB_PATH)
    now = time.time()
    for day in days_data:
        for perf in day.get("performances", []):
            con.execute(
                """
                INSERT INTO performances
                    (gazebo_ebs_id, perf_id, date, start_dt, end_dt, free_seats, price, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(perf_id) DO UPDATE SET
                    free_seats=excluded.free_seats,
                    fetched_at=excluded.fetched_at
                """,
                (
                    gazebo_ebs_id,
                    perf["id"],
                    day["date"],
                    perf.get("start_datetime", ""),
                    perf.get("end_datetime", ""),
                    perf.get("free_seats_count", 0),
                    perf.get("min_performance_price", 0),
                    now,
                ),
            )
    con.commit()
    con.close()


# ── Job state ──────────────────────────────────────────────────────────────────

class ScrapeJob:
    def __init__(self):
        self.reset()

    def reset(self):
        self.running = False
        self.done = False
        self.total = 0
        self.processed = 0
        self.errors = 0
        self.parks: list[str] = []
        self.date_from = ""
        self.date_to = ""
        self.log_lines: list[str] = []

    def log(self, msg: str):
        log.info(msg)
        self.log_lines.append(msg)
        if len(self.log_lines) > 200:
            self.log_lines = self.log_lines[-200:]

    def status(self) -> dict:
        pct = round(self.processed / self.total * 100) if self.total else 0
        return {
            "running": self.running,
            "done": self.done,
            "total": self.total,
            "processed": self.processed,
            "errors": self.errors,
            "percent": pct,
            "log": self.log_lines[-30:],
        }


job = ScrapeJob()


def run_scrape(parks: list[str], date_from: str, date_to: str):
    job.reset()
    job.running = True
    job.parks = parks
    job.date_from = date_from
    job.date_to = date_to

    try:
        job.log("Загружаю список беседок...")
        all_items = []
        page = 1
        while True:
            items, total_pages = fetch_gazebos_page(page)
            all_items.extend(items)
            job.log(f"  Страница {page}/{total_pages}: получено {len(items)} беседок")
            if page >= total_pages:
                break
            page += 1
            time.sleep(0.3)

        upsert_gazebos(all_items)

        if parks:
            parks_lower = [p.lower() for p in parks]
            filtered = [
                i for i in all_items
                if any(p in (i.get("foundation") or {}).get("title", "").lower() for p in parks_lower)
            ]
        else:
            filtered = all_items

        job.total = len(filtered)
        job.log(f"Беседок для обхода: {job.total}")

        scrape_start = time.time()

        for item in filtered:
            ebs_id = item.get("ebs_id")
            agent_id = item.get("ebs_agent_uid")
            title = item.get("title", str(ebs_id))
            try:
                days_data = fetch_slots(ebs_id, agent_id, date_from, date_to)
                upsert_slots(ebs_id, days_data)
                job.log(f"  ✓ {title}")
            except Exception as e:
                job.errors += 1
                job.log(f"  ✗ {title}: {e}")
            finally:
                job.processed += 1
            time.sleep(0.2)

        # Удаляем только те слоты, которые не обновились в этом прогоне
        ebs_ids = [item.get("ebs_id") for item in filtered if item.get("ebs_id")]
        if ebs_ids:
            con = sqlite3.connect(DB_PATH)
            placeholders = ",".join("?" * len(ebs_ids))
            con.execute(
                f"DELETE FROM performances WHERE gazebo_ebs_id IN ({placeholders}) AND fetched_at < ?",
                ebs_ids + [scrape_start],
            )
            con.commit()
            con.close()

        job.log("Готово!")
    except Exception as e:
        job.log(f"Критическая ошибка: {e}")
    finally:
        job.running = False
        job.done = True


def start_scrape(parks: list[str], date_from: str, date_to: str):
    if job.running:
        return False
    t = threading.Thread(target=run_scrape, args=(parks, date_from, date_to), daemon=True)
    t.start()
    return True


def get_available_date_range() -> dict:
    con = sqlite3.connect(DB_PATH)
    row = con.execute("SELECT MIN(date), MAX(date) FROM performances WHERE free_seats >= 0").fetchone()
    con.close()
    return {"min": row[0], "max": row[1]}


def get_last_updated() -> float | None:
    con = sqlite3.connect(DB_PATH)
    row = con.execute("SELECT MAX(fetched_at) FROM performances").fetchone()
    con.close()
    return row[0] if row else None


def get_parks() -> list[str]:
    con = sqlite3.connect(DB_PATH)
    rows = con.execute(
        "SELECT DISTINCT park FROM gazebos WHERE park != '' ORDER BY park"
    ).fetchall()
    con.close()
    return [r[0] for r in rows]


def get_results(parks: list[str], date_from: str, date_to: str) -> list[dict]:
    """Return gazebos with their free slots in [date_from, date_to]."""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    placeholders = ",".join("?" * len(parks)) if parks else "1"
    park_filter = f"AND g.park IN ({placeholders})" if parks else ""
    params: list = []
    if parks:
        params.extend(parks)
    params.extend([date_from, date_to])

    rows = con.execute(
        f"""
        SELECT
            g.ebs_id, g.bilet_id, g.image_url, g.has_mangal, g.title, g.park, g.address, g.lat, g.lon,
            p.date, p.start_dt, p.end_dt, p.free_seats, p.price
        FROM gazebos g
        JOIN performances p ON p.gazebo_ebs_id = g.ebs_id
        WHERE p.free_seats > 0
          AND p.date >= ?
          AND p.date <= ?
          {park_filter}
        ORDER BY g.park, g.title, p.date, p.start_dt
        """,
        [date_from, date_to] + (list(parks) if parks else []),
    ).fetchall()
    con.close()

    # Group by gazebo
    gazebos: dict[int, dict] = {}
    for r in rows:
        eid = r["ebs_id"]
        if eid not in gazebos:
            gazebos[eid] = {
                "ebs_id": eid,
                "bilet_id": r["bilet_id"],
                "image_url": r["image_url"] or "",
                "has_mangal": bool(r["has_mangal"]),
                "title": r["title"],
                "park": r["park"],
                "address": r["address"],
                "lat": r["lat"],
                "lon": r["lon"],
                "slots": [],
            }
        gazebos[eid]["slots"].append({
            "date": r["date"],
            "start": r["start_dt"],
            "end": r["end_dt"],
            "free": r["free_seats"],
            "price": r["price"],
        })

    return list(gazebos.values())


def get_unavailable_gazebos(parks: list[str], date_from: str, date_to: str) -> list[dict]:
    """Gazebos with no free slots in the date range (fully booked or simply not open)."""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    park_filter = f"AND g.park IN ({','.join('?' * len(parks))})" if parks else ""
    rows = con.execute(
        f"""
        SELECT g.ebs_id, g.bilet_id, g.title, g.park, g.address, g.image_url, g.has_mangal
        FROM gazebos g
        WHERE g.ebs_id NOT IN (
            SELECT gazebo_ebs_id FROM performances
            WHERE free_seats > 0 AND date >= ? AND date <= ?
        )
        {park_filter}
        ORDER BY g.park, g.title
        """,
        [date_from, date_to] + (list(parks) if parks else []),
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


# ── Auto-scrape scheduler ──────────────────────────────────────────────────────

def _load_auto_settings() -> dict:
    path = os.environ.get("DEFAULTS_PATH", "defaults.json")
    try:
        with open(path) as f:
            return json.load(f).get("autoScrape", {})
    except Exception:
        return {}


def _auto_scrape_loop():
    while True:
        time.sleep(60)
        try:
            s = _load_auto_settings()
            if not s.get("enabled"):
                continue
            if job.running:
                continue
            interval_sec = int(s.get("intervalMinutes", 10)) * 60
            last_ts = get_last_updated() or 0
            if time.time() - last_ts < interval_sec:
                continue
            parks     = s.get("parks", [])
            date_from = s.get("dateFrom") or datetime.today().strftime("%Y-%m-%d")
            date_to   = s.get("dateTo")   or (datetime.today() + timedelta(days=13)).strftime("%Y-%m-%d")
            log.info("Автопарсинг запущен")
            start_scrape(parks, date_from, date_to)
        except Exception as e:
            log.error("Ошибка планировщика: %s", e)


_scheduler_thread = threading.Thread(target=_auto_scrape_loop, daemon=True)
_scheduler_thread.start()


init_db()
