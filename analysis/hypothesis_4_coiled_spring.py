import pandas as pd
import numpy as np

def run_hypothesis_4(csv_path):
    print("--- Hypothesis 4: Flat-Then-Spike (Coiled Spring) ---")
    try:
        df = pd.read_csv(csv_path)
    except FileNotFoundError:
        print(f"Error: Could not find {csv_path}")
        return

    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    results = []
    
    for slug, group in df.groupby('market_slug'):
        group = group.sort_values('timestamp').reset_index(drop=True)
        if len(group) < 20:
            continue
            
        start_time = group['timestamp'].iloc[0]
        end_time = group['timestamp'].iloc[-1]
        
        # Need at least > 3 minutes of data to test this properly
        if (end_time - start_time).total_seconds() < 200:
            continue
            
        first_3_mins = group[group['timestamp'] <= start_time + pd.Timedelta(seconds=180)]
        if len(first_3_mins) < 5:
            continue
            
        max_price_3m = first_3_mins['poly_mid'].max()
        min_price_3m = first_3_mins['poly_mid'].min()
        
        # Check if "flat" (tight horizontal range)
        is_flat = (max_price_3m - min_price_3m) < 0.10 and min_price_3m >= 0.40 and max_price_3m <= 0.60
        
        if is_flat:
            # Look for breakout after 3 mins
            after_3_mins = group[group['timestamp'] > start_time + pd.Timedelta(seconds=180)]
            if len(after_3_mins) == 0:
                continue
                
            breakout_row = None
            breakout_dir = 0
            
            for idx, row in after_3_mins.iterrows():
                if row['poly_mid'] > max_price_3m + 0.05:
                    breakout_row = row
                    breakout_dir = 1
                    break
                elif row['poly_mid'] < min_price_3m - 0.05:
                    breakout_row = row
                    breakout_dir = -1
                    break
            
            if breakout_row is not None:
                final_price = group.iloc[-1]['poly_mid']
                actual_winner = 1 if final_price > 0.50 else -1
                
                is_correct = breakout_dir == actual_winner
                results.append({
                    'slug': slug,
                    'breakout_time': breakout_row['timestamp'],
                    'breakout_price': breakout_row['poly_mid'],
                    'breakout_dir': breakout_dir,
                    'final_price': final_price,
                    'actual_winner': actual_winner,
                    'correct': is_correct
                })
                
    if not results:
        print("No 'Flat-Then-Spike' events detected in this sample.")
        return
        
    res_df = pd.DataFrame(results)
    total_events = len(res_df)
    correct_preds = res_df['correct'].sum()
    win_rate = correct_preds / total_events if total_events > 0 else 0
    
    print(f"Total Flat-Then-Spike Events: {total_events}")
    print(f"Correct Predictions (Breakout dir == Final Outcome proxy): {correct_preds}")
    print(f"Flat-Then-Spike Win Rate: {win_rate:.2%}")

if __name__ == "__main__":
    import sys
    import os
    csv_path = sys.argv[1] if len(sys.argv) > 1 else '../logs/market_tape_2026-05-02_12.csv'
    run_hypothesis_4(csv_path)
