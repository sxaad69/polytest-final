import json
import requests
import os
import time
from datetime import datetime

# CONFIGURATION
TRADES_JSON = "/home/ubuntu/polytest_legacy/final_21_trades.json"
LOG_PATH = "/home/ubuntu/polytest_legacy/logs/open_positions.log"

def fetch_token_id(cid, direction):
    try:
        url = f"https://gamma-api.polymarket.com/markets?conditionId={cid}"
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if not data: return None
        tokens = data[0].get("clobTokenIds", [])
        if isinstance(tokens, str): tokens = json.loads(tokens)
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
        url = "https://clob.polymarket.com/trades"
        params = {"market": token_id, "limit": 100}
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        tape = []
        for t in data:
            price = float(t['price'])
            dt = datetime.fromtimestamp(int(t['timestamp']))
            tape.append({"t": dt.strftime("%Y-%m-%d %H:%M:%S"), "p": price, "src": "TAPE"})
        return tape
    except: return []

def main():
    with open(TRADES_JSON, 'r') as f:
        trades = json.load(f)

    print(f"[*] Starting Final JSON Audit (Count: {len(trades)})")
    results = []
    for trade in trades:
        trade_id = trade['trade_id']
        print(f"[*] Auditing Trade #{trade_id}...")
        
        token_id = fetch_token_id(trade['market_id'], trade['direction'])
        if not token_id: 
            results.append({"trade_id": trade_id, "error": "no_token"})
            continue
            
        logs = extract_logs_for_trade(trade_id)
        tape = fetch_tape(token_id)
        all_p = sorted(logs + tape, key=lambda x: x['t'])
        
        entry = float(trade['entry_odds'])
        direction = trade['direction'].upper()
        ts_exit = trade['ts_exit']
        
        recovered = False
        for p in all_p:
            if p['t'] > ts_exit and not recovered:
                if (direction == "SHORT" and p['p'] <= entry - 0.01) or (direction == "LONG" and p['p'] >= entry + 0.01):
                    recovered = True
        
        results.append({"trade_id": trade_id, "outcome": "SHAKEOUT" if recovered else "REAL_FAILURE"})
        time.sleep(3)

    out_file = "/home/ubuntu/polytest_legacy/audit_results_final_21.json"
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)
    
    shakeouts = len([x for x in results if x.get("outcome") == "SHAKEOUT"])
    print(f"\n--- FINAL BATCH SUMMARY ---")
    print(f"Success: {shakeouts} SHAKEOUTS out of {len(results)} trades.")

if __name__ == "__main__":
    main()
