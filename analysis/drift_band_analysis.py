import pandas as pd
import numpy as np
import sys

def run_drift_band_analysis(csv_path):
    df = pd.read_csv(csv_path)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    # Extract START time from slug (e.g., ...-1777746900)
    df['window_start_ts'] = df['market_slug'].str.extract(r'(\d+)$').astype(float)
    df['window_start_dt'] = pd.to_datetime(df['window_start_ts'], unit='s')
    
    # Window ends 5 minutes (300 seconds) after the slug timestamp
    df['window_end_dt'] = df['window_start_dt'] + pd.Timedelta(minutes=5)
    
    # Calculate time remaining in the window
    df['seconds_remaining'] = (df['window_end_dt'] - df['timestamp']).dt.total_seconds()
    
    # Filter for the drift zone (90 to 120 seconds before expiry)
    # The user asked for: 90-95, 96-100, 100-120
    drift_zone = df[(df['seconds_remaining'] >= 90) & (df['seconds_remaining'] <= 120)].copy()
    
    def get_time_band(s):
        if 90 <= s <= 95:   return "90-95s"
        if 95 < s <= 100:  return "96-100s"
        if 100 < s <= 120: return "101-120s"
        return None

    drift_zone['time_band'] = drift_zone['seconds_remaining'].apply(get_time_band)
    
    # Define Price Bands (0.40 to 1.00 in 0.05 steps)
    price_bins = [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 1.01]
    price_labels = ["0.40-0.45", "0.45-0.50", "0.50-0.55", "0.55-0.60", "0.60-0.65", "0.65-0.70", "0.70-0.75", "0.75-0.80", "0.80-0.85", "0.85-0.90", "0.90-0.95", "0.95-1.00"]
    drift_zone['price_band'] = pd.cut(drift_zone['poly_mid'], bins=price_bins, labels=price_labels)
    
    # Outcomes: Get the last price for each market in the ENTIRE tape
    last_prices = df.groupby('market_slug')['poly_mid'].last().rename('final_price')
    outcomes_binary = (last_prices > 0.5).astype(int)
    
    drift_zone = drift_zone.join(outcomes_binary, on='market_slug')
    
    # Win if the final resolution is YES (1.0)
    drift_zone['is_win'] = (drift_zone['final_price'] == 1)
    
    # Group and Aggregate
    matrix = drift_zone.groupby(['time_band', 'price_band'], observed=False).agg(
        win_rate=('is_win', 'mean'),
        total_samples=('is_win', 'count')
    ).unstack(level=1)
    
    # Order the time bands correctly
    time_order = ["101-120s", "96-100s", "90-95s"]
    matrix = matrix.reindex(time_order)
    
    print("\n" + "="*120)
    print("PRE-RESOLUTION DRIFT BAND MATRIX (WIN RATE %)")
    print("="*120)
    print(matrix['win_rate'].map(lambda x: f"{x*100:5.1f}%" if not pd.isna(x) else "  N/A "))
    
    print("\n" + "="*120)
    print("TOTAL SAMPLES (TICKS) PER REGION")
    print("="*120)
    print(matrix['total_samples'].map(lambda x: f"{int(x):5d}" if not pd.isna(x) else "    0 "))
    
if __name__ == "__main__":
    csv_path = sys.argv[1] if len(sys.argv) > 1 else '../logs/market_tape_2026-05-03.csv'
    run_drift_band_analysis(csv_path)
