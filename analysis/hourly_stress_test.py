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
    end_time = trades['ts_entry'].max()
    total_hours = int((end_time - start_time).total_seconds() / 3600) + 1
    conn.close()

    # 2. Load peaks from heartbeats
    log_files = glob.glob(os.path.join(LOG_DIR, 'open_positions.log*'))
    hb_peaks = {}
    print(f"Parsing peaks from {len(log_files)} log files...")
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

    print('='*80)
    print('HOURLY STRESS TEST ($36 RESET EVERY HOUR | NO SL / 40c TP)')
    print('='*80)

    blown_hours = 0
    survived_hours = 0

    for i in range(total_hours):
        h_start = start_time + pd.Timedelta(hours=i)
        h_end = h_start + pd.Timedelta(hours=1)
        h_trades = trades[(trades['ts_entry'] >= h_start) & (trades['ts_entry'] < h_end)]
        
        if h_trades.empty:
            continue
            
        balance = 36.0
        min_balance = 36.0
        ruin = False
        
        for _, t in h_trades.iterrows():
            tid = t['id']
            peak = hb_peaks.get(tid, 0)
            tp_target = t['entry_odds'] + 0.40
            
            if peak >= tp_target:
                exit_price = max(0.01, tp_target - 0.03) # Forced slippage
            else:
                exit_price = max(0.01, peak - 0.03) # Forced slippage
                
            pnl = t['stake_usdc'] * (exit_price / t['entry_odds']) - t['stake_usdc']
            balance += pnl
            
            if balance < min_balance:
                min_balance = balance
            if balance <= 0 and not ruin:
                ruin = True
                
        if ruin:
            status = "❌ BLOWN"
            blown_hours += 1
        else:
            status = "✅ SURVIVED"
            survived_hours += 1
            
        print(f"HOUR {i+1:>2} ({h_start.strftime('%H:%M')}): Trades: {len(h_trades):>3} | Min Bal: ${min_balance:>7.2f} | End Bal: ${balance:>7.2f} | Status: {status}")

    print('='*80)
    print(f"Total Hours Actively Traded: {blown_hours + survived_hours}")
    print(f"Hours Survived:              {survived_hours}")
    print(f"Hours Blown:                 {blown_hours}")
    print('='*80)

if __name__ == "__main__":
    run_sim()
