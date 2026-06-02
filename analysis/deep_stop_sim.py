import sqlite3
import pandas as pd
import warnings
import os
warnings.filterwarnings('ignore')

DB_PATH = "data/aws/bot_sniper_paper_2026-05-05.db"
TAPE_PATH = "logs/AWS_2026-05-05/market_tape_2026-05-05.csv"

def run_sim():
    if not os.path.exists(DB_PATH) or not os.path.exists(TAPE_PATH):
        print("Required files missing.")
        return

    conn = sqlite3.connect(DB_PATH)
    trades = pd.read_sql_query('SELECT id, asset, slug, window_start, window_end, entry_odds, stake_usdc FROM trades', conn)
    tape = pd.read_csv(TAPE_PATH)

    trades['start_dt'] = pd.to_datetime(trades['window_start'])
    trades['end_dt'] = pd.to_datetime(trades['window_end'])
    tape['timestamp'] = pd.to_datetime(tape['timestamp'])

    def simulate_sl(sl_pct):
        total_pnl = 0
        trade_count = 0
        wins = 0
        for _, t in trades.iterrows():
            # SL target price: e.g. 0.50 * (1 - 0.50) = 0.25
            sl_price = t['entry_odds'] * (1 - sl_pct)
            
            # Get all ticks for this trade
            slug_tape = tape[(tape['market_slug'] == t['slug']) & (tape['timestamp'] >= t['start_dt']) & (tape['timestamp'] <= t['end_dt'])]
            if slug_tape.empty: continue
            
            trade_count += 1
            slug_tape = slug_tape.sort_values('timestamp')
            
            # Did it ever hit SL?
            hit_sl = False
            exit_price = 0
            for _, tick in slug_tape.iterrows():
                if tick['poly_mid'] <= sl_price:
                    hit_sl = True
                    exit_price = max(0.01, tick['poly_mid'] - 0.03) # Paper slippage
                    break
            
            if hit_sl:
                pnl = t['stake_usdc'] * (exit_price / t['entry_odds']) - t['stake_usdc']
            else:
                final_price = slug_tape.iloc[-1]['poly_mid']
                pnl = t['stake_usdc'] * (final_price / t['entry_odds']) - t['stake_usdc']
                if pnl > 0: wins += 1
                
            total_pnl += pnl
        return total_pnl, (wins / trade_count * 100 if trade_count > 0 else 0)

    pnl_50, win_50 = simulate_sl(0.50)
    pnl_75, win_75 = simulate_sl(0.75)

    print('='*40)
    print('DEEP STOP LOSS SIMULATION')
    print('='*40)
    print(f'Scenario: 50% SL (Value Drops 50%)')
    print(f'Total Sim PnL:  ${pnl_50:.2f}')
    print(f'Win Rate:       {win_50:.2f}%')
    print('-'*40)
    print(f'Scenario: 75% SL (Value Drops 75%)')
    print(f'Total Sim PnL:  ${pnl_75:.2f}')
    print(f'Win Rate:       {win_75:.2f}%')
    print('='*40)
    
    conn.close()

if __name__ == "__main__":
    run_sim()
