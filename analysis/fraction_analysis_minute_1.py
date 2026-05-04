import pandas as pd
import numpy as np
import sys

def run_simulation(csv_path):
    df = pd.read_csv(csv_path)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['window_start_ts'] = df['market_slug'].str.extract(r'(\d+)$').astype(float)
    df['window_start_dt'] = pd.to_datetime(df['window_start_ts'], unit='s')
    df['window_end_dt'] = df['window_start_dt'] + pd.Timedelta(minutes=5)
    df['rem'] = (df['window_end_dt'] - df['timestamp']).dt.total_seconds()
    
    # FRACTION 1: 0-1M (The Picker) 
    # This corresponds to 240-300 seconds remaining
    picker_phase = df[(df['rem'] >= 240) & (df['rem'] <= 300)].copy()
    
    # 3-cent Price Bands (0.00 to 1.00)
    bins = np.arange(0.00, 1.03, 0.03)
    labels = [f"{bins[i]:.2f}-{bins[i+1]:.2f}" for i in range(len(bins)-1)]
    picker_phase['price_band'] = pd.cut(picker_phase['poly_mid'], bins=bins, labels=labels)
    
    outcomes = df.groupby('market_slug')['poly_mid'].last().rename('final_price')
    
    # Unique entries per market in this fraction
    unique_entries = picker_phase.sort_values('timestamp').groupby(['market_slug', 'price_band'], observed=False).first().dropna(subset=['poly_mid'])
    unique_entries = unique_entries.join(outcomes, on='market_slug')
    
    investment = 3.00
    def calc_profit(row):
        if row['final_price'] > 0.5:
            return (investment / row['poly_mid']) - investment
        else:
            return -investment

    unique_entries['pnl'] = unique_entries.apply(calc_profit, axis=1)
    
    report = unique_entries.groupby('price_band', observed=False).agg(
        trades=('pnl', 'count'),
        win_rate=('pnl', lambda x: (x > 0).mean() * 100),
        net_pnl=('pnl', 'sum')
    )
    report['roi'] = (report['net_pnl'] / (report['trades'] * investment)) * 100
    
    print("\n" + "="*80)
    print("FRACTION 1: THE PICKER (Minute 0-1) | ROI Analysis")
    print("="*80)
    # Filter out 0-trade bands for readability
    report = report[report['trades'] > 0]
    print(report[['trades', 'win_rate', 'net_pnl', 'roi']].to_string(formatters={
        'win_rate': '{:,.2f}%'.format,
        'net_pnl': '${:,.2f}'.format,
        'roi': '{:,.2f}%'.format
    }))
    print("="*80)

if __name__ == "__main__":
    csv_path = sys.argv[1] if len(sys.argv) > 1 else '../logs/market_tape_2026-05-03.csv'
    run_simulation(csv_path)
