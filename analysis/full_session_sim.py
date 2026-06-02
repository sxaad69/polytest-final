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

    # 1. Load trades
    conn = sqlite3.connect(DB_PATH)
    trades = pd.read_sql_query('SELECT id, ts_entry, entry_odds, stake_usdc FROM trades ORDER BY ts_entry ASC', conn)
    trades['ts_entry'] = pd.to_datetime(trades['ts_entry'])
    conn.close()

    # 2. Load peaks from heartbeats
    log_files = glob.glob(os.path.join(LOG_DIR, 'open_positions.log*'))
    hb_peaks = {}
    print(f"Parsing peaks from {len(log_files)} files...")
    for f in log_files:
        with open(f, 'r') as file:
            for line in file:
                if 'Trade #' in line and ('HEARTBEAT' in line or 'POST-EXIT HB' in line):
                    try:
                        tid_match = re.search(r'Trade #(\d+)', line)
                        if not tid_match: continue
                        tid = int(tid_match.group(1))
                        
                        price_match = re.search(r'(?:Current|Internal): ([\d\.]+)', line)
                        if not price_match: continue
                        price = float(price_match.group(1))
                        
                        if tid not in hb_peaks or price > hb_peaks[tid]:
                            hb_peaks[tid] = price
                    except: continue

    balance = 36.0
    start_balance = 36.0
    min_balance = 36.0
    ruin_trade_id = None

    print(f"Starting full simulation on {len(trades)} trades...")
    
    for _, t in trades.iterrows():
        tid = t['id']
        peak = hb_peaks.get(tid, 0)
        tp_target = t['entry_odds'] + 0.40
        
        if peak >= tp_target:
            exit_price = max(0.01, tp_target - 0.03)
        else:
            exit_price = max(0.01, peak - 0.03)
            
        pnl = t['stake_usdc'] * (exit_price / t['entry_odds']) - t['stake_usdc']
        balance += pnl
        
        if balance < min_balance:
            min_balance = balance
        if balance <= 0 and ruin_trade_id is None:
            ruin_trade_id = tid

    print('='*40)
    print('FULL SESSION SIMULATION ($36 START)')
    print('='*40)
    print(f'Total Trades:     {len(trades)}')
    print(f'Starting Balance: ${start_balance:.2f}')
    print(f'Minimum Balance:  ${min_balance:.2f}')
    
    if ruin_trade_id:
        print(f'STATUS: ACCOUNT BLOWN at Trade ID: {ruin_trade_id}')
    else:
        print('STATUS: ACCOUNT SURVIVED')
        
    print(f'Final Balance:    ${balance:.2f}')
    print(f'Total Profit:     ${balance - start_balance:.2f}')
    print(f'Total ROI:        {((balance - start_balance) / start_balance * 100):.2f}%')
    print('='*40)

if __name__ == "__main__":
    run_sim()
