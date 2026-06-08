import json
import os
from datetime import datetime, timedelta
from flask import Flask, jsonify, render_template, request

import scraper

app = Flask(__name__)

DEFAULTS_PATH = os.environ.get("DEFAULTS_PATH", "defaults.json")


def load_defaults() -> dict:
    if os.path.exists(DEFAULTS_PATH):
        with open(DEFAULTS_PATH) as f:
            return json.load(f)
    return {"filterParks": [], "filterTimeFrom": "00:00", "filterTimeTo": "23:59", "filterPriceMax": ""}


def save_defaults(data: dict):
    existing = load_defaults()
    existing.update(data)
    with open(DEFAULTS_PATH, "w") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)


@app.get("/")
def public():
    return render_template("index.html", is_admin=False)


@app.get("/admin")
def admin():
    return render_template("index.html", is_admin=True)


@app.get("/api/parks")
def api_parks():
    return jsonify(scraper.get_parks())


@app.post("/api/scrape")
def api_scrape():
    data = request.get_json(force=True) or {}
    parks = data.get("parks", [])
    date_from = data.get("date_from", datetime.today().strftime("%Y-%m-%d"))
    date_to = data.get("date_to", (datetime.today() + timedelta(days=13)).strftime("%Y-%m-%d"))

    started = scraper.start_scrape(parks, date_from, date_to)
    if not started:
        return jsonify({"error": "Парсинг уже идёт"}), 409
    return jsonify({"ok": True})


@app.get("/api/status")
def api_status():
    return jsonify(scraper.job.status())


@app.get("/api/results")
def api_results():
    parks = request.args.getlist("park")
    date_from = request.args.get("date_from", datetime.today().strftime("%Y-%m-%d"))
    date_to = request.args.get("date_to", (datetime.today() + timedelta(days=13)).strftime("%Y-%m-%d"))
    results = scraper.get_results(parks, date_from, date_to)
    return jsonify(results)


@app.get("/api/unavailable")
def api_unavailable():
    parks = request.args.getlist("park")
    date_from = request.args.get("date_from", datetime.today().strftime("%Y-%m-%d"))
    date_to = request.args.get("date_to", (datetime.today() + timedelta(days=13)).strftime("%Y-%m-%d"))
    return jsonify(scraper.get_unavailable_gazebos(parks, date_from, date_to))


@app.get("/api/available-dates")
def api_available_dates():
    return jsonify(scraper.get_available_date_range())


@app.get("/api/last-updated")
def api_last_updated():
    ts = scraper.get_last_updated()
    return jsonify({"ts": ts})


@app.get("/api/defaults")
def api_get_defaults():
    return jsonify(load_defaults())


@app.post("/api/defaults")
def api_save_defaults():
    data = request.get_json(force=True) or {}
    allowed = {"filterParks", "filterDateFrom", "filterDateTo", "filterTimeFrom", "filterTimeTo", "filterPriceMax"}
    save_defaults({k: v for k, v in data.items() if k in allowed})
    return jsonify({"ok": True})


@app.get("/api/auto-scrape")
def api_get_auto_scrape():
    return jsonify(load_defaults().get("autoScrape", {}))


@app.post("/api/auto-scrape")
def api_save_auto_scrape():
    data = request.get_json(force=True) or {}
    save_defaults({"autoScrape": {
        "enabled":         bool(data.get("enabled")),
        "intervalMinutes": int(data.get("intervalMinutes", 10)),
        "dateFrom":        data.get("dateFrom", ""),
        "dateTo":          data.get("dateTo", ""),
        "parks":           list(data.get("parks", [])),
    }})
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
