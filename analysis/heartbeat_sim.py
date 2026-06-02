import sqlite3
import pandas as pd
import os
import glob
import re
import warnings
warnings.filterwarnings('ignore')

DB_PATH = "data/aws/bot_sniper_paper_2026-05-05.db"
LOG_DIR = "logs/AWS_2026-05-05/"

def run_sim():
    if not os.path.exists(DB_PATH):
        print("Database missing.")
        return

    # 1. Load trades chronologically
    conn = sqlite3.connect(DB_PATH)
    trades = pd.read_sql_query('SELECT id, ts_entry, entry_odds, stake_usdc FROM trades ORDER BY ts_entry ASC', conn)
    conn.close()

    # 2. Load all heartbeats from logs
    hb_data = {} # trade_id -> list of prices
    log_files = glob.glob(os.path.join(LOG_DIR, 'open_positions.log*'))
    
    print(f"Parsing {len(log_files)} log files...")
    for f in log_files:
        with open(f, 'r') as file:
            for line in file:
                if 'Trade #' in line and ('Current: ' in line or 'Internal: ' in line):
                    try:
                        # Extract Trade ID
                        tid_match = re.search(r'Trade #(\d+)', line)
                        if not tid_match: continue
                        tid = int(tid_match.group(1))
                        
                        # Extract Price
                        price_match = re.search(r'(?:Current|Internal): ([\d\.]+)', line)
                        if not price_match: continue
                        price = float(price_match.group(1))
                        
                        if tid not in hb_data: hb_data[tid] = []
                        hb_data[tid].append(price)
                    except:
                        continue

    starting_balance = 36.0
    balance = starting_balance
    min_balance = starting_balance
    ruin_trade_id = None
    ruin_count = 0

    print(f"Starting simulation on {len(trades)} trades...")
    
    for _, t in trades.iterrows():
        tid = t['id']
        if tid not in hb_data: continue
        
        prices = hb_data[tid]
        tp_price = t['entry_odds'] + 0.40
        sl_price = t['entry_odds'] - 0.05
        
        exit_price = None
        for p in prices:
            if p >= tp_price:
                exit_price = max(0.01, p - 0.03) # Forced slippage
                break
            if p <= sl_price:
                exit_price = max(0.01, p - 0.03) # Forced slippage
                break
                
        if exit_price is None:
            exit_price = prices[-1] # End of window
            
        pnl = t['stake_usdc'] * (exit_price / t['entry_odds']) - t['stake_usdc']
        balance += pnl
        
        if balance < min_balance:
            min_balance = balance
        if balance <= 0 and ruin_trade_id is None:
            ruin_trade_id = tid

    print('='*40)
    print('HEARTBEAT-BASED SURVIVAL SIM ($36 START)')
    print('='*40)
    print(f'Starting Balance: ${starting_balance:.2f}')
    print(f'Minimum Balance:  ${min_balance:.2f}')
    if ruin_trade_id:
        print(f'STATUS: ACCOUNT BLOWN at Trade ID: {ruin_trade_id}')
    else:
        print('STATUS: ACCOUNT SURVIVED')
    print(f'Final Balance:    ${balance:.2f}')
    print('='*40)

if __name__ == "__main__":
    run_sim()
