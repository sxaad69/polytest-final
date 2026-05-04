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
    
    drift_zone = df[(df['rem'] >= 90) & (df['rem'] <= 120)].copy()
    
    # 5-second Time Bands
    time_bins = np.arange(90, 125, 5)
    time_labels = [f"{time_bins[i]}-{time_bins[i+1]}s" for i in range(len(time_bins)-1)]
    drift_zone['time_band'] = pd.cut(drift_zone['rem'], bins=time_bins, labels=time_labels)
    
    # 3-cent Price Bands
    price_bins = np.arange(0.15, 1.05, 0.03)
    price_labels = [f"{price_bins[i]:.2f}-{price_bins[i+1]:.2f}" for i in range(len(price_bins)-1)]
    drift_zone['price_band'] = pd.cut(drift_zone['poly_mid'], bins=price_bins, labels=price_labels)
    
    outcomes = df.groupby('market_slug')['poly_mid'].last().rename('final_price')
    
    # Process unique entries per (market, price_band, time_band)
    entries = drift_zone.sort_values('timestamp').groupby(['market_slug', 'price_band', 'time_band'], observed=False).first().dropna(subset=['poly_mid'])
    entries = entries.join(outcomes, on='market_slug')
    
    investment = 3.00
    def calc_profit(row):
        if row['final_price'] > 0.5:
            return (investment / row['poly_mid']) - investment
        else:
            return -investment

    entries['pnl'] = entries.apply(calc_profit, axis=1)
    
    # Create the Matrix: Rows=Price, Cols=Time
    # We want to see ROI
    matrix_pnl = entries.groupby(['price_band', 'time_band'], observed=False)['pnl'].sum().unstack()
    matrix_count = entries.groupby(['price_band', 'time_band'], observed=False)['pnl'].count().unstack()
    matrix_roi = (matrix_pnl / (matrix_count * investment)) * 100
    
    print("\n" + "="*120)
    print("HYPER-GRANULAR ROI HEATMAP (Price Band vs. Time Window)")
    print("="*120)
    
    # Focus on the active regions for readability
    report = matrix_roi.loc['0.45-0.48':'0.99-1.02']
    
    def color_roi(val):
        if pd.isna(val): return "  N/A  "
        return f"{val:6.1f}%"

    print(report.applymap(color_roi))
    print("\n" + "="*120)
    print("TRADE DENSITY (SAMPLES PER CELL)")
    print("="*120)
    print(matrix_count.loc['0.45-0.48':'0.99-1.02'].applymap(lambda x: f"{int(x):5d}" if not pd.isna(x) else "    0"))
    
if __name__ == "__main__":
    csv_path = sys.argv[1] if len(sys.argv) > 1 else '../logs/market_tape_2026-05-03.csv'
    run_simulation(csv_path)
