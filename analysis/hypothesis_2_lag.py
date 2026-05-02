import pandas as pd
import numpy as np

def run_hypothesis_2(csv_path):
    print("--- Hypothesis 2: Binance Lead-Time Lag ---")
    try:
        df = pd.read_csv(csv_path)
    except FileNotFoundError:
        print(f"Error: Could not find {csv_path}")
        return

    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    lags = []
    
    for slug, group in df.groupby('market_slug'):
        group = group.sort_values('timestamp').reset_index(drop=True)
        if len(group) < 10:
            continue
            
        # Detect significant Binance momentum shifts (e.g., > 0.02 change)
        group['mom_diff'] = group['binance_mom'].diff()
        
        # Find rows where momentum changed significantly
        sig_mom_shifts = group[group['mom_diff'].abs() > 0.02]
        
        for idx, shift_row in sig_mom_shifts.iterrows():
            shift_time = shift_row['timestamp']
            shift_dir = 1 if shift_row['mom_diff'] > 0 else -1
            current_poly_mid = shift_row['poly_mid']
            
            # Look ahead to see when poly_mid moves in the same direction
            lookahead = group.loc[idx+1:]
            
            for _, future_row in lookahead.iterrows():
                poly_diff = future_row['poly_mid'] - current_poly_mid
                future_time = future_row['timestamp']
                
                # If poly_mid moved in the same direction
                if (shift_dir == 1 and poly_diff > 0.005) or (shift_dir == -1 and poly_diff < -0.005):
                    lag_seconds = (future_time - shift_time).total_seconds()
                    # Only consider it a valid reaction if it happens within 60 seconds
                    if lag_seconds <= 60:
                        lags.append({
                            'slug': slug,
                            'shift_time': shift_time,
                            'lag_seconds': lag_seconds,
                            'mom_diff': shift_row['mom_diff'],
                            'poly_diff': poly_diff
                        })
                    break # Stop looking after the first reaction

    if not lags:
        print("No significant lag correlations found in this sample.")
        return
        
    lag_df = pd.DataFrame(lags)
    avg_lag = lag_df['lag_seconds'].mean()
    median_lag = lag_df['lag_seconds'].median()
    print(f"Total Valid Lag Events Detected: {len(lag_df)}")
    print(f"Average Lag (seconds): {avg_lag:.2f}")
    print(f"Median Lag (seconds): {median_lag:.2f}")
    print("\nTop 5 Lag Events:")
    print(lag_df.head().to_string(index=False))

if __name__ == "__main__":
    run_hypothesis_2('../logs/market_tape_2026-05-02_12.csv')
