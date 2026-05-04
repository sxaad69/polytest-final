import pandas as pd
import numpy as np
import sys

def run_simulation(csv_path):
    df = pd.read_csv(csv_path)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['window_start_ts'] = df['market_slug'].str.extract(r'(\d+)$').astype(float)
    df['window_start_dt'] = pd.to_datetime(df['window_start_ts'], unit='s')
    df['window_end_dt'] = df['window_start_dt'] + pd.Timedelta(minutes=5)
    df['rem'] = (df['window_end_dt'] - df['timestamp']).dt.total_seconds()
    
    # Target: 0.70 to 0.85 price, 90 to 120s remaining (wider window for more trades)
    entries = df[
        (df['poly_mid'] >= 0.70) & 
        (df['poly_mid'] <= 0.85) & 
        (df['rem'] >= 90) & 
        (df['rem'] <= 120)
    ].sort_values('timestamp').groupby('market_slug').first()
    
    outcomes = df.groupby('market_slug')['poly_mid'].last()
    entries = entries.join(outcomes.rename('final_price'), on='market_slug')
    
    investment = 3.00
    
    def calc_profit(row):
        if row['final_price'] > 0.5:
            return (investment / row['poly_mid']) - investment
        else:
            return -investment

    entries['pnl'] = entries.apply(calc_profit, axis=1)
    total_trades = len(entries)
    total_pnl = entries['pnl'].sum()
    
    print("\n" + "="*50)
    print(f"P&L SIMULATION: THE 0.70-0.85 ZONE")
    print("="*50)
    print(f"Total Trades       : {total_trades}")
    print(f"Win Rate           : {(len(entries[entries['pnl'] > 0])/total_trades)*100:.2f}%")
    print("-" * 50)
    print(f"Total Net Profit   : ${total_pnl:.2f} 🚀")
    print(f"Avg Profit/Trade   : ${entries['pnl'].mean():.2f}")
    print("="*50)

if __name__ == "__main__":
    csv_path = sys.argv[1] if len(sys.argv) > 1 else '../logs/market_tape_2026-05-03.csv'
    run_simulation(csv_path)
