# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the app

```bash
# Development
pip install -r requirements.txt
python app.py          # runs on http://localhost:5000

# Production (Docker)
docker compose up --build
```

Two routes: `/` (public read-only view) and `/admin` (scrape controls + save-defaults button).

## Architecture

Three files do everything:

- **`scraper.py`** — all data access and scraping logic. Talks to two external APIs (`bilet.mos.ru` afisha API and `tickets.mos.ru` widget API), writes to SQLite. Runs scrapes in a background thread via `ScrapeJob`/`start_scrape`. Exposes `get_results()`, `get_parks()`, `get_last_updated()`.
- **`app.py`** — thin Flask wrapper. All endpoints are under `/api/`. Reads/writes `defaults.json` for public-facing filter presets.
- **`templates/index.html`** — single-page app (vanilla JS, no framework). All rendering is client-side. The `IS_ADMIN` flag (injected by Jinja2) gates scrape controls.

## Data flow

1. Admin triggers `/api/scrape` → `scraper.start_scrape()` spawns a thread
2. Thread paginates `AFISHA_URL` to collect all gazebos, upserts into `gazebos` table
3. Then fetches slots per gazebo from `SLOTS_URL`, upserts into `performances` table
4. Public page calls `/api/results?date_from=&date_to=&park=` → returns gazebos with free slots grouped by `ebs_id`
5. Client filters results locally by time range and price (no round-trip for filter changes)

## Environment variables

| Var | Default | Purpose |
|-----|---------|---------|
| `DB_PATH` | `gazebos.db` | SQLite file location |
| `DEFAULTS_PATH` | `defaults.json` | Public filter presets |
| `PROXY_URL` | _(none)_ | HTTP proxy for outbound requests to mos.ru APIs |

## Key external API details

- Gazebo catalogue: `GET https://bilet.mos.ru/api/newsfeed/v4/frontend/json/ru/afisha` — filter by `spheres.id=472299`, paginated (50/page), total pages in `X-Pagination-Page-Count` header
- Slot availability: `GET https://tickets.mos.ru/api/widget/v2/event/{ebs_id}/performances` — keyed by `ebs_id` + `ebs_agent_uid` from catalogue response

## DB schema (SQLite)

```sql
gazebos(id, bilet_id, ebs_id UNIQUE, ebs_agent_uid, title, park, address, image_url, has_mangal)
performances(id, gazebo_ebs_id, perf_id UNIQUE, date, start_dt, end_dt, free_seats, price, fetched_at)
```
