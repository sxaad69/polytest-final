import json
import sqlite3
import requests
import os
import time
from datetime import datetime

# CONFIGURATION
# Using relative path for robustness inside the root dir
DB_PATH = "/home/ubuntu/polytest_legacy/bot_g_paper.db"
LOG_PATH = "logs/open_positions.log"
BATCH_SIZE = 25

def fetch_token_id(cid, direction):
    try:
        url = f"https://gamma-api.polymarket.com/markets?conditionId={cid}"
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if not data: return None
        tokens = data[0].get("clobTokenIds", [])
        if isinstance(tokens, str): tokens = json.loads(tokens)
        # 0: Yes (Long), 1: No (Short)
        return tokens[1] if direction.upper() == "SHORT" else tokens[0]
    except: return None

def extract_logs_for_trade(trade_id):
    prices = []
    if not os.path.exists(LOG_PATH): return []
    with open(LOG_PATH, 'r') as f:
        for line in f:
            if f"Trade #{trade_id} " in line and "Internal:" in line:
                try:
                    ts_str = line.split(" [")[0]
                    price_str = line.split("Internal: ")[1].split(" |")[0]
                    prices.append({"t": ts_str, "p": float(price_str), "src": "LOG"})
                except: pass
    return prices

def fetch_tape(token_id):
    try:
        # Fetch actual trade history (tape)
        url = "https://clob.polymarket.com/trades"
        params = {"market": token_id, "limit": 100}
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200: return []
        data = resp.json()
        tape = []
        for t in data:
            price = float(t['price'])
            ts_unix = int(t['timestamp'])
            dt = datetime.fromtimestamp(ts_unix)
            tape.append({"t": dt.strftime("%Y-%m-%d %H:%M:%S"), "p": price, "src": "TAPE"})
        return tape
    except: return []

def audit_single(trade):
    trade_id = trade['trade_id']
    print(f"[*] Auditing Trade #{trade_id} ({trade['slug']})...")
    
    token_id = fetch_token_id(trade['market_id'], trade['direction'])
    if not token_id: return {"trade_id": trade_id, "error": "no_token_id"}
    
    log_prices = extract_logs_for_trade(trade_id)
    tape_prices = fetch_tape(token_id)
    
    all_p = log_prices + tape_prices
    all_p.sort(key=lambda x: x['t'])
    
    entry_price = float(trade['entry_odds'])
    direction = trade['direction'].upper()
    ts_exit = trade['ts_exit']
    
    recovered = False
    best_recovery = 0.0
    
    for p in all_p:
        if p['t'] > ts_exit and not recovered:
            if direction == "SHORT":
                if p['p'] <= (entry_price - 0.01):
                    recovered = True
                    best_recovery = p['p']
            else:
                if p['p'] >= (entry_price + 0.01):
                    recovered = True
                    best_recovery = p['p']
    
    return {
        "trade_id": trade_id,
        "slug": trade['slug'],
        "outcome": "SHAKEOUT" if recovered else "REAL_FAILURE",
        "recovery": best_recovery if recovered else None,
        "ticks": len(all_p)
    }

def main(offset):
    if not os.path.exists(DB_PATH):
        print(f"[!] DB NOT FOUND: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    print(f"[*] Opening DB: {os.path.abspath(DB_PATH)}")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    # Explicitly find all hard_sl_hit trades
    cur.execute(f"SELECT trade_id, slug, market_id, ts_entry, ts_exit, direction, entry_odds FROM trades WHERE exit_reason = 'hard_sl_hit' ORDER BY rowid ASC LIMIT {BATCH_SIZE} OFFSET {offset}")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    print(f"[*] Starting Batch (Offset {offset}, Count {len(rows)})")
    results = []
    for r in rows:
        results.append(audit_single(r))
        time.sleep(3) # Safe delay
        
    out_file = f"audit_results_off_{offset}.json"
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)
    
    shakeouts = len([x for x in results if x.get('outcome') == "SHAKEOUT"])
    print(f"\n--- BATCH {offset} SUMMARY ---")
    print(f"Success: {shakeouts} SHAKEOUTS detected out of {len(results)} trades.")
    print(f"Results saved to: {out_file}")

if __name__ == "__main__":
    import sys
    off = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    main(off)
