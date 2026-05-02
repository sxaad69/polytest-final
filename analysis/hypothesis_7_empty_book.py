import pandas as pd
import numpy as np

def run_hypothesis_7(csv_path):
    print("--- Hypothesis 7: Empty Book Transition ---")
    try:
        df = pd.read_csv(csv_path)
    except FileNotFoundError:
        print(f"Error: Could not find {csv_path}")
        return

    # Check if we have bid/ask columns
    if 'poly_bid' not in df.columns or 'poly_ask' not in df.columns:
        print("Missing poly_bid or poly_ask columns in tape. Cannot test Hypothesis 7.")
        return

    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    results = []
    
    for slug, group in df.groupby('market_slug'):
        group = group.sort_values('timestamp').reset_index(drop=True)
        if len(group) < 10:
            continue
            
        transition_row = None
        
        # Look for a transition from wide spread (>0.80) to tight spread (<0.10)
        was_empty = False
        
        for idx, row in group.iterrows():
            spread = row['poly_ask'] - row['poly_bid']
            
            if spread > 0.80:
                was_empty = True
            elif was_empty and spread < 0.10:
                # Transition found!
                transition_row = row
                break
                
        if transition_row is not None:
            # We found the first populated book. Let's see if its direction predicts the end.
            trans_price = transition_row['poly_mid']
            final_price = group.iloc[-1]['poly_mid']
            
            # Predict YES if populated book price > 0.50, else NO
            predicted_winner = 1 if trans_price > 0.50 else 0
            actual_winner = 1 if final_price > 0.50 else 0
            
            correct = predicted_winner == actual_winner
            
            results.append({
                'slug': slug,
                'trans_time': transition_row['timestamp'],
                'trans_price': trans_price,
                'final_price': final_price,
                'predicted_winner': predicted_winner,
                'actual_winner': actual_winner,
                'correct': correct
            })

    if not results:
        print("No Empty-to-Populated book transitions detected in this sample.")
        return
        
    res_df = pd.DataFrame(results)
    total_transitions = len(res_df)
    correct_preds = res_df['correct'].sum()
    win_rate = correct_preds / total_transitions if total_transitions > 0 else 0
    
    print(f"Total Empty Book Transitions Detected: {total_transitions}")
    print(f"Correct Predictions (First populated mid vs final proxy): {correct_preds}")
    print(f"Empty Book Transition Win Rate: {win_rate:.2%}")

if __name__ == "__main__":
    run_hypothesis_7('../logs/market_tape_2026-05-02_12.csv')
