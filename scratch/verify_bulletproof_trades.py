import re
import sys
from datetime import datetime

def analyze_trade(log_content, trade_id):
    print(f"\n{'='*60}")
    print(f" ANALYZING TRADE #{trade_id}")
    print(f"{'='*60}")
    
    # Filter lines for this trade
    lines = [l for l in log_content if f"Trade #{trade_id}" in l]
    if not lines:
        print(f"No logs found for Trade #{trade_id}")
        return

    entry_price = None
    exit_price = None
    peak_price = 0
    exit_reason = ""
    exit_time = None
    
    # Tracking prices
    price_history = []
    
    for line in lines:
        # Extract data using regex
        # Format: 2026-05-01 09:04:19,899 [HEARTBEAT] [Bot G] Trade #80 (DOGE-short) | Entry: 0.680 | Current: 0.930 | Peak: 0.930 | Target: 0.910 | Source: WS
        ts_str = line[:23]
        
        entry_match = re.search(r"Entry: ([\d\.]+)", line)
        curr_match = re.search(r"Current: ([\d\.]+)", line)
        peak_match = re.search(r"Peak: ([\d\.]+)", line)
        reason_match = re.search(r"Closed at: ([\d\.]+) \((.*?)\)", line)
        
        if entry_match: entry_price = float(entry_match.group(1))
        if curr_match: 
            curr_p = float(curr_match.group(1))
            price_history.append((ts_str, curr_p))
        if peak_match: peak_price = max(peak_price, float(peak_match.group(1)))
        
        if reason_match and not exit_price:
            exit_price = float(reason_match.group(1))
            exit_reason = reason_match.group(2)
            exit_time = ts_str

    if not entry_price:
        print("Could not determine entry price.")
        return

    print(f"Entry Price:  {entry_price}")
    print(f"Peak Price:   {peak_price}")
    print(f"Exit Price:   {exit_price} ({exit_reason})")
    
    if exit_price and peak_price > 0:
        gap = abs(peak_price - exit_price)
        print(f"Ratchet Gap:  {gap:.3f} (Ideal is 0.02)")
        
    # Find the peak timestamp
    peak_ts = next((ts for ts, p in price_history if p == peak_price), "Unknown")
    print(f"Peak Reached: {peak_ts}")
    print(f"Exit Time:    {exit_time}")
    
    # Analyze Post-Exit (last 5 entries in history after exit_time)
    post_exit_prices = []
    found_exit = False
    for ts, p in price_history:
        if ts == exit_time: found_exit = True
        if found_exit: post_exit_prices.append(p)
    
    if len(post_exit_prices) > 1:
        print(f"Post-Exit Action: {post_exit_prices[1:6]}")
        first_post = post_exit_prices[1]
        if exit_reason == "profit_ratchet_exit":
            # For a long, we want price to drop after exit. For a short, we want it to rise.
            # In our logs, "Current" is always converted to the same direction as profit.
            if first_post < exit_price:
                print("Result: ✅ Perfect Exit. Price decayed after we left.")
            else:
                print("Result: ⚠️ Price kept going. Could have held longer?")
    else:
        print("Result: No post-exit data available.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python verify_bulletproof_trades.py <log_file> <trade_id1> <trade_id2> ...")
        sys.exit(1)
        
    log_path = sys.argv[1]
    trade_ids = sys.argv[2:]
    
    with open(log_path, 'r') as f:
        content = f.readlines()
        
    for tid in trade_ids:
        analyze_trade(content, tid)
