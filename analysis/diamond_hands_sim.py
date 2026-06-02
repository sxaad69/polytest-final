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
    trades = pd.read_sql_query('SELECT id, asset, slug, window_end, entry_odds, stake_usdc FROM trades', conn)
    tape = pd.read_csv(TAPE_PATH)

    trades['window_end_dt'] = pd.to_datetime(trades['window_end'])
    tape['timestamp'] = pd.to_datetime(tape['timestamp'])

    results = []
    for _, t in trades.iterrows():
        # Find the price for this slug at the EXACT window end (or closest before)
        slug_tape = tape[tape['market_slug'] == t['slug']]
        if slug_tape.empty: continue
        
        slug_tape = slug_tape.sort_values('timestamp')
        idx = slug_tape['timestamp'].searchsorted(t['window_end_dt'])
        if idx > 0:
            final_price = slug_tape.iloc[idx-1]['poly_mid']
            # Theoretical PnL: Hold until end
            # In Polymarket, 5m binary markets settle at 0.999 or 0.001
            # If final_price > 0.50, it's a win (1.0), if < 0.50, it's a loss (0.0)
            # But let's use the actual tape price for accuracy
            theoretical_pnl = t['stake_usdc'] * (final_price / t['entry_odds']) - t['stake_usdc']
            results.append({
                'id': t['id'], 
                'asset': t['asset'], 
                'entry': t['entry_odds'],
                'final': final_price, 
                'pnl': theoretical_pnl
            })

    df = pd.DataFrame(results)
    print('='*40)
    print('SIMULATION: HOLD UNTIL WINDOW END')
    print('='*40)
    print(f'Total Trades Modeled: {len(df)}')
    print(f'Total Sim PnL:        ${df["pnl"].sum():.2f}')
    print(f'Win Rate (>0 PnL):    {(df["pnl"] > 0).mean()*100:.2f}%')
    print(f'Avg PnL per Trade:    ${df["pnl"].mean():.3f}')
    
    print("\nBiggest Theoretical Winners (Hold to End):")
    print(df.sort_values('pnl', ascending=False).head(10))
    
    conn.close()

if __name__ == "__main__":
    run_sim()
