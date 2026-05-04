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
    
    # Filter for Minute 1 (240-300s remaining)
    picker_phase = df[(df['rem'] >= 240) & (df['rem'] <= 300)].copy()
    
    # 3-cent Price Bands
    price_bins = np.arange(0.15, 0.96, 0.03) # Focusing on the active range
    price_labels = [f"{price_bins[i]:.2f}-{price_bins[i+1]:.2f}" for i in range(len(price_bins)-1)]
    picker_phase['price_band'] = pd.cut(picker_phase['poly_mid'], bins=price_bins, labels=price_labels)
    
    outcomes = df.groupby('market_slug')['poly_mid'].last().rename('final_price')
    grouped = df.groupby('market_slug')
    
    # Unique entries
    entries = picker_phase.sort_values('timestamp').groupby(['market_slug', 'price_band'], observed=False).first().dropna(subset=['poly_mid'])
    
    investment = 3.00
    sl_dist = 0.05
    tp_levels = [0.04, 0.08, 0.12, 0.16, 0.20, 0.30, 0.40, 0.50]
    
    results = []
    
    for tp_dist in tp_levels:
        total_pnl = 0
        for (slug, price_band), entry in entries.iterrows():
            entry_price = entry['poly_mid']
            entry_time = entry['timestamp']
            sl_price = entry_price - sl_dist
            tp_price = entry_price + tp_dist
            shares = investment / entry_price
            
            market_data = grouped.get_group(slug)
            future_ticks = market_data[market_data['timestamp'] > entry_time].sort_values('timestamp')
            
            if len(future_ticks) == 0: continue
            
            pnl = 0
            outcome_met = False
            for _, tick in future_ticks.iterrows():
                # Check SL
                if tick['poly_mid'] <= sl_price:
                    pnl = (shares * sl_price) - investment
                    outcome_met = True
                    break
                # Check TP
                if tick['poly_mid'] >= tp_price:
                    pnl = (shares * tp_price) - investment
                    outcome_met = True
                    break
            
            if not outcome_met:
                final_val = outcomes.get(slug, 0.0)
                if final_val > 0.5:
                    pnl = (shares * 1.0) - investment
                else:
                    pnl = -investment
            
            total_pnl += pnl
            
        roi = (total_pnl / (len(entries) * investment)) * 100
        results.append({'TP_Cents': f"{int(tp_dist*100)}c", 'ROI': f"{roi:.2f}%", 'Net_USD': f"${total_pnl:.2f}"})
        
    print("\n" + "="*60)
    print("MINUTE 1 OPTIMIZATION: SL -5c | TP VARIABLE")
    print("="*60)
    res_df = pd.DataFrame(results)
    print(res_df.to_string(index=False))
    print("="*60)

if __name__ == "__main__":
    csv_path = sys.argv[1] if len(sys.argv) > 1 else '../logs/market_tape_2026-05-03.csv'
    run_study(csv_path)
