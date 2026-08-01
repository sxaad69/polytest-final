import sqlite3
import pandas as pd
import glob
import re
import os
import gzip

def parse_logs_for_peaks(log_pattern):
    print(f"Parsing logs matching: {log_pattern}...")
    files = glob.glob(log_pattern)
    files.sort(key=lambda x: os.path.getmtime(x))
    
    trade_peaks = {}
    
    # Regex to extract Trade ID, Entry, and Peak
    # Format: 2026-06-09 14:45:01,660 [HEARTBEAT] [Bot SNIPER] Trade #2587 (eth-updown...) [SHORT] | Conf: 2.0000 | Entry: 0.980 | Peak: 0.990 | Current: ...
    regex = re.compile(r"Trade #(\d+) .*?Entry: ([\d.]+) \| Peak: ([\d.]+)")

    for fpath in files:
        print(f"  -> Reading {os.path.basename(fpath)}")
        try:
            # Handle zipped if they exist, else plain
            open_func = gzip.open if fpath.endswith('.gz') else open
            with open_func(fpath, 'rt', encoding='utf-8') as f:
                for line in f:
                    if "[HEARTBEAT]" not in line or "Trade #" not in line:
                        continue
                    m = regex.search(line)
                    if m:
                        t_id = int(m.group(1))
                        # entry = float(m.group(2))
                        peak = float(m.group(3))
                        if t_id not in trade_peaks:
                            trade_peaks[t_id] = peak
                        else:
                            if peak > trade_peaks[t_id]:
                                trade_peaks[t_id] = peak
        except Exception as e:
            print(f"Error reading {fpath}: {e}")
            
    print(f"Found peak data for {len(trade_peaks)} trades.")
    return trade_peaks

def main():
    DB_PATH = "/home/ubuntu/polytest-final/data/bot_g_paper.db"
    LOGS_PATTERN = "/home/ubuntu/polytest-final/logs/open_positions.log*"
    
    # 1. Connect to DB and pull trades with valid chainlink_lag
    try:
        conn = sqlite3.connect(DB_PATH)
        df_trades = pd.read_sql_query("SELECT id, asset, entry_odds FROM trades", conn)
        conn.close()
    except Exception as e:
        print(f"Database error: {e}")
        return

    print(f"Loaded {len(df_trades)} trades from {DB_PATH}")

    # 2. Parse logs
    peaks_map = parse_logs_for_peaks(LOGS_PATTERN)
    
    # 3. Correlate
    results = []
    for _, row in df_trades.iterrows():
        t_id = row['id']
        entry = float(row['entry_odds'])
        
        if t_id in peaks_map:
            peak = peaks_map[t_id]
            max_profit = peak - entry
            
            results.append({
                'id': t_id,
                'asset': row['asset'],
                'max_profit': max_profit
            })
            
    df_res = pd.DataFrame(results)
    if df_res.empty:
        print("No matches found between DB and logs.")
        return
        
    print("\n" + "="*50)
    print("EARLY SNIPER SMASH PROFIT ANALYSIS")
    print("="*50)
    
    total = len(df_res)
    hit_10c = len(df_res[df_res['max_profit'] >= 0.10])
    hit_20c = len(df_res[df_res['max_profit'] >= 0.20])
    
    pct_10c = (hit_10c / total) * 100 if total > 0 else 0
    pct_20c = (hit_20c / total) * 100 if total > 0 else 0
    
    print(f"Total Early Sniper Trades Matched: {total}")
    print(f">= 10c Smash Profit Hit: {hit_10c} ({pct_10c:.1f}%)")
    print(f">= 20c Smash Profit Hit: {hit_20c} ({pct_20c:.1f}%)")
    
    out_csv = "/home/ubuntu/polytest-final/data/lag_smash_correlation.csv"
    df_res.to_csv(out_csv, index=False)
    print(f"\nDetailed CSV exported to: {out_csv}")

if __name__ == '__main__':
    main()
