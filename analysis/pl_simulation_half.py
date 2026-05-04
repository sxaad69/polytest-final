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
    
    # Target: 0.80 to 0.90 price, 90 to 110s remaining
    entries = df[
        (df['poly_mid'] >= 0.80) & 
        (df['poly_mid'] <= 0.90) & 
        (df['rem'] >= 90) & 
        (df['rem'] <= 110)
    ].sort_values('timestamp').groupby('market_slug').first()
    
    grouped = df.groupby('market_slug')
    investment = 3.00
    
    results = []
    
    for slug, entry in entries.iterrows():
        entry_price = entry['poly_mid']
        entry_time = entry['timestamp']
        sl_price = entry_price / 2.0 # Exit when value drops by 50%
        shares = investment / entry_price
        
        market_data = grouped.get_group(slug)
        future_ticks = market_data[market_data['timestamp'] > entry_time].sort_values('timestamp')
        
        if len(future_ticks) == 0: continue
            
        pnl = 0
        outcome = ""
        
        # Check for SL hit (50% drop)
        hit_sl = False
        for _, tick in future_ticks.iterrows():
            if tick['poly_mid'] <= sl_price:
                hit_sl = True
                break
        
        if hit_sl:
            pnl = -1.50 # Lose half the stack
            outcome = "HALF_LOSS_SL"
        else:
            final_price = future_ticks.iloc[-1]['poly_mid']
            if final_price > 0.5:
                pnl = (shares * 1.0) - investment
                outcome = "WIN"
            else:
                pnl = -investment # Total wipeout if it didn't hit SL but closed NO
                outcome = "TOTAL_LOSS"
        
        results.append({'slug': slug, 'pnl': pnl, 'outcome': outcome})
        
    res_df = pd.DataFrame(results)
    total_pnl = res_df['pnl'].sum()
    
    print("\n" + "="*50)
    print(f"P&L SIMULATION: 50% ($1.50) STOP LOSS")
    print("="*50)
    print(res_df['outcome'].value_counts())
    print("-" * 50)
    print(f"Total Net Profit: ${total_pnl:.2f} 💸")
    print(f"Win Rate: {(len(res_df[res_df['outcome']=='WIN'])/len(res_df))*100:.2f}%")
    print(f"Avg P&L per Trade: ${res_df['pnl'].mean():.4f}")
    print("="*50)

if __name__ == "__main__":
    csv_path = sys.argv[1] if len(sys.argv) > 1 else '../logs/market_tape_2026-05-03.csv'
    run_simulation(csv_path)
