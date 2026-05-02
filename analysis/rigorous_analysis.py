import pandas as pd
import numpy as np
import sys

def run_rigorous_analysis(csv_path):
    try:
        df = pd.read_csv(csv_path)
    except FileNotFoundError:
        print(f"Error: Could not find {csv_path}")
        return

    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['window_start_ts'] = df['market_slug'].str.extract(r'(\d+)$').astype(float)
    df['window_start_dt'] = pd.to_datetime(df['window_start_ts'], unit='s')
    df['window_end_dt'] = df['window_start_dt'] + pd.Timedelta(minutes=5)
    
    print("==================================================")
    print(f"RIGOROUS ROADMAP ANALYSIS ON {csv_path}")
    print("==================================================")
    
    # ---------------------------------------------------------
    # H2: BINANCE LEAD-TIME LAG (Cross-Correlation)
    # ---------------------------------------------------------
    print("\n--- Hypothesis 2: Binance Lag (Cross-Correlation) ---")
    best_lags = []
    for slug, group in df.groupby('market_slug'):
        group = group.set_index('timestamp').resample('1S').agg({
            'poly_mid': 'last',
            'binance_mom': 'last'
        })
        group['poly_mid'] = group['poly_mid'].ffill()
        group['binance_mom'] = group['binance_mom'].fillna(0)
        group['poly_diff'] = group['poly_mid'].diff().fillna(0)
        
        if len(group) < 60: continue
            
        corrs = []
        for shift in range(0, 31):
            shifted_poly = group['poly_diff'].shift(-shift).fillna(0)
            corr = group['binance_mom'].corr(shifted_poly)
            if not pd.isna(corr):
                corrs.append((shift, corr))
                
        if corrs:
            best_shift = max(corrs, key=lambda x: x[1])
            if best_shift[1] > 0.1:
                best_lags.append(best_shift[0])
                
    if best_lags:
        print(f"Rigorous Median Lag (highest correlation): {np.median(best_lags):.1f} seconds")
    else:
        print("No statistically significant lag correlation found across the tape.")

    # ---------------------------------------------------------
    # H3: PRE-RESOLUTION DRIFT (Strict Timing)
    # ---------------------------------------------------------
    print("\n--- Hypothesis 3: Pre-Resolution Drift ---")
    drift_events = []
    for slug, group in df.groupby('market_slug'):
        window_end = group['window_end_dt'].iloc[0]
        drift_start = window_end - pd.Timedelta(seconds=90)
        
        drift_period = group[(group['timestamp'] >= drift_start) & (group['timestamp'] <= window_end)]
        
        if len(drift_period) < 5:
            continue
            
        start_p = drift_period.iloc[0]['poly_mid']
        end_p = drift_period.iloc[-1]['poly_mid']
        drift_amount = end_p - start_p
        
        if abs(drift_amount) >= 0.05:
            resolved_yes = end_p > 0.50
            predicted_yes = drift_amount > 0
            drift_events.append(resolved_yes == predicted_yes)

    if drift_events:
        print(f"Valid final-90s drift events captured: {len(drift_events)}")
        print(f"True Win Rate: {(sum(drift_events)/len(drift_events)):.2%}")
    else:
        print("Tape does not contain enough data in the final 90 seconds of any window to rigorously test this.")

    # ---------------------------------------------------------
    # H5: MEAN REVERSION VS CONTINUATION (Prior Momentum)
    # ---------------------------------------------------------
    print("\n--- Hypothesis 5: Mean Reversion vs. Continuation ---")
    h5_events = []
    for slug, group in df.groupby('market_slug'):
        start_time = group['window_start_dt'].iloc[0]
        first_2_mins = group[(group['timestamp'] >= start_time) & (group['timestamp'] <= start_time + pd.Timedelta(minutes=2))]
        if len(first_2_mins) < 10: continue
            
        start_price = first_2_mins.iloc[0]['poly_mid']
        
        for idx, row in first_2_mins.iterrows():
            diff = row['poly_mid'] - start_price
            if abs(diff) >= 0.15:
                prior_time = row['timestamp'] - pd.Timedelta(seconds=10)
                prior_data = group[group['timestamp'] <= prior_time]
                if len(prior_data) == 0: break
                
                prior_mom = prior_data.iloc[-1]['binance_mom']
                spike_dir = 1 if diff > 0 else -1
                
                end_price = first_2_mins.iloc[-1]['poly_mid']
                continued = (spike_dir == 1 and end_price > start_price + 0.05) or \
                            (spike_dir == -1 and end_price < start_price - 0.05)
                
                mom_aligned = (spike_dir == 1 and prior_mom > 0) or (spike_dir == -1 and prior_mom < 0)
                h5_events.append(continued == mom_aligned)
                break

    if h5_events:
        print(f"Early spikes detected: {len(h5_events)}")
        print(f"Prior-Momentum Filter Accuracy: {(sum(h5_events)/len(h5_events)):.2%}")
    else:
        print("No valid early spikes found to test.")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        run_rigorous_analysis(sys.argv[1])
    else:
        run_rigorous_analysis('../logs/market_tape_2026-05-02_12.csv')
