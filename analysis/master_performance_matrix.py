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
    
    picker_phase = df[(df['rem'] >= 240) & (df['rem'] <= 300)].copy()
    
    # Granular Price Bands
    price_bins = np.arange(0.15, 0.96, 0.09) # Slightly wider for cleaner table display
    price_labels = [f"{price_bins[i]:.2f}-{price_bins[i+1]:.2f}" for i in range(len(price_bins)-1)]
    picker_phase['price_band'] = pd.cut(picker_phase['poly_mid'], bins=price_bins, labels=price_labels)
    
    outcomes = df.groupby('market_slug')['poly_mid'].last().rename('final_price')
    grouped = df.groupby('market_slug')
    entries = picker_phase.sort_values('timestamp').groupby(['market_slug', 'price_band'], observed=False).first().dropna(subset=['poly_mid'])
    
    investment = 3.00
    sl_dist = 0.05
    tp_levels = [0.08, 0.16, 0.24, 0.32, 0.40]
    
    all_results = []
    
    for tp_dist in tp_levels:
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
                        outcome_met = True
                        break
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
            
            all_results.append({
                'TP': f"{int(tp_dist*100)}c",
                'Odds': price_band,
                'pnl': pnl
            })
            
    res_df = pd.DataFrame(all_results)
    final_report = res_df.groupby(['TP', 'Odds'], observed=False).agg(
        trades=('pnl', 'count'),
        net_profit=('pnl', 'sum'),
        roi=('pnl', lambda x: (x.sum() / (len(x) * investment)) * 100 if len(x) > 0 else 0)
    ).reset_index()
    
    print("\n" + "="*90)
    print("MASTER PERFORMANCE MATRIX: MINUTE 1 (0-1M)")
    print("="*90)
    # Pivot for clean display: TP as Columns, Odds as Rows
    pivot_roi = final_report.pivot(index='Odds', columns='TP', values='roi')
    print("ROI % BY ODDS AND TAKE PROFIT")
    print("-" * 90)
    print(pivot_roi.applymap(lambda x: f"{x:6.2f}%"))
    print("\n" + "-" * 90)
    pivot_pnl = final_report.pivot(index='Odds', columns='TP', values='net_profit')
    print("NET PROFIT ($) BY ODDS AND TAKE PROFIT")
    print("-" * 90)
    print(pivot_pnl.applymap(lambda x: f"${x:7.2f}"))
    print("="*90)

if __name__ == "__main__":
    csv_path = sys.argv[1] if len(sys.argv) > 1 else '../logs/market_tape_2026-05-03.csv'
    run_study(csv_path)
