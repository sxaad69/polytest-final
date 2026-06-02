import sqlite3
import requests
import json
import os
from datetime import datetime

GAMMA_API = "https://gamma-api.polymarket.com"
DB_PATH = "data/bot_sniper_paper.db"
OUTPUT_FILE = "logs/truth_resolution_report.txt"

def check_slugs(slugs: list) -> dict:
    results = {}
    for slug in slugs:
        try:
            resp = requests.get(f"{GAMMA_API}/events", params={"slug": slug}, timeout=10)
            if not resp.json():
                results[slug] = {"resolved": False, "winner": "NOT_FOUND"}
                continue
                
            event = resp.json()[0]
            market = event["markets"][0]
            prices = json.loads(market.get("outcomePrices", "[0,0]"))
            
            up_price   = float(prices[0])
            down_price = float(prices[1])

            if up_price == 1.0:
                winner = "LONG"
            elif down_price == 1.0:
                winner = "SHORT"
            else:
                winner = "UNRESOLVED"

            results[slug] = {
                "resolved": (up_price == 1.0 or down_price == 1.0),
                "winner":   winner,
            }
        except Exception as e:
            results[slug] = {"resolved": False, "winner": f"ERROR"}
    return results

def main():
    if not os.path.exists(DB_PATH):
        print(f"Database not found: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Grab unexited trades from the last 2 hours
    cursor.execute('''
        SELECT id, asset, direction, entry_odds, slug, ts_entry 
        FROM trades 
        WHERE exit_odds IS NULL 
        AND ts_entry >= datetime('now', '-2 hours')
    ''')
    trades = cursor.fetchall()
    
    if not trades:
        print("No unexited trades found in the last 2 hours.")
        return

    slugs = list(set([t["slug"] for t in trades if t["slug"]]))
    print(f"Found {len(slugs)} unique unexited slugs. Querying Polymarket Gamma API...")
    
    truth_data = check_slugs(slugs)
    
    report_lines = [
        f"TRUTH RESOLUTION REPORT - {datetime.utcnow().isoformat()[:16]} UTC",
        "="*90,
        f"{'ID':<6} | {'Asset':<5} | {'Dir':<5} | {'Entry':<6} | {'Resolved As':<12} | {'Result':<10} | {'Slug'}",
        "-"*90
    ]
    
    correct = 0
    wrong = 0
    pending = 0

    for t in trades:
        slug = t["slug"]
        td = truth_data.get(slug, {})
        winner = td.get("winner", "UNRESOLVED")
        
        if winner == "UNRESOLVED":
            result = "PENDING"
            pending += 1
        elif winner == str(t["direction"]).upper():
            result = "WIN"
            correct += 1
        else:
            result = "LOSS"
            wrong += 1
            
        report_lines.append(f"{t['id']:<6} | {t['asset']:<5} | {t['direction']:<5} | {t['entry_odds']:<6.3f} | {winner:<12} | {result:<10} | {slug}")

    report_lines.append("="*90)
    total_resolved = correct + wrong
    win_rate = (correct / total_resolved * 100) if total_resolved > 0 else 0
    
    report_lines.append(f"TOTAL HELD TRADES : {len(trades)}")
    report_lines.append(f"WINS (Correct)    : {correct}")
    report_lines.append(f"LOSSES (Wrong)    : {wrong}")
    report_lines.append(f"PENDING (No 1.0)  : {pending}")
    report_lines.append(f"WIN RATE          : {win_rate:.1f}%")

    report_text = "\n".join(report_lines)
    print("\n" + report_text)
    
    os.makedirs("logs", exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        f.write(report_text)
        
    print(f"\nSaved to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
