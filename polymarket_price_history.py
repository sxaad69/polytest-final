"""
Polymarket Price History Fetcher
=================================
Fetches 1-minute resolution price history for crypto up/down prediction markets
on Polymarket (BTC, ETH, SOL, XRP, DOGE) using the CLOB + Gamma APIs.

Runs on a configurable loop (default: every 5 minutes).
Saves output to JSON files in OUTPUT_DIR.

Usage:
    pip install requests
    python polymarket_price_history.py
"""

import requests
import json
import os
import time
import logging
from datetime import datetime, timezone, timedelta

# ─────────────────────────────────────────────
# CONFIG — edit these values freely
# ─────────────────────────────────────────────
ASSETS              = ["btc", "eth", "sol", "xrp", "doge"]  # lowercase
MARKET_INTERVAL     = "5m"          # Polymarket market duration: "5m" or "15m"
FETCH_EVERY_MINUTES = 5             # how often the loop runs
LOOKBACK_HOURS      = 1            # how far back to pull price history
FIDELITY_MINUTES    = 1            # resolution of price history (1 = 1-minute candles)
OUTPUT_DIR          = "./price_history"

# ─────────────────────────────────────────────
# API ENDPOINTS
# ─────────────────────────────────────────────
GAMMA_BASE  = "https://gamma-api.polymarket.com"
CLOB_BASE   = "https://clob.polymarket.com"

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def get_server_time() -> int:
    """Get Polymarket server time (Unix seconds). Falls back to local UTC."""
    try:
        resp = requests.get(f"{CLOB_BASE}/time", timeout=5)
        resp.raise_for_status()
        return int(resp.json().get("time", time.time()))
    except Exception:
        return int(time.time())


