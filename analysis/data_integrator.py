import csv
import os

def integrate_and_label(input_path):
    if not os.path.exists(input_path):
        print(f"Error: {input_path} not found.")
        return

    output_path = input_path.replace(".csv", "_LABELED.csv")
    
    # Track which slugs have already transitioned to "Valid"
    has_transitioned = set()
    
    # Stats for the report
    total_rows = 0
    valid_rows = 0
    transitions_found = 0

    print(f"Integrating data from {input_path}...")

    with open(input_path, 'r') as f_in, open(output_path, 'w', newline='') as f_out:
        reader = csv.DictReader(f_in)
        fieldnames = reader.fieldnames + ['is_valid', 'is_transition']
        writer = csv.DictWriter(f_out, fieldnames=fieldnames)
        writer.writeheader()

        for row in reader:
            total_rows += 1
            slug = row['market_slug']
            try:
                bid = float(row['poly_bid'])
                ask = float(row['poly_ask'])
                spread = ask - bid
                
                # CRITERIA FOR VALID BOOK (Relaxed to catch the first heartbeat):
                # 1. Bid must be above 0
                # 2. Ask must be below 1
                is_valid = (bid > 0 and ask < 1)
                
                is_transition = False
                if is_valid and slug not in has_transitioned:
                    is_transition = True
                    has_transitioned.add(slug)
                    transitions_found += 1
                
                if is_valid:
                    valid_rows += 1

                # Add labels
                row['is_valid'] = 'True' if is_valid else 'False'
                row['is_transition'] = 'True' if is_transition else 'False'
                writer.writerow(row)
                
            except Exception:
                # Skip corrupt rows
                continue

    print(f"\n--- DATA INTEGRATION COMPLETE ---")
    print(f"Output saved to: {output_path}")
    print(f"Total Ticks Processed: {total_rows}")
    print(f"Valid Ticks (Truth Grade): {valid_rows} ({ (valid_rows/total_rows)*100:.1f}%)")
    print(f"Total Market Transitions Found: {transitions_found}")
    print(f"Noise Rows Labeled (Placeholder Data): {total_rows - valid_rows}")

if __name__ == "__main__":
    # We'll process Hour 09 to verify the fix
    integrate_and_label("logs/market_tape_2026-05-02_10.csv")
