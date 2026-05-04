import pandas as pd
import numpy as np

def run_transparent_analysis(csv_path):
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
    print("TRANSPARENT DATA INTEGRITY & ANALYSIS REPORT")
    print("==================================================")
    
    valid_windows_for_drift = 0
    valid_windows_for_lag = 0
    
    for slug, group in df.groupby('market_slug'):
        group = group.sort_values('timestamp').reset_index(drop=True)
        window_start = group['window_start_dt'].iloc[0]
        window_end = group['window_end_dt'].iloc[0]
        
        # 1. DATA INTEGRITY CHECK
        print(f"\n[MARKET] {slug}")
        raw_ticks = len(group)
        
        # How much of the 5-minute window is actually captured in this tape?
        # A perfect 1Hz feed would have 300 ticks.
        tape_start = group['timestamp'].iloc[0]
        tape_end = group['timestamp'].iloc[-1]
        
        # Calculate overlap with the actual official window
        actual_start = max(tape_start, window_start)
        actual_end = min(tape_end, window_end)
        captured_duration = (actual_end - actual_start).total_seconds()
        
        if captured_duration <= 0:
            print("  -> ERROR: Tape data does not overlap with official window time.")
            continue
            
        coverage_pct = captured_duration / 300.0
        print(f"  -> Raw Ticks: {raw_ticks} (Ideal: 300)")
        print(f"  -> Window Coverage: {coverage_pct:.1%} ({captured_duration:.1f} out of 300 seconds)")
        
        if coverage_pct < 0.50:
            print("  -> WARNING: Less than 50% of window captured. Discarding from deep analysis.")
            continue
            
        # 2. TICK FREQUENCY EXPLANATION
        # Websockets only push when the price or orderbook changes. 
        # Therefore, raw_ticks / captured_duration is our tick frequency.
        tps = raw_ticks / captured_duration
        print(f"  -> Tick Frequency: {tps:.2f} ticks per second")
        if tps < 0.5:
            print("  -> NOTE: Feed is sparse. Polymarket price is likely staying flat for long periods.")
            
        # 3. HYPOTHESIS 3: 90s DRIFT STRICT VALIDATION
        # The true final 90 seconds of the official window:
        drift_start = window_end - pd.Timedelta(seconds=90)
        drift_end = window_end
        
        # Do we have data for this exact period?
        drift_data = group[(group['timestamp'] >= drift_start) & (group['timestamp'] <= drift_end)]
        
        print("  -> [H3: 90s Drift Check]")
        if len(drift_data) == 0:
            print("     -> ERROR: No data points exist in the final 90 seconds. Cannot calculate drift.")
        else:
            # We need a data point near the start of the 90s period and near the end
            first_drift_tick = drift_data.iloc[0]['timestamp']
            last_drift_tick = drift_data.iloc[-1]['timestamp']
            
            gap_from_drift_start = (first_drift_tick - drift_start).total_seconds()
            gap_to_drift_end = (drift_end - last_drift_tick).total_seconds()
            
            if gap_from_drift_start > 15:
                print(f"     -> INVALID: Missing data at the start of the 90s window (Gap: {gap_from_drift_start:.1f}s)")
            elif gap_to_drift_end > 15:
                print(f"     -> INVALID: Missing data at the end of the 90s window (Gap: {gap_to_drift_end:.1f}s)")
            else:
                drift_amount = drift_data.iloc[-1]['poly_mid'] - drift_data.iloc[0]['poly_mid']
                print(f"     -> VALID: Drift successfully calculated. Amount: {drift_amount:.4f}")
                valid_windows_for_drift += 1

        # 4. HYPOTHESIS 2: LAG ANALYSIS STRICT VALIDATION
        print("  -> [H2: Lag Check]")
        # We need continuous 1-second data to run Pearson correlation properly without interpolating huge gaps.
        # Check maximum gap between ticks
        group['time_diff'] = group['timestamp'].diff().dt.total_seconds()
        max_gap = group['time_diff'].max()
        if max_gap > 10:
            print(f"     -> INVALID: Tape has a continuous gap of {max_gap:.1f}s. Interpolating correlation would hallucinate data.")
        else:
            print(f"     -> VALID: Max gap is {max_gap:.1f}s. Safe for 1s resampling correlation.")
            valid_windows_for_lag += 1

    print("\n==================================================")
    print("FINAL DATA HEALTH SUMMARY")
    print(f"Windows valid for strict Drift Analysis: {valid_windows_for_drift}")
    print(f"Windows valid for strict Lag Analysis:   {valid_windows_for_lag}")
    print("==================================================")

import sys
if __name__ == "__main__":
    if len(sys.argv) > 1:
        run_transparent_analysis(sys.argv[1])
    else:
        run_transparent_analysis('../logs/market_tape_2026-05-02_12.csv')
