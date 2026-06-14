# 🗺️ Map Scraper API

## Overview

A FastAPI backend that automates Google Maps data extraction using Playwright. Give it a search query, get back structured business data — exported as CSV or saved directly to MySQL. Built for speed and flexibility: scrape a fixed number of listings or grab everything, synchronously or in the background.

---

> **Demo**
<img width="800" height="450" alt="map_Scraper_v1-ezgif com-video-to-gif-converter" src="https://github.com/user-attachments/assets/b33da054-c66b-4a28-aba7-f32db5e60f58" />

---

## Use Case — Freelancer Lead Generation

Freelancers and agencies spend hours manually collecting business contacts from Google Maps. This tool automates that entirely.

**Example workflow:**
1. Run a query like `"interior designers in Mumbai"` or `"dental clinics near Delhi"`
2. Get back a CSV with names, phone numbers, addresses, ratings, and opening hours
3. Cold outreach or hand off the leads list to a client

Whether you're building a leads pipeline for yourself or selling scraped datasets as a service, this replaces hours of manual copy-paste with a single API call.

---

## Tech Stack

`FastAPI` · `Playwright (Chromium)` · `MySQL` · `Pydantic v2` · `Python 3.13+`

---

## Getting Started

```bash
git clone https://github.com/shaswatHota/map-scraper-be.git
cd map-scraper-be

uv sync                        # or: pip install -r requirements
playwright install chromium
uvicorn main:app --reload
```

API: `http://localhost:8000` · Docs: `http://localhost:8000/docs`

---

## API Reference

### `POST /scrape`
Scrape and return results immediately.

```json
{
  "query": "cafes near Bhubaneswar",
  "scrape_count": 20,
  "save_to_db": false
}
```

| Field | Type | Description |
|---|---|---|
| `query` | `string` | Google Maps search query |
| `scrape_count` | `int \| "full"` | Number of listings, or `"full"` for all |
| `save_to_db` | `bool` | Persist results to MySQL |
| `db_config` | `object` | Required if `save_to_db: true` |
| `db_structure` | `"single" \| "normalized"` | DB schema mode |
| `table_action` | `"create_new" \| "update_existing"` | Behaviour on existing table |

### `POST /scrape-background`
Same as above but returns a `task_id` immediately and scrapes in the background.

### `GET /download/{filename}`
Download a generated CSV file.

### `GET /files`
List all available CSV files.

---

## Scraped Fields

`name` · `rating` · `reviews` · `address` · `opening hours` · `phone number`

---

> **Note:** Google Maps DOM can change over time. If scraping breaks, update the CSS selectors in `main.py`. Use responsibly and in accordance with Google's ToS.
