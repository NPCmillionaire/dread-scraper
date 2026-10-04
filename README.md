# dread-scraper

A slow, resumable archiver for selected Dread boards, routed through Tor. It walks board listings, saves every thread's original post and replies to a local SQLite database, and indexes them with full-text search so you can query the archive offline.

Built for research and threat-intelligence use: tracking discussion on fraud-related boards without browsing them by hand.

## How it works

```
Tor Browser (SOCKS 127.0.0.1:9150, logged-in session cookie)
        │
        ▼
scrape.py ── board pages ──► thread URLs ──► thread pages ──► parse OP + replies
        │
        ▼
dread_archive.sqlite3  (threads, posts, posts_fts full-text index)
        │
        ▼
search.py  ── FTS5 queries ──► matching posts with highlighted snippets
```

- **Polite by default** — randomized 5–10 s delay between requests, exponential back-off on errors, and a per-board page cap.
- **Resumable** — threads are marked `completed` once fully archived; re-running skips them, so it's safe to stop and restart anytime.
- **Anti-DDoS aware** — detects Dread's queue/gate page and waits it out (up to ~2 min) instead of saving the gate as content.
- **Deduplicated** — posts are unique on `(thread, author, date, text)`, so repeat runs don't create duplicates.

## Files

| File | Purpose |
|---|---|
| `scrape.py` | The archiver. All settings live in its `CONFIG` dict. |
| `search.py` | Full-text search over the archive from the command line. |
| `debug_fetch.py` | Fetches one URL with the scraper's client setup and prints the raw response — for diagnosing selectors that match nothing. |
| `requirements.txt` | `httpx[socks,http2]`, `beautifulsoup4` |

## Requirements

- Python 3.9+ (SQLite with FTS5 — included in standard CPython builds)
- [Tor Browser](https://www.torproject.org/), running while the scraper runs
- A Dread account

## Setup

1. **Install dependencies**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Start Tor Browser and log in to Dread.** Solve the captcha manually. Leave Tor Browser open — the scraper reuses its SOCKS proxy on `127.0.0.1:9150`.

3. **Copy your session cookie.** In Tor Browser dev tools → Storage → Cookies, copy the session cookie and paste it into `CONFIG["cookies"]` in `scrape.py`:
   ```python
   "cookies": {
       "dread_session": "paste-value-here",
   },
   ```
   Cookies expire; repeat this step when fetches start returning the login page.

4. **Check the selectors.** `CONFIG["selectors"]` holds the CSS selectors used to parse board and thread pages. The defaults match the current markup, but if Dread changes its layout, view-source a board page and a thread page in Tor Browser and update them. `debug_fetch.py` helps here (see below).

## Configuration

Everything is in `CONFIG` at the top of `scrape.py`:

| Key | Default | Notes |
|---|---|---|
| `base_url` | Dread's `.onion` address | |
| `boards` | `["/d/carding", "/d/Fraud"]` | Board paths to archive |
| `cookies` | `{}` | Logged-in session cookie (required) |
| `proxy` | `socks5://127.0.0.1:9150` | Tor Browser's SOCKS port. Use `9050` for a standalone `tor` daemon. |
| `db_path` | `dread_archive.sqlite3` | Output database |
| `delay_range` | `(5, 10)` | Seconds between requests, randomized |
| `max_retries` | `5` | Per URL, with exponential back-off (capped at 60 s) |
| `max_board_pages` | `50` | Safety cap on listing pages per board |
| `selectors` | see file | CSS selectors for board, thread, and OP markup |

The script refuses to start if any required selector is empty.

## Usage

**Archive:**
```bash
python3 scrape.py
```
Progress prints to stdout; retries and gate waits print to stderr.

**Search the archive:**
```bash
python3 search.py "escrow"
python3 search.py "bin NEAR checker" --limit 50
```
Queries use [SQLite FTS5 syntax](https://www.sqlite.org/fts5.html#full_text_query_syntax) — phrases in quotes, `AND`/`OR`/`NOT`, `NEAR`, and prefix matching with `*`. Results show the board, thread title, author, and a snippet with matches in `[brackets]`.

**Debug a page:**
```bash
python3 debug_fetch.py                     # defaults to /d/carding
python3 debug_fetch.py "<full thread URL>"
```
Prints the status code, final URL, and the first 2,000 characters of the response — useful for spotting an expired cookie, a gate page, or changed markup.

### Running on a schedule

The scraper is safe to run repeatedly, so it can go on a cron job. Tor must be reachable at `CONFIG["proxy"]`, so on a headless box run a `tor` daemon and set the proxy to `socks5://127.0.0.1:9050`:

```cron
0 23 * * * cd /path/to/dread-scraper && .venv/bin/python scrape.py >> scrape.log 2>&1
```

## Database schema

| Table | Columns |
|---|---|
| `threads` | `url` (PK), `board`, `title`, `completed` |
| `posts` | `id`, `thread_url`, `author`, `posted_at`, `text`, `fetched_at` |
| `posts_fts` | FTS5 index over `text`, `thread_title`, `board`, `author` — filled by an insert trigger |

Query it directly with any SQLite client:
```bash
sqlite3 dread_archive.sqlite3 "SELECT board, COUNT(*) FROM posts JOIN threads ON threads.url = posts.thread_url GROUP BY board;"
```

## Known limitations

- **Selectors are brittle.** Any Dread layout change can silently break parsing; check with `debug_fetch.py` if a run archives 0 posts.
- **Session cookies expire.** There's no automatic login — refresh the cookie manually.
- **`posted_at` is stored as displayed** (often relative text like "3 days ago"), not a normalized timestamp.
- **TLS verification is disabled** (`verify=False`), which is normal for `.onion` HTTP but worth knowing.

## Responsible use

This tool reads content you can already view in a browser and is intended for research, journalism, and threat intelligence. Keep the request rate low, don't redistribute personal data you collect, and follow the laws that apply where you live and work. The archive may contain sensitive material — store it accordingly.
