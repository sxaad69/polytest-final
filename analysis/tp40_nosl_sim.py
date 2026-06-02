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
    trades = pd.read_sql_query('SELECT id, ts_entry, slug, window_start, window_end, entry_odds, stake_usdc FROM trades ORDER BY ts_entry ASC', conn)
    tape = pd.read_csv(TAPE_PATH)
    tape['timestamp'] = pd.to_datetime(tape['timestamp'])

    starting_balance = 36.0
    balance = starting_balance
    min_balance = starting_balance
    ruin_trade_id = None

    for _, t in trades.iterrows():
        tp_price = t['entry_odds'] + 0.40
        
        start_dt = pd.to_datetime(t['window_start'])
        end_dt = pd.to_datetime(t['window_end'])
        slug_tape = tape[(tape['market_slug'] == t['slug']) & (tape['timestamp'] >= start_dt) & (tape['timestamp'] <= end_dt)]
        if slug_tape.empty: continue
        
        slug_tape = slug_tape.sort_values('timestamp')
        
        exit_price = None
        for _, tick in slug_tape.iterrows():
            if tick['poly_mid'] >= tp_price:
                exit_price = max(0.01, tick['poly_mid'] - 0.03) # Forced slippage
                break
                
        if exit_price is None:
            exit_price = slug_tape.iloc[-1]['poly_mid']
            
        pnl = t['stake_usdc'] * (exit_price / t['entry_odds']) - t['stake_usdc']
        balance += pnl
        
        if balance < min_balance:
            min_balance = balance
        if balance <= 0 and ruin_trade_id is None:
            ruin_trade_id = t['id']

    print('='*40)
    print('FIXED TP (40c) / NO SL SURVIVAL SIM')
    print('='*40)
    print(f'Starting Balance: ${starting_balance:.2f}')
    print(f'Minimum Balance:  ${min_balance:.2f}')
    if ruin_trade_id:
        print(f'STATUS: ACCOUNT BLOWN at Trade ID: {ruin_trade_id}')
    else:
        print('STATUS: ACCOUNT SURVIVED')
    print(f'Final Balance:    ${balance:.2f}')
    print('='*40)
    
    conn.close()

if __name__ == "__main__":
    run_sim()
