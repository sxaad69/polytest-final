import csv
import os
from collections import defaultdict

def analyze_opening_bias(labeled_path):
    if not os.path.exists(labeled_path):
        print(f"Error: {labeled_path} not found. Run the Data Integrator first.")
        return

    # Track the 'Opening Price' (first transition) and the 'Closing Price' (last seen)
    # slug -> { 'open': price, 'close': price, 'asset': asset }
    outcomes = {}

    with open(labeled_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            slug = row['market_slug']
            is_valid = row['is_valid'] == 'True'
            is_transition = row['is_transition'] == 'True'
            price = float(row['poly_mid'])
            asset = row['asset']

            if is_transition:
                outcomes[slug] = {
                    'open': price,
                    'close': price,
                    'asset': asset
                }
            elif is_valid and slug in outcomes:
                # Keep updating 'close' to be the latest valid price we see
                outcomes[slug]['close'] = price

    print(f"\n--- HYPOTHESIS #1: OPENING BIAS REPORT ---")
    print(f"{'Asset':<8} | {'Open Mid':<10} | {'Current Mid':<11} | {'Direction'}")
    print("-" * 55)

    for slug, data in outcomes.items():
        direction = "STABLE"
        if data['close'] > data['open']: direction = "UP (YES)"
        elif data['close'] < data['open']: direction = "DOWN (NO)"
        
        print(f"{data['asset']:<8} | {data['open']:<10.3f} | {data['close']:<11.3f} | {direction}")

if __name__ == "__main__":
    # This will be run on the Labeled Hour 10 file once it is downloaded and processed
    analyze_opening_bias("logs/market_tape_2026-05-02_10_LABELED.csv")
