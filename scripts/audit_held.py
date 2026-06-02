import sqlite3
import requests
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

GAMMA_API = "https://gamma-api.polymarket.com"
DB_PATH = "data/bot_sniper_paper.db"

def fetch_truth(slug):
    try:
        resp = requests.get(f"{GAMMA_API}/events", params={"slug": slug}, timeout=10)
        data = resp.json()
        if not data: return slug, "NOT_FOUND"
        market = data[0]["markets"][0]
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

    print("Fetching all trades held to 5-minute settlement (last 48 hours)...")
    cur.execute("""
        SELECT id, asset, direction, stake_usdc, slug 
        FROM trades 
        WHERE exit_reason IS NULL
        AND resolved = 0
        AND slug IS NOT NULL
        AND ts_entry >= datetime('now', '-48 hours')
    """)
    trades = [dict(r) for r in cur.fetchall()]
    conn.close()

    if not trades:
        print("No unresolved held trades found.")
        return

    unique_slugs = list(set([t["slug"] for t in trades]))
    print(f"Found {len(trades)} held trades across {len(unique_slugs)} unique markets.")
    print("Querying Polymarket Gamma API for true resolutions...")

    results = {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_truth, slug): slug for slug in unique_slugs}
        completed = 0
        for future in as_completed(futures):
            slug, winner = future.result()
            results[slug] = winner
            completed += 1
            if completed % 100 == 0:
                print(f"Processed {completed}/{len(unique_slugs)} markets...")

    wins = []
    losses = []
    unresolved = []

    for t in trades:
        winner = results.get(t["slug"], "ERROR")
        if winner in ("UNRESOLVED", "ERROR", "NOT_FOUND"):
            unresolved.append(t)
        elif winner == str(t["direction"]).lower():
            wins.append(t)
        else:
            losses.append(t)

    total_analyzed = len(wins) + len(losses)
    win_rate = (len(wins) / total_analyzed * 100) if total_analyzed > 0 else 0

    total_staked = sum(t["stake_usdc"] for t in wins + losses)
    # Win: receive 1.0 per share, profit = (1 - entry_price) * shares ≈ stake/entry_odds - stake
    # Simple approximation: full payout = stake / entry_odds, net = payout - stake
    # Since we don't have shares count, use pnl approximation from stake
    # Just count stake recovered on wins vs lost on losses
    total_win_payouts = sum(t["stake_usdc"] for t in wins)  # Got full stake back + profit
    total_loss_stakes = sum(t["stake_usdc"] for t in losses)  # Lost full stake

    print("\n" + "="*55)
    print("FINAL AUDIT: TRADES HELD TO 5-MINUTE SETTLEMENT")
    print("="*55)
    print(f"Total Held Trades Analyzed  : {total_analyzed}")
    print(f"Still Unresolved (recent)   : {len(unresolved)}")
    print(f"WON (Resolved LONG/SHORT ✓) : {len(wins)}")
    print(f"LOST (Wrong direction ✗)    : {len(losses)}")
    print(f"Win Rate on Held Trades     : {win_rate:.1f}%")
    print("-"*55)
    print(f"Capital at Risk on Held     : ${total_staked:.2f}")
    print(f"Stake on Winners            : ${total_win_payouts:.2f}")
    print(f"Stake on Losers             : ${total_loss_stakes:.2f}")

if __name__ == "__main__":
    main()
