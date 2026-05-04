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
    
    # Sniper Entries
    entries = df[
        (df['poly_mid'] >= 0.60) & 
        (df['poly_mid'] <= 0.75) & 
        (df['rem'] >= 90) & 
        (df['rem'] <= 120) &
        (df['binance_mom'] > 0.01)
    ].sort_values('timestamp').groupby('market_slug').first()
    
    grouped = df.groupby('market_slug')
    investment = 3.00
    
    results = []
    
    for slug, entry in entries.iterrows():
        entry_price = entry['poly_mid']
        entry_time = entry['timestamp']
        shares = investment / entry_price
        
        market_data = grouped.get_group(slug)
        future_ticks = market_data[market_data['timestamp'] > entry_time].sort_values('timestamp')
        
        if len(future_ticks) == 0: continue
            
        # Strategy: Exit at 15s remaining
        exit_tick = future_ticks[future_ticks['rem'] <= 15].sort_values('rem', ascending=False)
        
        if len(exit_tick) > 0:
            exit_price = exit_tick.iloc[0]['poly_mid']
        else:
            # Fallback to final resolution if no tick at 15s
            exit_price = future_ticks.iloc[-1]['poly_mid']
            
        pnl = (shares * exit_price) - investment
        results.append({'slug': slug, 'pnl': pnl})
        
    res_df = pd.DataFrame(results)
    total_pnl = res_df['pnl'].sum()
    roi = (total_pnl / (len(entries) * investment)) * 100
    
    print("\n" + "="*50)
    print(f"SNIPER SIMULATION: 15s EARLY EXIT")
    print("="*50)
    print(f"Total Trades       : {len(entries)}")
    print(f"Total Net Profit   : ${total_pnl:.2f} 💰")
    print(f"ROI                : {roi:.2f}%")
    print(f"Avg Profit/Trade   : ${res_df['pnl'].mean():.4f}")
    print("="*50)

if __name__ == "__main__":
    csv_path = sys.argv[1] if len(sys.argv) > 1 else '../logs/market_tape_2026-05-03.csv'
    run_simulation(csv_path)
