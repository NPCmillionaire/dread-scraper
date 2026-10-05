#!/usr/bin/env python3
"""
Gentle archiver for Dread boards, routed through Tor.

SETUP
1. Open Tor Browser, log into Dread, solve the captcha manually.
2. In Tor Browser dev tools -> Application/Storage -> Cookies, copy the
   session cookie value (usually named something like `dread_session`)
   and paste it into CONFIG["cookies"] below.
3. Keep Tor Browser open while this runs -- it exposes a local SOCKS
   proxy on 127.0.0.1:9150 that this script reuses.
4. View-source a board page (e.g. .../d/carding) and a thread page in
   Tor Browser to find the CSS selectors below. Fill them into
   CONFIG["selectors"]. Defaults are placeholders and will not work
   until you set them.

USAGE
    python3 scrape.py
Progress is stored in dread_archive.sqlite3; re-running skips threads
already fully archived, so it's safe to stop and resume.
"""

import random
import sqlite3
import sys
import time
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

CONFIG = {
    "base_url": "https://dreadlandswkysea676lnblidg3ienxnu2ilzcegxzt3v4hwkhmqz7id.onion",
    "boards": ["/d/carding", "/d/Fraud"],
    "cookies": {
        # "dread_session": "paste-value-here",
    },
    "proxy": "socks5://127.0.0.1:9150",
    "db_path": "dread_archive.sqlite3",
    "delay_range": (5, 10),  # seconds between requests, randomized
    "max_retries": 5,
    "max_board_pages": 50,   # safety cap per board
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; rv:128.0) Gecko/20100101 Firefox/128.0"
    ),
    # Fill these in from the actual page source. Each is a CSS selector
    # passed to BeautifulSoup .select() / .select_one().
    "selectors": {
        # --- board listing page: derived from the /d/Fraud listing source ---
        "thread_list_item": ".postBoard .item",
        "thread_link": "a.title",
        "board_next_page": ".pagination a.next",
        # --- thread page: derived from the page source you already pasted ---
        "post_container": ".comment",
        "post_author": ".top a.username",
        "post_date": ".timestamp span",
        "post_text": ".commentBody",
        "thread_title": ".title-text",
        "thread_next_page": "",      # leave "" -- Dread renders all comments on one page
        # --- the original post at the top of the thread (different markup
        # than a reply comment) ---
        "op_author": ".postTop .author a.author_link",
        "op_date": ".postTop .author span[title]",
        "op_text": ".postMain .postContent.viewPostBody",
    },
}

REQUIRED_SELECTORS = [
    "thread_list_item", "thread_link", "post_container", "post_author",
    "post_date", "post_text", "thread_title", "op_author", "op_text",
]


def make_session():
    return httpx.Client(
        proxy=CONFIG["proxy"],
        http2=True,
        verify=False,
        follow_redirects=True,
        timeout=60,
        headers={"User-Agent": CONFIG["user_agent"]},
        cookies=CONFIG["cookies"],
    )


GATE_MARKERS = ("Access Queue", "DDOS Protection")
GATE_POLL_SECONDS = 10
GATE_MAX_POLLS = 12  # ~2 minutes of waiting through the anti-DDoS gate


def fetch(session, url):
    delay_lo, delay_hi = CONFIG["delay_range"]
    for attempt in range(1, CONFIG["max_retries"] + 1):
        time.sleep(random.uniform(delay_lo, delay_hi))
        try:
            resp = session.get(url)
            text = resp.text
            polls = 0
            while (
                resp.status_code == 200
                and any(marker in text for marker in GATE_MARKERS)
                and polls < GATE_MAX_POLLS
            ):
                polls += 1
                print(f"  behind anti-DDoS gate, waiting ({polls}/{GATE_MAX_POLLS})...", file=sys.stderr)
                time.sleep(GATE_POLL_SECONDS)
                resp = session.get(url)
                text = resp.text
            if resp.status_code == 200 and not any(marker in text for marker in GATE_MARKERS):
                return text
            print(f"  [{resp.status_code}] {url} (attempt {attempt})", file=sys.stderr)
        except httpx.HTTPError as exc:
            print(f"  error fetching {url}: {exc} (attempt {attempt})", file=sys.stderr)
        time.sleep(min(60, 2 ** attempt))
    print(f"  giving up on {url}", file=sys.stderr)
    return None


