import sqlite3
import requests
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

GAMMA_API = "https://gamma-api.polymarket.com"
DB_PATH = "data/bot_sniper_paper.db"

def fetch_truth(slug):
    try:
        resp = requests.get(f"{GAMMA_API}/events", params={"slug": slug}, timeout=10)
        data = resp.json()
        if not data: return slug, "NOT_FOUND"
        event = data[0]
        market = event["markets"][0]
        prices = json.loads(market.get("outcomePrices", "[0,0]"))
        if float(prices[0]) == 1.0: return slug, "long"
        if float(prices[1]) == 1.0: return slug, "short"
        return slug, "UNRESOLVED"
    except Exception:
        return slug, "ERROR"

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    print("Fetching momentum_failure exits from the last 48 hours...")
    cur.execute("""
        SELECT id, asset, direction, exit_reason, pnl_usdc, slug 
        FROM trades 
        WHERE ts_entry >= datetime('now', '-48 hours') 
        AND exit_reason = 'momentum_failure'
        AND slug IS NOT NULL
    """)
    trades = [dict(r) for r in cur.fetchall()]
    conn.close()

    if not trades:
        print("No early cuts found.")
        return

    unique_slugs = list(set([t["slug"] for t in trades]))
    print(f"Found {len(trades)} early cuts across {len(unique_slugs)} unique markets.")
    print("Querying Polymarket for the true resolutions... This may take a minute.")

    results = {}
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_slug = {executor.submit(fetch_truth, slug): slug for slug in unique_slugs}
        completed = 0
        for future in as_completed(future_to_slug):
            slug, winner = future.result()
            results[slug] = winner
            completed += 1
            if completed % 50 == 0:
                print(f"Processed {completed}/{len(unique_slugs)} markets...")

    would_be_winners = []
    would_be_losers = []
    unresolved = 0

    for t in trades:
        winner = results.get(t["slug"], "ERROR")
        if winner == "UNRESOLVED" or winner == "ERROR" or winner == "NOT_FOUND":
            unresolved += 1
            continue
            
        if winner == str(t["direction"]).lower():
            would_be_winners.append(t)
        else:
            would_be_losers.append(t)

    print("\n" + "="*50)
    print("FINAL AUDIT RESULTS (LAST 48 HOURS - MOMENTUM FAILURE ONLY)")
    print("="*50)
    print(f"Total Early Cuts Analyzed: {len(trades) - unresolved}")
    print(f"Premature Exits (Would have WON $1.00) : {len(would_be_winners)}")
    print(f"Good Exits      (Correctly cut losers)  : {len(would_be_losers)}")
    print("-" * 50)
    
    if len(trades) - unresolved > 0:
        mistake_rate = (len(would_be_winners) / (len(trades) - unresolved)) * 100
        print(f"Mistake Rate (Winners we accidentally cut): {mistake_rate:.1f}%")
        
        # Calculate theoretical PnL swing
        # Assuming minimum $5.00 stake per trade
        # A cut costs roughly -$1.27
        # A win gains roughly +$4.00 (depends on odds, assuming 0.55 entry)
        print(f"\nIf we had diamond-handed all of these instead of cutting:")
        print(f"- We would have gained {len(would_be_winners)} full wins.")
        print(f"- We would have taken full -$5.00 losses on the {len(would_be_losers)} bad trades.")

if __name__ == "__main__":
    main()
