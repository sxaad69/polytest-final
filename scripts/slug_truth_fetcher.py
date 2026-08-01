"""
slug_truth_fetcher.py
---------------------
Fetches the true resolution of every trade slug from Polymarket Gamma API.

Features:
- Cache-first: reads logs/slug_truth_cache.txt before hitting the API
- Resume-safe: skips any slug already in the cache
- Rate-limited: 1 request per 0.5s to avoid bans
- Writes results line-by-line as they come in (crash-safe)
- Run once to fetch, run again to update DB from cache

Usage:
  python3 scripts/slug_truth_fetcher.py --fetch    # hit API and build cache
  python3 scripts/slug_truth_fetcher.py --update   # update DB from cache
  python3 scripts/slug_truth_fetcher.py --stats    # show cache stats and odds breakdown
"""

import sqlite3
import requests
import json
import time
import os
import sys
import argparse
from datetime import datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

CONCURRENCY = 30   # concurrent threads — safe for Gamma API

GAMMA_API = "https://gamma-api.polymarket.com"
DB_PATH = "data/bot_sniper_paper_backup.db"
CACHE_FILE = "logs/slug_truth_cache.txt"
RATE_LIMIT_SEC = 0.5  # 2 requests/sec — safe for Gamma API
SINCE_DATE = "2026-06-08 00:00:00"  # Only fetch/update trades from the recent run

# ─── Helpers ──────────────────────────────────────────────────────────────────

def load_cache() -> dict:
    """Load existing cache from disk. Returns {slug: winner} dict."""
    cache = {}
    if not os.path.exists(CACHE_FILE):
        return cache
    with open(CACHE_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if not line or "|" not in line:
                continue
            parts = line.split("|")
            if len(parts) == 2:
                cache[parts[0]] = parts[1]
    return cache


def append_cache(slug: str, winner: str):
    """Append a single result to the cache file immediately."""
    os.makedirs("logs", exist_ok=True)
    with open(CACHE_FILE, "a") as f:
        f.write(f"{slug}|{winner}\n")


def fetch_truth_from_api(slug: str) -> str:
    """Returns 'long', 'short', 'UNRESOLVED', or 'ERROR'."""
    try:
        resp = requests.get(f"{GAMMA_API}/events", params={"slug": slug}, timeout=10)
        data = resp.json()
        if not data:
            return "NOT_FOUND"
        market = data[0]["markets"][0]
        prices = json.loads(market.get("outcomePrices", "[0,0]"))
        if float(prices[0]) == 1.0:
            return "long"
        if float(prices[1]) == 1.0:
            return "short"
        return "UNRESOLVED"
    except Exception as e:
        return "ERROR"


def get_all_slugs_from_db() -> list:
    """Get every unique slug from the 2-day run that needs truth checking."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT slug, direction
        FROM trades
        WHERE slug IS NOT NULL
        AND ts_entry >= ?
        AND (exit_reason IS NULL OR exit_reason != 'truth_settled')
    """, (SINCE_DATE,))
    rows = cur.fetchall()
    conn.close()
    return rows  # list of (slug, direction)


# ─── Mode 1: Fetch ─────────────────────────────────────────────────────────────

def fetch_mode():
    import threading
    cache_lock = threading.Lock()

    print(f"[FETCH] Loading existing cache from {CACHE_FILE}...")
    cache = load_cache()
    print(f"[FETCH] Cache has {len(cache)} slugs already resolved. Skipping those.")

    print("[FETCH] Loading all unique slugs from database...")
    slug_rows = get_all_slugs_from_db()
    unique_slugs = list(set([row[0] for row in slug_rows]))

    pending = [s for s in unique_slugs if s not in cache]
    print(f"[FETCH] Total unique slugs : {len(unique_slugs)}")
    print(f"[FETCH] Pending (not cached): {len(pending)}")
    print(f"[FETCH] Concurrency        : {CONCURRENCY} threads")

    if not pending:
        print("[FETCH] All slugs already cached! Run --update to apply to DB.")
        return

    eta_minutes = (len(pending) / CONCURRENCY) * 0.5 / 60
    print(f"[FETCH] Estimated time     : ~{eta_minutes:.1f} minutes")
    print("[FETCH] Starting... (safe to Ctrl+C and resume anytime)\n")

    done = 0
    errors = 0

    def fetch_and_cache(slug):
        winner = fetch_truth_from_api(slug)
        with cache_lock:
            append_cache(slug, winner)
        return winner

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        futures = {executor.submit(fetch_and_cache, slug): slug for slug in pending}
        for future in as_completed(futures):
            winner = future.result()
            done += 1
            if winner == "ERROR":
                errors += 1
            if done % 200 == 0:
                pct = done / len(pending) * 100
                print(f"  [{datetime.now().strftime('%H:%M:%S')}] {done}/{len(pending)} ({pct:.1f}%) | Errors: {errors}")

    print(f"\n[FETCH] Done! Fetched {done} slugs. Errors: {errors}")
    print(f"[FETCH] Cache saved to {CACHE_FILE}")
    print("[FETCH] Run --update to apply results to the database.")


