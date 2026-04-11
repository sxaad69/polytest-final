import json
import urllib.request
import urllib.parse
from datetime import datetime
from typing import Optional

GAMMA_API   = "https://gamma-api.polymarket.com"

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
        print(f"[ERROR] API GET failed: {e}")
    return None

def fetch_condition_id(slug: str) -> Optional[str]:
    data = api_get(f"{GAMMA_API}/markets", {"slug": slug})
    if data and len(data) > 0: return data[0].get("conditionId")
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
        if str(price) in ("1", "1.0", 1, 1.0): return outcome
    return None

def analyze_sl(direction: str, exit_odds: float, prices: list[dict]) -> dict:
    if not prices: return {"verdict": "no_data", "post_sl_last": None}
    price_values = [float(p["p"]) for p in prices]
    post_sl_last = price_values[-1]
    
    if direction == "long":
        verdict = "bad_sl" if post_sl_last > exit_odds else "good_sl"
    elif direction == "short":
        verdict = "bad_sl" if post_sl_last < exit_odds else "good_sl"
    else:
        verdict = "unknown"
    return {"verdict": verdict, "post_sl_last": round(post_sl_last, 4)}

# ─── Isolated Trial Run ─────────────────────────────────────────────────────

def main():
    # Sampling 5 real trades from your session
    test_rows = [
        {"slug": "btc-updown-5m-1773950100", "exit_timestamp": "2026-04-10T17:59:58Z", "window_end": "2026-04-10T18:05:00Z", "direction": "short", "exit_odds": 0.1},
        {"slug": "btc-updown-5m-1773950700", "exit_timestamp": "2026-04-10T18:06:58Z", "window_end": "2026-04-10T18:12:00Z", "direction": "long", "exit_odds": 0.1},
        {"slug": "btc-updown-5m-1773951300", "exit_timestamp": "2026-04-10T18:11:58Z", "window_end": "2026-04-10T18:18:00Z", "direction": "long", "exit_odds": 0.1},
        {"slug": "btc-updown-5m-1773951900", "exit_timestamp": "2026-04-10T18:17:58Z", "window_end": "2026-04-10T18:24:00Z", "direction": "long", "exit_odds": 0.1},
        {"slug": "btc-updown-5m-1773952500", "exit_timestamp": "2026-04-10T18:23:59Z", "window_end": "2026-04-10T18:30:00Z", "direction": "short", "exit_odds": 0.1}
    ]

    print(f"Bypassing DB locks for Trial: Processing {len(test_rows)} test trades...\n")
    for row in test_rows:
        slug = row["slug"]
        c_id = fetch_condition_id(slug)
        if not c_id: continue
        prices = fetch_price_after_sl(c_id, row["exit_timestamp"], row["window_end"])
        outcome = fetch_resolved_outcome(slug)
        analysis = analyze_sl(row["direction"], row["exit_odds"], prices)
        
        print(f"Audit: {slug}")
        print(f"  -> Truth: {outcome} | Verdict: {analysis['verdict']} | (Exit Odds: {row['exit_odds']} vs Post-SL Last: {analysis['post_sl_last']})")

if __name__ == "__main__":
    main()
