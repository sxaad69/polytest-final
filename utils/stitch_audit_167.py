import json
import sqlite3
import requests
import os
from datetime import datetime

# CONFIGURATION FOR TRADE #167
TRADE_ID = "167"
CONDITION_ID = "0x92f9e4e75d0b4352062608bda66873249967b3ed5161a19f6e7b3ed5161a19f6e"
DIRECTION = "SHORT"
ENTRY_PRICE = 0.52
SL_PRICE = 0.58
TS_ENTRY = "2026-04-11 14:50:11"
TS_EXIT = "2026-04-11 14:52:22"
LOG_PATH = "/home/ubuntu/polytest_legacy/logs/open_positions.log"

def fetch_token_id(cid):
    print(f"[*] Fetching Token ID for Condition: {cid}")
    url = f"https://gamma-api.polymarket.com/markets?conditionId={cid}"
    resp = requests.get(url)
    data = resp.json()
    if not data: return None
    tokens = data[0].get("clobTokenIds", [])
    if isinstance(tokens, str): tokens = json.loads(tokens)
    # Token 0 is Yes (Long), Token 1 is No (Short)
    return tokens[1] if DIRECTION == "SHORT" else tokens[0]

def extract_logs():
    print(f"[*] Extracting heartbeats from {LOG_PATH}...")
    prices = []
    if not os.path.exists(LOG_PATH): return []
    with open(LOG_PATH, 'r') as f:
        for line in f:
            if f"Trade #{TRADE_ID}" in line and "Internal:" in line:
                try:
                    ts_str = line.split(" [")[0]
                    price_str = line.split("Internal: ")[1].split(" |")[0]
                    prices.append({"t": ts_str, "p": float(price_str), "src": "LOG"})
                except: pass
    return prices

def fetch_tape(token_id):
    print(f"[*] Fetching Trade Tape from CLOB...")
    url = "https://clob.polymarket.com/trades"
    params = {"market": token_id, "limit": 100}
    resp = requests.get(url, params=params)
    data = resp.json()
    tape = []
    for t in data:
        price = float(t['price'])
        ts_unix = int(t['timestamp'])
        dt = datetime.fromtimestamp(ts_unix)
        tape.append({"t": dt.strftime("%Y-%m-%d %H:%M:%S"), "p": price, "src": "TAPE"})
    return tape

def run_audit():
    token_id = fetch_token_id(CONDITION_ID)
    if not token_id:
        print("[!] Failed to find Token ID.")
        return

    log_prices = extract_logs()
    tape_prices = fetch_tape(token_id)
    
    all_prices = log_prices + tape_prices
    # Deduplicate by rounding timestamps slightly to avoid jitter
    all_prices.sort(key=lambda x: x['t'])
    
    print("\n--- RECONSTRUCTED TIMELINE (#167) ---")
    recovered = False
    recovery_price = 0.0
    recovery_time = ""
    
    # We want to see what happened AFTER the exit (14:52:22)
    for p in all_prices:
        marker = ""
        # Check if this point is AFTER the exit
        if p['t'] > TS_EXIT and not recovered:
            if p['p'] <= (ENTRY_PRICE - 0.01): # Reached profit target
                recovered = True
                recovery_price = p['p']
                recovery_time = p['t']
                marker = "<<< RECOVERY DETECTED >>>"
        
        # Only print a reasonable window: from entry to 5 mins after
        print(f"[{p['t']}] {p['p']:.4f} ({p['src']}) {marker}")

    print("\n--- FINAL VERDICT ---")
    if recovered:
        print(f"SHAKEOUT CONFIRMED: Market hit {recovery_price} at {recovery_time}")
        print(f"Profit missed due to 0.05 SL: +${(ENTRY_PRICE - recovery_price):.3f} per share")
    else:
        print("TERMINAL FAILURE: Market never returned to profit zone.")

if __name__ == "__main__":
    run_audit()
