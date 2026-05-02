import sqlite3
import csv
import glob
import os
from datetime import datetime

# Paths
DB_PATH = "/home/ubuntu/polytest-final/data/bot_g_paper.db"
TAPE_DIR = "/home/ubuntu/polytest-final/logs/"

def parse_t(s):
    s = s.replace('T', ' ')
    if '.' in s:
        s = s.split('.')[0]
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")

def run_audit(sl_threshold=0.05):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    query = "SELECT id, asset, direction, entry_odds, ts_entry, ts_exit, pnl_usdc, slug FROM trades WHERE id >= 220 AND ts_exit IS NOT NULL"
    cursor.execute(query)
    trades = [dict(row) for row in cursor.fetchall()]
    conn.close()

    if not trades:
        print("No trades found in DB for audit.")
        return

    tape_files = glob.glob(os.path.join(TAPE_DIR, "market_tape_*.csv"))
    if not tape_files:
        print(f"No tape files found in {TAPE_DIR}")
        return

    all_ticks = []
    for f in tape_files:
        with open(f, mode='r') as infile:
            reader = csv.DictReader(infile)
            for row in reader:
                all_ticks.append(row)

    print(f"Loaded {len(all_ticks)} ticks from tape.")
    if all_ticks:
        print(f"Sample tick slug: {all_ticks[0]['market_slug']}")
        print(f"Sample trade slug: {trades[0]['slug']}")

    print(f"\n--- MAE AUDIT (SL: {sl_threshold}) ---")
    
    # ... (rest of logic) ...
    winners_analyzed = 0
    losers_analyzed = 0
    killed_winners = []
    saved_losses = []

    for trade in trades:
        entry_t = parse_t(trade['ts_entry'])
        exit_t = parse_t(trade['ts_exit'])
        slug = trade['slug']
        direction = trade['direction']
        entry_price = float(trade['entry_odds'])

        max_pain = 0.0
        found_ticks = 0

        for tick in all_ticks:
            if tick['market_slug'].strip() != slug.strip():
                continue
            
            tick_t = parse_t(tick['timestamp'])

            if entry_t <= tick_t <= exit_t:
                found_ticks += 1
                poly_mid = float(tick['poly_mid'])
                if direction == 'long':
                    pain = entry_price - poly_mid
                else:
                    no_price = 1.0 - poly_mid
                    pain = entry_price - no_price
                if pain > max_pain: max_pain = pain

        if found_ticks == 0: continue

        pnl = float(trade['pnl_usdc'] or 0)
        is_winner = pnl > 0
        survived = max_pain < sl_threshold

        if is_winner:
            winners_analyzed += 1
            if not survived:
                killed_winners.append({"id": trade['id'], "asset": trade['asset'], "pain": round(max_pain, 3)})
        else:
            losers_analyzed += 1
            if max_pain >= sl_threshold:
                saved_losses.append({"id": trade['id'], "asset": trade['asset'], "pain": round(max_pain, 3)})

    print(f"Total Success Trades Analyzed: {winners_analyzed}")
    print(f"Successes that would be KILLED by {sl_threshold} SL: {len(killed_winners)}")
    if killed_winners:
        for kw in killed_winners: print(f"  #{kw['id']} {kw['asset']}: Pain {kw['pain']}")
    print(f"Total Losers Analyzed: {losers_analyzed}")
    print(f"Losses that would be CUT SOONER: {len(saved_losses)}")

if __name__ == "__main__":
    run_audit(0.05)