def init_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS threads (
            url TEXT PRIMARY KEY,
            board TEXT NOT NULL,
            title TEXT,
            completed INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_url TEXT NOT NULL,
            author TEXT,
            posted_at TEXT,
            text TEXT,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(thread_url, author, posted_at, text)
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts USING fts5(
            text, thread_title, board, author,
            content='posts', content_rowid='id'
        );
        CREATE TRIGGER IF NOT EXISTS posts_ai AFTER INSERT ON posts BEGIN
            INSERT INTO posts_fts(rowid, text, thread_title, board, author)
            SELECT new.id, new.text, threads.title, threads.board, new.author
            FROM threads WHERE threads.url = new.thread_url;
        END;
        """
    )
    conn.commit()
    return conn


def parse_board_page(html, base_url, sel):
    soup = BeautifulSoup(html, "html.parser")
    thread_urls = []
    for item in soup.select(sel["thread_list_item"]):
        link = item.select_one(sel["thread_link"])
        if link and link.get("href"):
            thread_urls.append(urljoin(base_url, link["href"]))
    next_link = soup.select_one(sel["board_next_page"]) if sel.get("board_next_page") else None
    next_url = urljoin(base_url, next_link["href"]) if next_link and next_link.get("href") else None
    return thread_urls, next_url


def parse_thread_page(html, base_url, sel):
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one(sel["thread_title"])
    title = title_el.get_text(strip=True) if title_el else None

    op_text_el = soup.select_one(sel["op_text"])
    op_post = None
    if op_text_el:
        op_author_el = soup.select_one(sel["op_author"])
        op_date_el = soup.select_one(sel["op_date"]) if sel.get("op_date") else None
        op_post = {
            "author": op_author_el.get_text(strip=True) if op_author_el else None,
            "posted_at": op_date_el.get_text(strip=True) if op_date_el else None,
            "text": op_text_el.get_text("\n", strip=True),
        }

    posts = []
    for post in soup.select(sel["post_container"]):
        author_el = post.select_one(sel["post_author"])
        date_el = post.select_one(sel["post_date"])
        text_el = post.select_one(sel["post_text"])
        posts.append(
            {
                "author": author_el.get_text(strip=True) if author_el else None,
                "posted_at": date_el.get_text(strip=True) if date_el else None,
                "text": text_el.get_text("\n", strip=True) if text_el else None,
            }
        )

    next_link = soup.select_one(sel["thread_next_page"]) if sel.get("thread_next_page") else None
    next_url = urljoin(base_url, next_link["href"]) if next_link and next_link.get("href") else None
    return title, op_post, posts, next_url


def scrape_thread(session, conn, board, thread_url, sel):
    existing = conn.execute(
        "SELECT completed FROM threads WHERE url = ?", (thread_url,)
    ).fetchone()
    if existing and existing[0]:
        return

    conn.execute(
        "INSERT OR IGNORE INTO threads (url, board) VALUES (?, ?)", (thread_url, board)
    )
    conn.commit()

    url = thread_url
    while url:
        html = fetch(session, url)
        if html is None:
            return  # leave incomplete; a re-run will retry from scratch
        title, op_post, posts, next_url = parse_thread_page(html, CONFIG["base_url"], sel)
        if title:
            conn.execute("UPDATE threads SET title = ? WHERE url = ?", (title, thread_url))
        if url == thread_url and op_post and op_post["text"]:
            posts = [op_post] + posts
        for post in posts:
            if not post["text"]:
                continue
            conn.execute(
                """INSERT OR IGNORE INTO posts (thread_url, author, posted_at, text)
                   VALUES (?, ?, ?, ?)""",
                (thread_url, post["author"], post["posted_at"], post["text"]),
            )
        conn.commit()
        print(f"    archived {len(posts)} posts from {url}")
        url = next_url

    conn.execute("UPDATE threads SET completed = 1 WHERE url = ?", (thread_url,))
    conn.commit()


def scrape_board(session, conn, board, sel):
    url = urljoin(CONFIG["base_url"], board)
    page_count = 0
    while url and page_count < CONFIG["max_board_pages"]:
        print(f"  board page: {url}")
        html = fetch(session, url)
        if html is None:
            return
        thread_urls, next_url = parse_board_page(html, CONFIG["base_url"], sel)
        for thread_url in thread_urls:
            print(f"    thread: {thread_url}")
            scrape_thread(session, conn, board, thread_url, sel)
        url = next_url
        page_count += 1


def main():
    sel = CONFIG["selectors"]
    missing = [k for k in REQUIRED_SELECTORS if not sel.get(k)]
    if missing:
        print("Fill in these selectors in CONFIG before running:", missing, file=sys.stderr)
        sys.exit(1)

    session = make_session()
    conn = init_db(CONFIG["db_path"])
    for board in CONFIG["boards"]:
        print(f"board: {board}")
        scrape_board(session, conn, board, sel)
    conn.close()
    session.close()


if __name__ == "__main__":
    main()
