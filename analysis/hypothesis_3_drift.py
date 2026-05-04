import pandas as pd
import numpy as np

def run_hypothesis_3(csv_path):
    print("--- Hypothesis 3: Pre-Resolution Drift ---")
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
            
        # Get the final timestamp in the group (end of window or closest to it)
        end_time = group['timestamp'].iloc[-1]
        
        # We need data for the last 90 seconds
        drift_start_time = end_time - pd.Timedelta(seconds=90)
        
        drift_period = group[group['timestamp'] >= drift_start_time]
        if len(drift_period) < 5:
            continue # Not enough data in the final 90 seconds
            
        # Price at the start of the final 90 seconds
        start_price = drift_period.iloc[0]['poly_mid']
        # Final price in our tape
        final_price = drift_period.iloc[-1]['poly_mid']
        
        # Did it drift? Let's say a drift is a change of at least 0.05
        price_change = final_price - start_price
        
        if abs(price_change) >= 0.05:
            # Predict YES if it drifted UP, predict NO (or 0) if it drifted DOWN
            predicted_winner = 1 if price_change > 0 else 0
            
            # Since we don't have the official settlement data in the tape, 
            # we will assume if it ended > 0.50 it resolved YES, and < 0.50 resolved NO.
            # This is a proxy for final resolution.
            actual_winner = 1 if final_price > 0.50 else 0
            
            is_correct = predicted_winner == actual_winner
            
            results.append({
                'slug': slug,
                'start_price_t90': start_price,
                'final_price': final_price,
                'price_change': price_change,
                'predicted_winner': predicted_winner,
                'actual_winner': actual_winner,
                'correct': is_correct
            })
            
    if not results:
        print("No significant pre-resolution drift found in this sample.")
        return
        
    res_df = pd.DataFrame(results)
    total_drifts = len(res_df)
    correct_predictions = res_df['correct'].sum()
    win_rate = correct_predictions / total_drifts if total_drifts > 0 else 0
    
    print(f"Total Drift Events (>0.05 change in last 90s): {total_drifts}")
    print(f"Correct Predictions (Drift direction matched final outcome proxy): {correct_predictions}")
    print(f"Pre-Resolution Drift Win Rate: {win_rate:.2%}")
    if win_rate > 0.70:
        print("-> HYPOTHESIS CONFIRMED: Drift win rate is >70%")
    else:
        print("-> HYPOTHESIS REJECTED: Drift win rate is not >70%")

if __name__ == "__main__":
    import sys
    import os
    csv_path = sys.argv[1] if len(sys.argv) > 1 else '../logs/market_tape_2026-05-02_12.csv'
    run_hypothesis_3(csv_path)
