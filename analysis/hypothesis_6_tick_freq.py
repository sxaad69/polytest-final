import pandas as pd

def run_hypothesis_6(csv_path):
    print("--- Hypothesis 6: Tick Frequency (Smart Money Detection) ---")
    try:
        df = pd.read_csv(csv_path)
    except FileNotFoundError:
        print(f"Error: Could not find {csv_path}")
        return

    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    results = []
    
    for slug, group in df.groupby('market_slug'):
        group = group.sort_values('timestamp').set_index('timestamp')
        if len(group) < 30:
            continue
            
        # Count ticks per 30 seconds
        tick_counts = group.resample('30S').size()
        
        # Define 'surge' as a period with significantly more ticks than average for that market
        avg_ticks = tick_counts.mean()
        std_ticks = tick_counts.std()
        
        if pd.isna(std_ticks) or std_ticks == 0:
            continue
            
        surge_threshold = avg_ticks + (1.5 * std_ticks)
        
        surges = tick_counts[tick_counts > surge_threshold]
        
        for surge_time, count in surges.items():
            # Look at price action in the next 60 seconds
            start_price = group.loc[:surge_time, 'poly_mid'].iloc[-1] if len(group.loc[:surge_time]) > 0 else group['poly_mid'].iloc[0]
            
            lookahead_end = surge_time + pd.Timedelta(seconds=90)
            lookahead_group = group.loc[surge_time:lookahead_end]
            
            if len(lookahead_group) < 2:
                continue
                
            max_move = (lookahead_group['poly_mid'] - start_price).abs().max()
            
            significant_move = max_move > 0.10
            
            results.append({
                'slug': slug,
                'surge_time': surge_time,
                'ticks_in_period': count,
                'avg_ticks': avg_ticks,
                'max_subsequent_move': max_move,
                'significant_move': significant_move
            })
            
    if not results:
        print("No tick surges detected in this sample.")
        return
        
    res_df = pd.DataFrame(results)
    total_surges = len(res_df)
    sig_moves = res_df['significant_move'].sum()
    predictive_rate = sig_moves / total_surges if total_surges > 0 else 0
    
    print(f"Total Tick Surges Detected: {total_surges}")
    print(f"Surges followed by Significant Move (>0.10 in 90s): {sig_moves}")
    print(f"Predictive Rate: {predictive_rate:.2%}")

if __name__ == "__main__":
    import sys
    import os
    csv_path = sys.argv[1] if len(sys.argv) > 1 else '../logs/market_tape_2026-05-02_12.csv'
    run_hypothesis_6(csv_path)
