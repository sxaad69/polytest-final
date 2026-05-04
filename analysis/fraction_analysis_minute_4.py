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
    
    # FRACTION 4: 3-4M (Consolidate) 
    consolidate_phase = df[(df['rem'] >= 60) & (df['rem'] <= 120)].copy()
    
    price_bins = np.arange(0.30, 1.03, 0.03)
    price_labels = [f"{price_bins[i]:.2f}-{price_bins[i+1]:.2f}" for i in range(len(price_bins)-1)]
    consolidate_phase['price_band'] = pd.cut(consolidate_phase['poly_mid'], bins=price_bins, labels=price_labels)
    
    outcomes = df.groupby('market_slug')['poly_mid'].last().rename('final_price')
    grouped = df.groupby('market_slug')
    entries = consolidate_phase.sort_values('timestamp').groupby(['market_slug', 'price_band'], observed=False).first().dropna(subset=['poly_mid'])
    
    investment = 3.00
    sl_dist = 0.05
    tp_levels = [0.08, 0.12, 0.16, 0.20, 0.24, 0.32] # Testing tighter TPs for this phase
    
    all_results = []
    
    for tp_dist in tp_levels:
        tp_label = f"{int(tp_dist*100)}c"
        for (slug, price_band), entry in entries.iterrows():
            entry_price = entry['poly_mid']
            entry_time = entry['timestamp']
            sl_price = entry_price - sl_dist
            tp_price = entry_price + tp_dist
            shares = investment / entry_price
            
            market_data = grouped.get_group(slug)
            future_ticks = market_data[market_data['timestamp'] > entry_time].sort_values('timestamp')
            
            pnl = 0
            outcome_met = False
            if len(future_ticks) > 0:
                for _, tick in future_ticks.iterrows():
                    if tick['poly_mid'] <= sl_price:
                        pnl = (shares * sl_price) - investment
                        outcome_met = True; break
                    if tick['poly_mid'] >= tp_price:
                        pnl = (shares * tp_price) - investment
                        outcome_met = True; break
            
            if not outcome_met:
                final_val = outcomes.get(slug, 0.0)
                pnl = (shares * 1.0 - investment) if final_val > 0.5 else -investment
            
            all_results.append({'TP': tp_label, 'Odds': price_band, 'pnl': pnl})
            
    res_df = pd.DataFrame(all_results)
    final_report = res_df.groupby(['TP', 'Odds'], observed=False)['pnl'].apply(lambda x: (x.sum() / (len(x) * investment)) * 100 if len(x) > 0 else 0).unstack()
    
    print("\n" + "="*120)
    print("MASTER ROI MATRIX: MINUTE 3-4 (CONSOLIDATE)")
    print("="*120)
    print(final_report.applymap(lambda x: f"{x:5.1f}%" if x != 0 else "  0%  "))
    print("="*120)

if __name__ == "__main__":
    csv_path = sys.argv[1] if len(sys.argv) > 1 else '../logs/market_tape_2026-05-03.csv'
    run_study(csv_path)
