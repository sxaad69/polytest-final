import pandas as pd
import numpy as np
import sys

def run_study(csv_path):
    df = pd.read_csv(csv_path)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['window_start_ts'] = df['market_slug'].str.extract(r'(\d+)$').astype(float)
    df['window_start_dt'] = pd.to_datetime(df['window_start_ts'], unit='s')
    df['window_end_dt'] = df['window_start_dt'] + pd.Timedelta(minutes=5)
    df['rem'] = (df['window_end_dt'] - df['timestamp']).dt.total_seconds()
    
    # Target: 0.60-0.75 price AND Binance Momentum > 0
    entries = df[
        (df['poly_mid'] >= 0.60) & 
        (df['poly_mid'] <= 0.75) & 
        (df['rem'] >= 90) & 
        (df['rem'] <= 120) &
        (df['binance_mom'] > 0.01) # Sniper Binance Filter
    ].sort_values('timestamp').groupby('market_slug').first()
    
    grouped = df.groupby('market_slug')
    investment = 3.00
    
    sl_levels = [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.00]
    study_results = []
    
    for sl_pct in sl_levels:
        total_pnl = 0
        wins = 0
        losses = 0
        
        for slug, entry in entries.iterrows():
            entry_price = entry['poly_mid']
            entry_time = entry['timestamp']
            sl_price = entry_price * (1 - sl_pct)
            shares = investment / entry_price
            
            market_data = grouped.get_group(slug)
            future_ticks = market_data[market_data['timestamp'] > entry_time].sort_values('timestamp')
            
            if len(future_ticks) == 0: continue
                
            pnl = 0
            hit_sl = False
            for _, tick in future_ticks.iterrows():
                if tick['poly_mid'] <= sl_price:
                    hit_sl = True
                    break
            
            if hit_sl:
                pnl = (shares * sl_price) - investment
                losses += 1
            else:
                final_price = future_ticks.iloc[-1]['poly_mid']
                if final_price > 0.5:
                    pnl = (shares * 1.0) - investment
                    wins += 1
                else:
                    pnl = -investment
                    losses += 1
            
            total_pnl += pnl
            
        roi = (total_pnl / (len(entries) * investment)) * 100 if len(entries) > 0 else 0
        study_results.append({
            'SL_Pct': f"-{int(sl_pct*100)}%",
            'ROI': f"{roi:.2f}%",
            'Wins': wins,
            'Losses': losses,
            'Net_USD': f"${total_pnl:.2f}"
        })
        
    print("\n" + "="*70)
    print("BINANCE-FILTERED ROI CORRELATION (0.60-0.75 Zone)")
    print("="*70)
    res_df = pd.DataFrame(study_results)
    print(res_df.to_string(index=False))
    print("="*70)

if __name__ == "__main__":
    csv_path = sys.argv[1] if len(sys.argv) > 1 else '../logs/market_tape_2026-05-03.csv'
    run_study(csv_path)
