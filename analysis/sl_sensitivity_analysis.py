import pandas as pd
import numpy as np
import sys

def run_sl_test(csv_path):
    df = pd.read_csv(csv_path)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    # Extract START time and calculate Window End
    df['window_start_ts'] = df['market_slug'].str.extract(r'(\d+)$').astype(float)
    df['window_start_dt'] = pd.to_datetime(df['window_start_ts'], unit='s')
    df['window_end_dt'] = df['window_start_dt'] + pd.Timedelta(minutes=5)
    df['seconds_remaining'] = (df['window_end_dt'] - df['timestamp']).dt.total_seconds()
    
    # Filter for the Target Zone: 0.80-0.95 price, 90-120s remaining
    entries = df[
        (df['poly_mid'] >= 0.80) & 
        (df['poly_mid'] <= 0.95) & 
        (df['seconds_remaining'] >= 90) & 
        (df['seconds_remaining'] <= 120)
    ].copy()
    
    results = []
    
    # Group the main dataframe by slug for faster lookups
    grouped = df.groupby('market_slug')
    
    print(f"Simulating {len(entries)} potential entries...")
    
    for idx, entry in entries.iterrows():
        slug = entry['market_slug']
        entry_price = entry['poly_mid']
        entry_time = entry['timestamp']
        sl_price = entry_price - 0.05
        
        # Get future ticks for this market
        market_data = grouped.get_group(slug)
        future_ticks = market_data[market_data['timestamp'] > entry_time].sort_values('timestamp')
        
        if len(future_ticks) == 0:
            continue
            
        outcome = "WIN"
        final_price = future_ticks.iloc[-1]['poly_mid']
        
        # Check for Stop Loss hit
        for _, tick in future_ticks.iterrows():
            if tick['poly_mid'] <= sl_price:
                outcome = "STOP_LOSS"
                break
        
        # If not stopped out, check final resolution
        if outcome != "STOP_LOSS":
            if final_price > 0.5: # Resolved YES
                outcome = "WIN"
            else:
                outcome = "LOSS (NO)"
                
        results.append({
            'slug': slug,
            'entry_price': entry_price,
            'outcome': outcome
        })
        
    res_df = pd.DataFrame(results)
    summary = res_df['outcome'].value_counts(normalize=True) * 100
    counts = res_df['outcome'].value_counts()
    
    print("\n" + "="*50)
    print(f"STOP LOSS SENSITIVITY (-5 Cents)")
    print(f"Zone: 0.80-0.95 Price | 90-120s Remaining")
    print("="*50)
    for category in ['WIN', 'STOP_LOSS', 'LOSS (NO)']:
        pct = summary.get(category, 0)
        cnt = counts.get(category, 0)
        print(f"{category:<12}: {pct:5.2f}% ({cnt} cases)")
    print("="*50)

if __name__ == "__main__":
    csv_path = sys.argv[1] if len(sys.argv) > 1 else '../logs/market_tape_2026-05-03.csv'
    run_sl_test(csv_path)
