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
    
    picker = df[(df['rem'] >= 240) & (df['rem'] <= 300) & (df['poly_mid'] >= 0.33) & (df['poly_mid'] <= 0.54)]
    entries = picker.sort_values('timestamp').groupby('market_slug').first()
    outcomes = df.groupby('market_slug')['poly_mid'].last()
    grouped = df.groupby('market_slug')
    
    inv = 3.00
    sl_dist = 0.05
    ttp_activation = 0.08
    ttp_trail = 0.03
    
    results = []
    
    for slug, entry in entries.iterrows():
        ep = entry['poly_mid']
        et = entry['timestamp']
        sh = inv/ep
        sl_p = ep - sl_dist
        
        m_data = grouped.get_group(slug)
        future = m_data[m_data['timestamp'] > et].sort_values('timestamp')
        
        pnl = 0
        met = False
        ttp_active = False
        peak_price = ep
        
        for _, t in future.iterrows():
            curr_p = t['poly_mid']
            
            # Check SL
            if not ttp_active and curr_p <= sl_p:
                pnl = (sh * sl_p) - inv
                met = True; break
                
            # Check TTP Activation
            if not ttp_active and curr_p >= (ep + ttp_activation):
                ttp_active = True
                peak_price = curr_p
            
            # Handle Trailing
            if ttp_active:
                if curr_p > peak_price:
                    peak_price = curr_p
                if curr_p <= (peak_price - ttp_trail):
                    pnl = (sh * curr_p) - inv
                    met = True; break
        
        if not met:
            final_val = outcomes.get(slug, 0.0)
            pnl = (sh * 1.0 - inv) if final_val > 0.5 else -inv
        results.append(pnl)

    print("\n" + "="*60)
    print("TRAILING TP STUDY: MINUTE 1 (0.33-0.54)")
    print(f"Activation: {ttp_activation} | Trail: {ttp_trail} | SL: {sl_dist}")
    print("="*60)
    print(f"TOTAL TRADES: {len(results)}")
    print(f"TOTAL PROFIT: ${sum(results):.2f}")
    print(f"ROI: {(sum(results)/(len(results)*inv))*100:.2f}%")
    print("="*60)

if __name__ == "__main__":
    csv_path = sys.argv[1] if len(sys.argv) > 1 else '../logs/market_tape_2026-05-03.csv'
    run_study(csv_path)
