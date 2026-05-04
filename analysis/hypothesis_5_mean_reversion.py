import pandas as pd
import numpy as np

def run_hypothesis_5(csv_path):
    print("--- Hypothesis 5: Mean Reversion vs. Continuation ---")
    try:
        df = pd.read_csv(csv_path)
    except FileNotFoundError:
        print(f"Error: Could not find {csv_path}")
        return

    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    results = []
    
    for slug, group in df.groupby('market_slug'):
        group = group.sort_values('timestamp').reset_index(drop=True)
        if len(group) < 10:
            continue
            
        start_time = group['timestamp'].iloc[0]
        start_price = group['poly_mid'].iloc[0]
        
        first_2_mins = group[group['timestamp'] <= start_time + pd.Timedelta(seconds=120)]
        if len(first_2_mins) < 5:
            continue
            
        # Find spikes > 0.15 in first 2 mins
        spike_row = None
        spike_dir = 0
        
        for idx, row in first_2_mins.iterrows():
            if row['poly_mid'] - start_price > 0.15:
                spike_row = row
                spike_dir = 1
                break
            elif row['poly_mid'] - start_price < -0.15:
                spike_row = row
                spike_dir = -1
                break
                
        if spike_row is not None:
            spike_mom = spike_row['binance_mom']
            mom_aligned = (spike_dir == 1 and spike_mom > 0) or (spike_dir == -1 and spike_mom < 0)
            
            final_price = group.iloc[-1]['poly_mid']
            # Did it continue/hold (Continuation) or revert back towards start (Mean Reversion)?
            # Say it continued if final_price is still > 0.05 in spike direction from start
            continued = (spike_dir == 1 and final_price > start_price + 0.05) or \
                        (spike_dir == -1 and final_price < start_price - 0.05)
                        
            predicted_continuation = mom_aligned
            correct = predicted_continuation == continued
            
            results.append({
                'slug': slug,
                'spike_dir': spike_dir,
                'spike_mom': spike_mom,
                'mom_aligned': mom_aligned,
                'continued': continued,
                'correct_filter': correct
            })

    if not results:
        print("No significant early spikes detected in this sample.")
        return
        
    res_df = pd.DataFrame(results)
    total_spikes = len(res_df)
    correct_filters = res_df['correct_filter'].sum()
    accuracy = correct_filters / total_spikes if total_spikes > 0 else 0
    
    print(f"Total Early Spikes (>0.15 move in first 2m): {total_spikes}")
    print(f"Momentum correctly filtered Fake/Real spikes: {correct_filters} times")
    print(f"Filter Accuracy: {accuracy:.2%}")

if __name__ == "__main__":
    import sys
    import os
    csv_path = sys.argv[1] if len(sys.argv) > 1 else '../logs/market_tape_2026-05-02_12.csv'
    run_hypothesis_5(csv_path)
