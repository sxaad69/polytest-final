import pandas as pd
import numpy as np
import sys

def run_study(csv_path):
    df = pd.read_csv(csv_path)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['window_start_ts'] = df['market_slug'].str.extract(r'(\d+)$').astype(float)
    df['window_start_dt'] = pd.to_datetime(df['window_start_ts'], unit='s')
    df['window_end_dt'] = df['window_start_dt'] + pd.Timedelta(minutes=5)
    df['rem'] = (df['window_end_dt'] - df['timestamp']).dt.total_seconds()
    
    picker_phase = df[(df['rem'] >= 240) & (df['rem'] <= 300)].copy()
    outcomes = df.groupby('market_slug')['poly_mid'].last().rename('final_price')
    grouped = df.groupby('market_slug')
    
    # Target Band: 0.33 to 0.54
    investment = 3.00
    sl_dist = 0.05
    tp_dist = 0.32 # Using a strong middle-ground TP
    
    results = []
    
    # Analyze YES Side entries (YES price is in the target band)
    yes_entries = picker_phase[(picker_phase['poly_mid'] >= 0.33) & (picker_phase['poly_mid'] <= 0.54)].sort_values('timestamp').groupby('market_slug').first()
    
    for slug, entry in yes_entries.iterrows():
        entry_price = entry['poly_mid']
        entry_time = entry['timestamp']
        shares = investment / entry_price
        market_data = grouped.get_group(slug)
        future_ticks = market_data[market_data['timestamp'] > entry_time].sort_values('timestamp')
        
        pnl = 0
        outcome_met = False
        if len(future_ticks) > 0:
            for _, tick in future_ticks.iterrows():
                if tick['poly_mid'] <= (entry_price - sl_dist): # SL
                    pnl = (shares * (entry_price - sl_dist)) - investment
                    outcome_met = True; break
                if tick['poly_mid'] >= (entry_price + tp_dist): # TP
                    pnl = (shares * (entry_price + tp_dist)) - investment
                    outcome_met = True; break
        
        if not outcome_met:
            final_val = outcomes.get(slug, 0.0)
            pnl = (shares * 1.0 - investment) if final_val > 0.5 else -investment
        results.append({'side': 'YES (LONG)', 'pnl': pnl})

    # Analyze NO Side entries (NO price is in the target band, meaning YES is in 1.0 - band)
    # NO Price = 1.0 - YES Price. If NO is 0.33-0.54, YES is 0.46-0.67
    no_entries = picker_phase[(picker_phase['poly_mid'] >= 0.46) & (picker_phase['poly_mid'] <= 0.67)].sort_values('timestamp').groupby('market_slug').first()
    
    for slug, entry in no_entries.iterrows():
        # We are buying NO shares. Price = 1.0 - poly_mid
        entry_price_no = 1.0 - entry['poly_mid']
        entry_time = entry['timestamp']
        shares = investment / entry_price_no
        market_data = grouped.get_group(slug)
        future_ticks = market_data[market_data['timestamp'] > entry_time].sort_values('timestamp')
        
        pnl = 0
        outcome_met = False
        if len(future_ticks) > 0:
            for _, tick in future_ticks.iterrows():
                current_price_no = 1.0 - tick['poly_mid']
                if current_price_no <= (entry_price_no - sl_dist): # SL
                    pnl = (shares * (entry_price_no - sl_dist)) - investment
                    outcome_met = True; break
                if current_price_no >= (entry_price_no + tp_dist): # TP
                    pnl = (shares * (entry_price_no + tp_dist)) - investment
                    outcome_met = True; break
        
        if not outcome_met:
            final_val = outcomes.get(slug, 0.0)
            # If final_val < 0.5, NO wins (it goes to 1.0)
            pnl = (shares * 1.0 - investment) if final_val < 0.5 else -investment
        results.append({'side': 'NO (SHORT)', 'pnl': pnl})
        
    res_df = pd.DataFrame(results)
    report = res_df.groupby('side').agg(
        trades=('pnl', 'count'),
        roi=('pnl', lambda x: (x.sum() / (len(x) * investment)) * 100 if len(x) > 0 else 0)
    )
    print("\n" + "="*60)
    print("TWO-SIDED ROI COMPARISON (0.33-0.54 Band)")
    print("="*60)
    print(report.to_string())
    print("="*60)

if __name__ == "__main__":
    csv_path = sys.argv[1] if len(sys.argv) > 1 else '../logs/market_tape_2026-05-03.csv'
    run_study(csv_path)
