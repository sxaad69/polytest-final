import sqlite3
import json
import os
import urllib.request
import urllib.parse
from datetime import datetime
from typing import Optional

GAMMA_API   = "https://gamma-api.polymarket.com"
DB_PATH = "data/bot_g_paper.db"

# ─── Helpers ────────────────────────────────────────────────────────────────

def ts_to_unix(ts: str) -> int:
    dt_str = ts.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(dt_str)
    except ValueError:
        dt = datetime.strptime(dt_str.split('.')[0], "%Y-%m-%d %H:%M:%S")
    return int(dt.timestamp())

def api_get(url: str, params: dict = None) -> Optional[dict]:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.getcode() == 200:
                return json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        print(f"[ERROR] API GET failed: {e} | URL: {url}")
    return None


# ─── Audit Steps ────────────────────────────────────────────────────────────

def fetch_condition_id(slug: str) -> Optional[str]:
    data = api_get(f"{GAMMA_API}/markets", {"slug": slug})
    if data and len(data) > 0:
        return data[0].get("conditionId")
    return None

def fetch_price_after_sl(condition_id: str, ts_exit: str, window_end: str) -> list[dict]:
    params = {
        "market":   condition_id,
        "startTs":  ts_to_unix(ts_exit),
        "endTs":    ts_to_unix(window_end),
        "interval": "1m",
        "fidelity": 60,
    }
    data = api_get(f"{GAMMA_API}/prices-history", params)
    return data.get("history", []) if data else []

def fetch_resolved_outcome(slug: str) -> Optional[str]:
    data = api_get(f"{GAMMA_API}/markets", {"slug": slug})
    if not data: return None
    market = data[0]
    if not market.get("resolved"): return "not_resolved"
    
    outcomes = market.get("outcomes", "[]")
    if isinstance(outcomes, str): outcomes = json.loads(outcomes)
    
    prices = market.get("outcomePrices", "[]")
    if isinstance(prices, str): prices = json.loads(prices)
    
    for outcome, price in zip(outcomes, prices):
        if str(price) in ("1", "1.0", 1, 1.0):
            return outcome
    return None

def analyze_sl(direction: str, exit_odds: float, prices: list[dict]) -> dict:
    if not prices:
        return {"verdict": "no_data", "post_sl_last": None}

    price_values = [float(p["p"]) for p in prices]
    post_sl_last = price_values[-1]

    if direction == "long":
        verdict = "bad_sl" if post_sl_last > exit_odds else "good_sl"
    elif direction == "short":
        verdict = "bad_sl" if post_sl_last < exit_odds else "good_sl"
    else:
        verdict = "unknown"

    return {
        "verdict": verdict,
        "post_sl_last": round(post_sl_last, 4),
    }

# ─── Main Logic ─────────────────────────────────────────────────────────────

def main():
    if not os.path.exists(DB_PATH):
        print(f"Database {DB_PATH} not found.")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT slug, exit_timestamp, window_end, direction, entry_odds, exit_odds
        FROM trades
        WHERE exit_reason = 'hard_sl_hit'
        ORDER BY exit_timestamp ASC
        LIMIT 5
    """)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    if not rows:
        print("No hard_sl_hit trades found.")
        return

    print(f"Trial Run (Headers Refined): Processing {len(rows)} trades...\n")
    results = []

    for i, row in enumerate(rows):
        slug = row["slug"]
        print(f"[{i+1}/{len(rows)}] Auditing: {slug}")
        
        c_id = fetch_condition_id(slug)
        if not c_id:
            print(f"  !! No condition ID found for {slug}")
            continue
            
        prices = fetch_price_after_sl(c_id, row["exit_timestamp"], row["window_end"])
        outcome = fetch_resolved_outcome(slug)
        analysis = analyze_sl(row["direction"], row["exit_odds"], prices)
        
        report = {**row, "resolved": outcome, **analysis}
        results.append(report)
        print(f"  -> Truth: {outcome} | Verdict: {analysis['verdict']} | Post-SL Last: {analysis['post_sl_last']}")

    # Summary report to console
    print(f"\n{'='*45}")
    print(f"TRIAL COMPLETE: Found {len(results)} results.")
    print(f"{'='*45}")
    
    with open("trial_sl_analysis.json", "w") as f:
        json.dump(results, f, indent=2, default=str)

if __name__ == "__main__":
    main()
