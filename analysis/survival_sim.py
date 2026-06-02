import sqlite3
import pandas as pd
import os
import warnings
warnings.filterwarnings('ignore')

DB_PATH = "data/aws/bot_sniper_paper_2026-05-05.db"
TAPE_PATH = "logs/AWS_2026-05-05/market_tape_2026-05-05.csv"

def run_sim():
    if not os.path.exists(DB_PATH) or not os.path.exists(TAPE_PATH):
        print("Required files missing.")
        return

    conn = sqlite3.connect(DB_PATH)
    trades = pd.read_sql_query('SELECT id, ts_entry, slug, window_end, entry_odds, stake_usdc FROM trades ORDER BY ts_entry ASC', conn)
    tape = pd.read_csv(TAPE_PATH)
    tape['timestamp'] = pd.to_datetime(tape['timestamp'])

    starting_balance = 36.0
    balance = starting_balance
    min_balance = starting_balance
    ruin_trade_id = None
    ruin_timestamp = None

    results = []
    for _, t in trades.iterrows():
        window_end_dt = pd.to_datetime(t['window_end'])
        slug_tape = tape[tape['market_slug'] == t['slug']]
        if slug_tape.empty: continue
        
        slug_tape = slug_tape.sort_values('timestamp')
        idx = slug_tape['timestamp'].searchsorted(window_end_dt)
        if idx > 0:
            final_price = slug_tape.iloc[idx-1]['poly_mid']
            pnl = t['stake_usdc'] * (final_price / t['entry_odds']) - t['stake_usdc']
            balance += pnl
            
            if balance < min_balance:
                min_balance = balance
            
            if balance <= 0 and ruin_trade_id is None:
                ruin_trade_id = t['id']
                ruin_timestamp = t['ts_entry']
            
            results.append({'id': t['id'], 'balance': balance})

    print('='*40)
    print('ACCOUNT SURVIVAL SIMULATION ($36 START)')
    print('='*40)
    print(f'Starting Balance: ${starting_balance:.2f}')
    print(f'Minimum Balance:  ${min_balance:.2f}')
    
    if ruin_trade_id:
        print(f'STATUS: ACCOUNT BLOWN')
        print(f'Trade ID: {ruin_trade_id}')
        print(f'Timestamp: {ruin_timestamp}')
    else:
        print('STATUS: ACCOUNT SURVIVED')
        
    print(f'Final Balance:    ${balance:.2f}')
    print('='*40)
    
    conn.close()

if __name__ == "__main__":
    run_sim()
