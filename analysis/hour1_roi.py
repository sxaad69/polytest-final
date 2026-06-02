import sqlite3
import pandas as pd
import os
import glob
import re
import warnings
warnings.filterwarnings('ignore')

DB_PATH = "data/aws/bot_sniper_paper_2026-05-05.db"
LOG_DIR = "logs/AWS_2026-05-05/"

def run_roi():
    if not os.path.exists(DB_PATH):
        print("Database missing.")
        return

    conn = sqlite3.connect(DB_PATH)
    trades = pd.read_sql_query('SELECT id, ts_entry, entry_odds, stake_usdc FROM trades ORDER BY ts_entry ASC', conn)
    start_time = pd.to_datetime(trades['ts_entry'].min())
    h_end = start_time + pd.Timedelta(hours=1)
    trades['ts_entry'] = pd.to_datetime(trades['ts_entry'])
    hour_1_trades = trades[(trades['ts_entry'] >= start_time) & (trades['ts_entry'] < h_end)]
    conn.close()

    log_files = glob.glob(os.path.join(LOG_DIR, 'open_positions.log*'))
    balance = 36.0
    start_balance = 36.0

    print(f"Analyzing {len(hour_1_trades)} trades in Hour 1...")

    for _, t in hour_1_trades.iterrows():
        tid = t['id']
        peak_in_cycle = 0
        
        # Check heartbeats for peak
        for f in log_files:
            with open(f, 'r') as file:
                content = file.read()
                if f'Trade #{tid}' in content:
                    # Found the trade, find max price
                    prices = re.findall(rf'Trade #{tid}.*?(?:Current|Internal): ([\d\.]+)', content)
                    if prices:
                        peak_in_cycle = max([float(p) for p in prices])
        
        if peak_in_cycle >= 0.90:
            # Settle at 0.99 (Full Win)
            pnl = t['stake_usdc'] * (0.99 / t['entry_odds']) - t['stake_usdc']
        else:
            pnl = t['stake_usdc'] * (peak_in_cycle / t['entry_odds']) - t['stake_usdc']
            
        balance += pnl

    print('='*40)
    print('HOUR 1 ROI ANALYSIS ($36 START)')
    print('='*40)
    print(f'Starting Balance: ${start_balance:.2f}')
    print(f'Final Balance:    ${balance:.2f}')
    print(f'Total Profit:     ${(balance - start_balance):.2f}')
    print(f'Hour 1 ROI:       {((balance - start_balance) / start_balance * 100):.2f}%')
    print('='*40)

if __name__ == "__main__":
    run_roi()
