#!/usr/bin/env python3
"""One-off: fetch a single URL with the same client setup as scrape.py and
dump what actually came back, to diagnose why selectors matched nothing."""

import sys

from scrape import CONFIG, make_session

url = sys.argv[1] if len(sys.argv) > 1 else CONFIG["base_url"] + "/d/carding"

session = make_session()
resp = session.get(url)
print(f"status: {resp.status_code}")
print(f"final url: {resp.url}")
print(f"length: {len(resp.text)} chars")
print("---- first 2000 chars ----")
print(resp.text[:2000])
session.close()
