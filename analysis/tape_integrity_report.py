import csv
import os
from collections import defaultdict

def run_integrity_report(file_path):
    if not os.path.exists(file_path):
        print(f"Error: {file_path} not found.")
        return

    # slug -> set of unique integer timestamps (seconds)
    slug_seconds = defaultdict(set)
    
    # Track the start and end of when we SAW the slug
    slug_first_seen = {}
    slug_last_seen = {}

    with open(file_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                slug = row['market_slug']
                timestamp_str = row['timestamp']
                second_key = timestamp_str.split('.')[0]
                
                slug_seconds[slug].add(second_key)
                
                if slug not in slug_first_seen:
                    slug_first_seen[slug] = timestamp_str
                slug_last_seen[slug] = timestamp_str
            except Exception:
                continue

    total_slugs = len(slug_seconds)
    verified_count = 0      # > 95% fidelity
    unverified_count = 0    # < 95% fidelity
    
    report_lines = []
    report_lines.append(f"--- TAPE INTEGRITY REPORT: {os.path.basename(file_path)} ---")
    report_lines.append(f"{'Market Slug':<35} | {'Missing Secs':<12} | {'Fidelity %'}")
    report_lines.append("-" * 65)

    sorted_slugs = sorted(slug_seconds.keys(), key=lambda x: x.split('-')[-1])

    for slug in sorted_slugs:
        unique_secs = len(slug_seconds[slug])
        
        # 5m = 300s
        missing_secs = 300 - unique_secs
        fidelity_pct = (unique_secs / 300.0) * 100
        
        if fidelity_pct >= 95.0:
            verified_count += 1
            status = "VERIFIED"
        else:
            unverified_count += 1
            status = "SPARSE"

        # Only report slugs that were present for most of the hour 
        # (avoiding those cut off by file start/end)
        report_lines.append(f"{slug:<35} | {missing_secs:<12} | {fidelity_pct:>9.1f}% [{status}]")

    summary = []
    summary.append("\n=== FINAL SUMMARY ===")
    summary.append(f"TOTAL SLUGS ANALYZED: {total_slugs}")
    summary.append(f"VERIFIED (HIGH FIDELITY): {verified_count}")
    summary.append(f"UNVERIFIED (SPARSE DATA): {unverified_count}")
    
    # Print to console
    for line in report_lines:
        print(line)
    for line in summary:
        print(line)

    # Save to a text file for your records
    with open("analysis/integrity_report_hour14.txt", "w") as f:
        f.write("\n".join(report_lines))
        f.write("\n".join(summary))

if __name__ == "__main__":
    # Ensure analysis directory exists
    os.makedirs("analysis", exist_ok=True)
    run_integrity_report("logs/market_tape_2026-05-02_04.csv")
