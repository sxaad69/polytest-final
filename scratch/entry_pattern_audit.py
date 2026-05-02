import csv
import os
from collections import defaultdict
from datetime import datetime

# --- CONFIG PARAMETERS ---
MIN_CONFIDENCE = 0.05

def run_pattern_audit(file_path):
    if not os.path.exists(file_path):
        print(f"Error: {file_path} not found.")
        return

    # asset -> minute_of_5m_window -> count
    patterns = defaultdict(lambda: defaultdict(int))
    total_signals = 0

    with open(file_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                dt = datetime.strptime(row['timestamp'], "%Y-%m-%d %H:%M:%S.%f")
                mom = abs(float(row['binance_mom']))
                asset = row['asset']

                if mom >= MIN_CONFIDENCE:
                    # Calculate minute within the current 5-minute block of the hour
                    # e.g., 14:13 -> 13 % 5 = 3rd minute
                    minute_of_window = dt.minute % 5
                    patterns[asset][minute_of_window] += 1
                    total_signals += 1
            except Exception:
                continue

    print(f"\n--- ENTRY SIGNAL PATTERN AUDIT (Hour 14) ---")
    print(f"Total valid ticks meeting {MIN_CONFIDENCE} threshold: {total_signals}\n")
    
    # Header
    print(f"{'Asset':<8} | {'0-1m':<6} | {'1-2m':<6} | {'2-3m':<6} | {'3-4m':<6} | {'4-5m':<6}")
    print("-" * 55)

    assets = sorted(patterns.keys())
    for asset in assets:
        counts = [patterns[asset][m] for m in range(5)]
        print(f"{asset:<8} | {counts[0]:<6} | {counts[1]:<6} | {counts[2]:<6} | {counts[3]:<6} | {counts[4]:<6}")

    # Aggregated totals per minute
    print("-" * 55)
    totals = [sum(patterns[a][m] for a in assets) for m in range(5)]
    print(f"{'TOTAL':<8} | {totals[0]:<6} | {totals[1]:<6} | {totals[2]:<6} | {totals[3]:<6} | {totals[4]:<6}")

if __name__ == "__main__":
    run_pattern_audit("logs/market_tape_2026-05-01_14.csv")