def round_down_to_interval(ts: int, interval_minutes: int) -> int:
    """Round a Unix timestamp down to the nearest N-minute boundary."""
    interval_sec = interval_minutes * 60
    return (ts // interval_sec) * interval_sec


def build_slug(asset: str, interval: str, ts: int) -> str:
    """Build a Polymarket event slug, e.g. 'btc-updown-5m-1771168800'."""
    return f"{asset}-updown-{interval}-{ts}"


def fetch_market_token_ids(slug: str) -> dict | None:
    """
    Query Gamma API for a market by slug.
    Returns dict with keys: question, yes_token_id, no_token_id, condition_id
    or None if not found.
    """
    try:
        url = f"{GAMMA_BASE}/markets"
        params = {"slug": slug}
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        markets = data if isinstance(data, list) else data.get("markets", [])
        if not markets:
            return None

        market = markets[0]
        clob_token_ids = market.get("clobTokenIds") or market.get("clob_token_ids")

        # clobTokenIds is either a JSON string or already a list
        if isinstance(clob_token_ids, str):
            clob_token_ids = json.loads(clob_token_ids)

        if not clob_token_ids or len(clob_token_ids) < 2:
            return None

        return {
            "question":    market.get("question", slug),
            "condition_id": market.get("conditionId", ""),
            "yes_token_id": clob_token_ids[0],
            "no_token_id":  clob_token_ids[1],
        }

    except Exception as e:
        log.warning(f"  Gamma API error for slug '{slug}': {e}")
        return None


def fetch_price_history(token_id: str, start_ts: int, end_ts: int) -> list[dict]:
    """
    Fetch price history from CLOB API.
    Returns list of {t: unix_ts, p: float} dicts.
    """
    try:
        url = f"{CLOB_BASE}/prices-history"
        params = {
            "market":   token_id,
            "startTs":  start_ts,
            "endTs":    end_ts,
            "fidelity": FIDELITY_MINUTES,
        }
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json().get("history", [])

    except Exception as e:
        log.warning(f"  CLOB API error for token '{token_id[:16]}...': {e}")
        return []


def fetch_current_price(token_id: str) -> float | None:
    """Fetch best mid price for a token from CLOB order book."""
    try:
        resp = requests.get(
            f"{CLOB_BASE}/midpoint",
            params={"token_id": token_id},
            timeout=5,
        )
        resp.raise_for_status()
        mid = resp.json().get("mid")
        return float(mid) if mid is not None else None
    except Exception:
        return None


def save_results(results: list[dict], run_ts: int) -> None:
    """Save results to a timestamped JSON file and overwrite latest.json."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    dt_str = datetime.fromtimestamp(run_ts, tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    timestamped_path = os.path.join(OUTPUT_DIR, f"price_history_{dt_str}.json")
    latest_path      = os.path.join(OUTPUT_DIR, "latest.json")

    payload = {
        "run_at_utc": datetime.fromtimestamp(run_ts, tz=timezone.utc).isoformat(),
        "config": {
            "assets":           ASSETS,
            "market_interval":  MARKET_INTERVAL,
            "lookback_hours":   LOOKBACK_HOURS,
            "fidelity_minutes": FIDELITY_MINUTES,
        },
        "markets": results,
    }

    with open(timestamped_path, "w") as f:
        json.dump(payload, f, indent=2)

    with open(latest_path, "w") as f:
        json.dump(payload, f, indent=2)

    log.info(f"  Saved → {timestamped_path}")
    log.info(f"  Saved → {latest_path}")


# ─────────────────────────────────────────────
# CORE LOOP
# ─────────────────────────────────────────────

def run_once() -> None:
    """One full fetch cycle: discover markets → fetch history → save."""
    server_ts = get_server_time()
    interval_minutes = int(MARKET_INTERVAL.replace("m", ""))
    market_ts = round_down_to_interval(server_ts, interval_minutes)

    start_ts = server_ts - int(LOOKBACK_HOURS * 3600)
    end_ts   = server_ts

    log.info(
        f"Fetching price history | "
        f"market_ts={market_ts} | "
        f"window={LOOKBACK_HOURS}h | "
        f"fidelity={FIDELITY_MINUTES}m"
    )

    results = []

    for asset in ASSETS:
        log.info(f"[{asset.upper()}] Looking up market...")

        # Try current interval, then fallback to previous interval
        market_info = None
        for offset in [0, -interval_minutes]:
            ts_try = market_ts + (offset * 60)
            slug   = build_slug(asset, MARKET_INTERVAL, ts_try)
            log.info(f"  Trying slug: {slug}")
            market_info = fetch_market_token_ids(slug)
            if market_info:
                log.info(f"  Found: {market_info['question']}")
                break

        if not market_info:
            log.warning(f"  [{asset.upper()}] No active market found — skipping.")
            results.append({
                "asset":   asset.upper(),
                "status":  "no_market_found",
                "history": [],
            })
            continue

        # Fetch YES token price history
        history = fetch_price_history(market_info["yes_token_id"], start_ts, end_ts)
        current_price = fetch_current_price(market_info["yes_token_id"])

        # Enrich history with human-readable timestamps
        enriched = []
        for point in history:
            enriched.append({
                "unix_ts":    point["t"],
                "utc_time":   datetime.fromtimestamp(point["t"], tz=timezone.utc).isoformat(),
                "yes_price":  round(float(point["p"]), 4),
                "no_price":   round(1.0 - float(point["p"]), 4),
            })

        log.info(
            f"  [{asset.upper()}] {len(enriched)} data points | "
            f"current price: {current_price}"
        )

        results.append({
            "asset":         asset.upper(),
            "status":        "ok",
            "question":      market_info["question"],
            "condition_id":  market_info["condition_id"],
            "yes_token_id":  market_info["yes_token_id"],
            "no_token_id":   market_info["no_token_id"],
            "current_yes_price": current_price,
            "data_points":   len(enriched),
            "history":       enriched,
        })

    save_results(results, server_ts)
    log.info("─" * 60)


def main() -> None:
    log.info("=" * 60)
    log.info("Polymarket Price History Fetcher")
    log.info(f"  Assets:          {[a.upper() for a in ASSETS]}")
    log.info(f"  Market interval: {MARKET_INTERVAL}")
    log.info(f"  Fetch every:     {FETCH_EVERY_MINUTES} min")
    log.info(f"  Lookback:        {LOOKBACK_HOURS} hour(s)")
    log.info(f"  Fidelity:        {FIDELITY_MINUTES} min candles")
    log.info(f"  Output dir:      {os.path.abspath(OUTPUT_DIR)}")
    log.info("=" * 60)

    while True:
        try:
            run_once()
        except KeyboardInterrupt:
            log.info("Interrupted. Exiting.")
            break
        except Exception as e:
            log.error(f"Unexpected error: {e}", exc_info=True)

        log.info(f"Sleeping {FETCH_EVERY_MINUTES} minutes...")
        try:
            time.sleep(FETCH_EVERY_MINUTES * 60)
        except KeyboardInterrupt:
            log.info("Interrupted during sleep. Exiting.")
            break


if __name__ == "__main__":
    main()
