#!/usr/bin/env python3
"""Query the archived posts. Usage: python3 search.py <query> [--limit N]"""

import argparse
import sqlite3
import textwrap

DB_PATH = "dread_archive.sqlite3"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        """
        SELECT board, thread_title, author, snippet(posts_fts, 0, '[', ']', '...', 20)
        FROM posts_fts
        WHERE posts_fts MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
        (args.query, args.limit),
    ).fetchall()

    if not rows:
        print("No matches.")
        return

    for board, title, author, snippet in rows:
        print(f"[{board}] {title!r} - {author}")
        print(textwrap.indent(snippet, "    "))
        print()


if __name__ == "__main__":
    main()
