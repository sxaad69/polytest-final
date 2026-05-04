import pandas as pd
import numpy as np
import sys

def run_simulation(csv_path):
    df = pd.read_csv(csv_path)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    # Extract START time and calculate Window End
    df['window_start_ts'] = df['market_slug'].str.extract(r'(\d+)$').astype(float)
    df['window_start_dt'] = pd.to_datetime(df['window_start_ts'], unit='s')
    df['window_end_dt'] = df['window_start_dt'] + pd.Timedelta(minutes=5)
    df['rem'] = (df['window_end_dt'] - df['timestamp']).dt.total_seconds()
    
    # Filter for Target Group (0.85-0.95 at 90-95s)
    # Use .first() to pick only one entry per market slug
    entries = df[
        (df['poly_mid'] >= 0.85) & 
        (df['poly_mid'] <= 0.95) & 
        (df['rem'] >= 90) & 
        (df['rem'] <= 95)
    ].sort_values('timestamp').groupby('market_slug').first()
    
    # Get Final Outcome for each market
    outcomes = df.groupby('market_slug')['poly_mid'].last()
    entries = entries.join(outcomes.rename('final_price'), on='market_slug')
    
    # Simulation Parameters
    investment_per_trade = 3.00
    
    def calc_profit(row):
        entry_price = row['poly_mid']
        # shares = investment / entry_price
        # if Win (final_price > 0.5): result = shares * 1.0 - investment
        # if Loss (final_price <= 0.5): result = -investment
        if row['final_price'] > 0.5:
            return (investment_per_trade / entry_price) - investment_per_trade
        else:
            return -investment_per_trade

    entries['pnl'] = entries.apply(calc_profit, axis=1)
    
    total_trades = len(entries)
    total_invested = total_trades * investment_per_trade
    total_pnl = entries['pnl'].sum()
    roi = (total_pnl / total_invested) * 100 if total_invested > 0 else 0
    
    print("\n" + "="*50)
    print(f"P&L SIMULATION ($3.00 FIXED ENTRY)")
    print(f"Group: 0.85-0.95 Price | 90-95s Remaining")
    print("="*50)
    print(f"Total Trades       : {total_trades}")
    print(f"Wins               : {len(entries[entries['pnl'] > 0])}")
    print(f"Losses             : {len(entries[entries['pnl'] < 0])}")
    print(f"Win Rate           : {(len(entries[entries['pnl'] > 0])/total_trades)*100:.2f}%")
    print("-" * 50)
    print(f"Total Invested     : ${total_invested:.2f}")
    print(f"Total Net Profit   : ${total_pnl:.2f} 🔥")
    print(f"ROI                : {roi:.2f}%")
    print(f"Avg Profit/Trade   : ${entries['pnl'].mean():.2f}")
    print("="*50)

if __name__ == "__main__":
    csv_path = sys.argv[1] if len(sys.argv) > 1 else '../logs/market_tape_2026-05-03.csv'
    run_simulation(csv_path)
