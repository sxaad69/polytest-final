import csv
import os
import sys
from collections import defaultdict
from datetime import datetime

# --- CONFIG PARAMETERS (Mirroring config.py) ---
MIN_CONFIDENCE = 0.05
MIN_ENTRY_ODDS = 0.35
MAX_ENTRY_ODDS = 0.75
MIN_SECS_REMAINING = 60
SLIPPAGE = 0.03

HARD_SL_DELTA = 0.05
RATCHET_ACTIVATION_GAIN = 0.05
TRAILING_STOP_DELTA = 0.05

def parse_tape(file_path):
    print(f"Loading tape data from {file_path}...")
    if not os.path.exists(file_path):
        print(f"Error: {file_path} not found.")
        return []
    
    ticks = []
    with open(file_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                dt = datetime.strptime(row['timestamp'], "%Y-%m-%d %H:%M:%S.%f")
                ts = dt.timestamp()
                
                ticks.append({
                    'ts': ts,
                    'timestamp_str': row['timestamp'],
                    'slug': row['market_slug'],
                    'asset': row['asset'],
                    'mid': float(row['poly_mid']),
                    'mom': float(row['binance_mom'])
                })
            except Exception as e:
                pass
    
    # Sort by timestamp to ensure chronological order
    ticks.sort(key=lambda x: x['ts'])
    print(f"Loaded {len(ticks)} ticks.")
    return ticks

def run_simulation(ticks):
    print("\n--- SIMULATION RESULTS ---")
    
    # Track which markets we've already entered
    entered_markets = set()
    trades = []
    
    # Group ticks by market for post-analysis
    market_ticks = defaultdict(list)
    for t in ticks:
        market_ticks[t['slug']].append(t)
    
    # Step 1: Find Entries
    for t in ticks:
        slug = t['slug']
        if slug in entered_markets:
            continue  # Only one trade per market
            
        # Parse window end from slug
        try:
            parts = slug.split('-')
            window_start = int(parts[-1])
            window_end = window_start + 300  # 5m markets
        except:
            continue
            
        secs_remaining = window_end - t['ts']
        if secs_remaining < MIN_SECS_REMAINING:
            continue
            
        # Check odds bounds
        if t['mid'] < MIN_ENTRY_ODDS or t['mid'] > MAX_ENTRY_ODDS:
            continue
            
        # Check confidence (momentum)
        mom = t['mom']
        if abs(mom) < MIN_CONFIDENCE:
            continue
            
        # Entry Triggered!
        direction = "LONG" if mom >= MIN_CONFIDENCE else "SHORT"
        
        # Calculate entry price with slippage
        if direction == "LONG":
            entry_price = min(0.98, t['mid'] + SLIPPAGE)
        else:
            entry_price = min(0.98, (1.0 - t['mid']) + SLIPPAGE)
            
        trade = {
            'slug': slug,
            'asset': t['asset'],
            'direction': direction,
            'entry_time': t['ts'],
            'entry_str': t['timestamp_str'],
            'entry_price': round(entry_price, 4),
            'raw_mid': t['mid'],
            'mom': mom,
            'status': 'OPEN',
            'exit_price': None,
            'exit_reason': None,
            'pnl': 0.0,
            'peak_val': entry_price
        }
        
        trades.append(trade)
        entered_markets.add(slug)

    print(f"Found {len(trades)} valid entries.\n")

    # Step 2: Post-Analysis (Simulate the trade lifecycle)
    total_pnl = 0.0
    wins = 0
    losses = 0

    for trade in trades:
        slug = trade['slug']
        entry_time = trade['entry_time']
        direction = trade['direction']
        entry_price = trade['entry_price']
        
        # Get all ticks for this market AFTER the entry time
        future_ticks = [t for t in market_ticks[slug] if t['ts'] > entry_time]
        
        peak_val = entry_price
        ratchet_active = False
        trailing_stop = 0.0
        hard_sl = entry_price - HARD_SL_DELTA
        
        for t in future_ticks:
            # Calculate current value of position
            if direction == "LONG":
                current_val = t['mid']
            else:
                current_val = 1.0 - t['mid']
                
            # Update peak
            if current_val > peak_val:
                peak_val = current_val
                
            # Check Ratchet Activation
            if not ratchet_active and current_val >= entry_price + RATCHET_ACTIVATION_GAIN:
                ratchet_active = True
                
            # Update Trailing Stop if Ratchet is active
            if ratchet_active:
                new_trailing_stop = peak_val - TRAILING_STOP_DELTA
                if new_trailing_stop > trailing_stop:
                    trailing_stop = new_trailing_stop
                    
            # 1. Check Trailing Stop hit
            if ratchet_active and current_val <= trailing_stop:
                trade['status'] = 'CLOSED'
                trade['exit_price'] = trailing_stop
                trade['exit_reason'] = 'profit_ratchet_exit'
                break
                
            # 2. Check Hard Stop Loss hit
            if current_val <= hard_sl:
                trade['status'] = 'CLOSED'
                trade['exit_price'] = hard_sl
                trade['exit_reason'] = 'hard_sl_hit'
                break
                
        # If the market window closed without hitting a stop, close at final value
        if trade['status'] == 'OPEN':
            if len(future_ticks) > 0:
                final_tick = future_ticks[-1]
                final_val = final_tick['mid'] if direction == "LONG" else (1.0 - final_tick['mid'])
                trade['exit_price'] = final_val
                trade['exit_reason'] = 'market_close'
            else:
                trade['exit_price'] = entry_price
                trade['exit_reason'] = 'no_data'
            trade['status'] = 'CLOSED'
            
        trade['pnl'] = trade['exit_price'] - entry_price
        total_pnl += trade['pnl']
        if trade['pnl'] > 0:
            wins += 1
        else:
            losses += 1
            
        print(f"[{trade['entry_str']}] {trade['asset']} {trade['direction']} | "
              f"Entry: {trade['entry_price']:.3f} | Exit: {trade['exit_price']:.3f} | "
              f"PnL: {trade['pnl']:+.3f} | Reason: {trade['exit_reason']}")

    # Summary
    print("\n--- FINAL SUMMARY ---")
    print(f"Total Trades: {len(trades)}")
    if len(trades) > 0:
        win_rate = (wins / len(trades)) * 100
        print(f"Wins: {wins} | Losses: {losses} | Win Rate: {win_rate:.1f}%")
        print(f"Total Net PnL (per share): {total_pnl:+.3f} USDC")

if __name__ == "__main__":
    # Ensure the file path targets the downloaded file 14
    file_path = "logs/market_tape_2026-05-01_16.csv"
    ticks = parse_tape(file_path)
    if ticks:
        run_simulation(ticks)
