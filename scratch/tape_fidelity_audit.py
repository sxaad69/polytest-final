import csv
import os
from collections import defaultdict

def run_fidelity_audit(file_path):
    if not os.path.exists(file_path):
        print(f"Error: {file_path} not found.")
        return

    # slug -> set of unique integer timestamps (seconds)
    slug_seconds = defaultdict(set)
    slug_tick_count = defaultdict(int)

    with open(file_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                slug = row['market_slug']
                # Convert timestamp string to total seconds (integer)
                # Format: 2026-05-01 14:13:21.715
                # We just care about the date + hour + minute + second part
                second_key = row['timestamp'].split('.')[0]
                
                slug_seconds[slug].add(second_key)
                slug_tick_count[slug] += 1
            except Exception:
                continue

    print(f"\n--- MARKET TAPE FIDELITY AUDIT ---")
    print(f"{'Market Slug':<35} | {'Ticks':<6} | {'Unique Secs':<11} | {'Fidelity %'}")
    print("-" * 75)

    # Sort slugs by their window timestamp (last part of slug)
    sorted_slugs = sorted(slug_seconds.keys(), key=lambda x: x.split('-')[-1])

    for slug in sorted_slugs:
        unique_secs = len(slug_seconds[slug])
        tick_count = slug_tick_count[slug]
        
        # All our markets are 5m (300s)
        fidelity_pct = (unique_secs / 300.0) * 100
        
        # Only show markets that have a reasonable amount of data to avoid cluttering with 
        # markets that just started or just ended at the hour boundary
        if tick_count > 50:
            print(f"{slug:<35} | {tick_count:<6} | {unique_secs:<11} | {fidelity_pct:>9.1f}%")

if __name__ == "__main__":
    run_fidelity_audit("logs/market_tape_2026-05-01_14.csv")
