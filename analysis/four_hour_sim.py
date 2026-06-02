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
    start_time = trades['ts_entry'].min()
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
                        tid = int(re.search(r'Trade #(\d+)', line).group(1))
                        price_match = re.search(r'(?:Current|Internal): ([\d\.]+)', line)
                        if price_match:
                            price = float(price_match.group(1))
                            if tid not in hb_peaks or price > hb_peaks[tid]:
                                hb_peaks[tid] = price
                    except: continue

    balance = 36.0
    start_balance = 36.0

    print('='*60)
    print('4-HOUR SEQUENTIAL BALANCE SIMULATION ($36 START)')
    print('='*60)

    for i in range(4):
        h_start = start_time + pd.Timedelta(hours=i)
        h_end = h_start + pd.Timedelta(hours=1)
        h_trades = trades[(trades['ts_entry'] >= h_start) & (trades['ts_entry'] < h_end)]
        
        if h_trades.empty:
            print(f"HOUR {i+1}: No trades found in this window.")
            continue
        
        h_start_bal = balance
        for _, t in h_trades.iterrows():
            tid = t['id']
            peak = hb_peaks.get(tid, 0)
            
            # Logic: Exit at Entry + 0.40 OR Final Window Peak (if < 0.40 gain)
            tp_target = t['entry_odds'] + 0.40
            
            if peak >= tp_target:
                # Sell at target (minus slippage)
                exit_price = max(0.01, tp_target - 0.03)
            else:
                # Sell at the best price available in the cycle (minus slippage)
                exit_price = max(0.01, peak - 0.03)
                
            pnl = t['stake_usdc'] * (exit_price / t['entry_odds']) - t['stake_usdc']
            balance += pnl
            
        print(f"HOUR {i+1} ({h_start.strftime('%H:%M')}): Start: ${h_start_bal:>7.2f} | End: ${balance:>7.2f} | PnL: ${balance-h_start_bal:>7.2f}")

    print('='*60)
    print(f"FINAL 4-HOUR BALANCE: ${balance:.2f}")
    print(f"TOTAL PROFIT:         ${balance - start_balance:.2f}")
    print(f"TOTAL 4-HOUR ROI:      {((balance - start_balance) / start_balance * 100):.2f}%")
    print('='*60)

if __name__ == "__main__":
    run_sim()