# ─── Mode 2: Update DB ─────────────────────────────────────────────────────────

def update_mode():
    print(f"[UPDATE] Loading cache from {CACHE_FILE}...")
    cache = load_cache()
    print(f"[UPDATE] Cache has {len(cache)} resolved slugs.")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Fetch all trades that need resolution
    cur.execute("""
        SELECT id, direction, slug, stake_usdc, entry_odds
        FROM trades
        WHERE slug IS NOT NULL
        AND ts_entry >= ?
        AND exit_reason IS NULL
        AND resolved = 0
    """, (SINCE_DATE,))
    trades = [dict(r) for r in cur.fetchall()]
    print(f"[UPDATE] Found {len(trades)} unresolved held trades to update.")

    updated = skipped = 0
    for t in trades:
        winner = cache.get(t["slug"])
        if not winner or winner in ("UNRESOLVED", "ERROR", "NOT_FOUND"):
            skipped += 1
            continue

        exit_odds = 1.0 if winner == str(t["direction"]).lower() else 0.0
        cur.execute("""
            UPDATE trades
            SET exit_odds = ?,
                exit_reason = 'truth_settled',
                resolved = 1,
                ts_exit = datetime('now')
            WHERE id = ?
        """, (exit_odds, t["id"]))
        updated += 1

    conn.commit()
    conn.close()

    print(f"[UPDATE] Updated {updated} trades in the database.")
    print(f"[UPDATE] Skipped {skipped} (still unresolved or not in cache).")


# ─── Mode 3: Stats ─────────────────────────────────────────────────────────────

def stats_mode():
    print(f"[STATS] Loading cache from {CACHE_FILE}...")
    cache = load_cache()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT id, direction, slug, stake_usdc, entry_odds, exit_reason
        FROM trades
        WHERE slug IS NOT NULL
        AND ts_entry >= ?
    """, (SINCE_DATE,))
    trades = [dict(r) for r in cur.fetchall()]
    conn.close()

    # Buckets
    buckets = defaultdict(lambda: {"wins": 0, "losses": 0, "unresolved": 0})

    for t in trades:
        winner = cache.get(t["slug"])
        if not winner or winner in ("UNRESOLVED", "ERROR", "NOT_FOUND"):
            continue

        # Odds bucket
        e = t["entry_odds"]
        if e < 0.52: bucket = "0.50-0.52"
        elif e < 0.54: bucket = "0.52-0.54"
        elif e < 0.56: bucket = "0.54-0.56"
        elif e < 0.58: bucket = "0.56-0.58"
        elif e < 0.60: bucket = "0.58-0.60"
        elif e < 0.65: bucket = "0.60-0.65"
        elif e < 0.70: bucket = "0.65-0.70"
        elif e < 0.80: bucket = "0.70-0.80"
        else: bucket = "0.80+"

        if winner == str(t["direction"]).lower():
            buckets[bucket]["wins"] += 1
        else:
            buckets[bucket]["losses"] += 1

    print("\n" + "="*65)
    print("WIN RATE BY ENTRY ODDS — FULL DATABASE (ALL EXITS COMBINED)")
    print("="*65)
    print(f"{'Odds Range':<14} | {'Total':>6} | {'Wins':>6} | {'Losses':>7} | {'Win Rate':>9}")
    print("-"*65)

    breakeven = 53.0
    for bucket in sorted(buckets.keys()):
        d = buckets[bucket]
        total = d["wins"] + d["losses"]
        if total == 0:
            continue
        wr = d["wins"] / total * 100
        flag = "✅" if wr > breakeven else "❌"
        print(f"{bucket:<14} | {total:>6} | {d['wins']:>6} | {d['losses']:>7} | {wr:>8.1f}% {flag}")

    print("="*65)
    print(f"Break-even win rate at ~0.53 entry odds ≈ {breakeven}%")


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Slug Truth Fetcher & DB Updater")
    parser.add_argument("--fetch",  action="store_true", help="Fetch truth from Gamma API into cache")
    parser.add_argument("--update", action="store_true", help="Update database from cache file")
    parser.add_argument("--stats",  action="store_true", help="Show win rate stats by entry odds bucket")
    args = parser.parse_args()

    if args.fetch:
        fetch_mode()
    elif args.update:
        update_mode()
    elif args.stats:
        stats_mode()
    else:
        print("Usage:")
        print("  python3 scripts/slug_truth_fetcher.py --fetch    # hit API and build cache")
        print("  python3 scripts/slug_truth_fetcher.py --update   # update DB from cache")
        print("  python3 scripts/slug_truth_fetcher.py --stats    # show win rate by odds bucket")
