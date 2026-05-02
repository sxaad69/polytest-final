import re
import glob
from collections import defaultdict

LOG_PATH = "/home/ubuntu/polytest-final/logs/open_positions.log*"

def run_trailing_simulator():
    # trade_id -> list of {'source': str, 'price': float} chronological
    trade_curves = defaultdict(list)
    trade_entries = {}
    
    log_files = glob.glob(LOG_PATH)
    
    # Regexes
    # Active HB: [HEARTBEAT] [Bot G] Trade #259 (sol-updown-5m) | Conf: 0.0560 | Entry: 0.770 | Internal: 0.820
    hb_pattern = re.compile(r"\[HEARTBEAT\].*?Trade #(\d+).*?Entry:\s*([0-9.]+).*?Internal:\s*([0-9.]+)")
    # Post-Exit HB: [POST-EXIT HB] [Bot G] Trade #244 (SOL-long) | Entry: 0.760 | Closed at: 0.840 (profit_ratchet_exit) | Current: 0.990
    post_hb_pattern = re.compile(r"\[POST-EXIT HB\].*?Trade #(\d+).*?Entry:\s*([0-9.]+).*?Current:\s*([0-9.]+)")

    print("Parsing heartbeats to reconstruct full 5-minute price curves...")

    for file in sorted(log_files): # Sort to try to keep chronological, though timestamps are better
        try:
            with open(file, 'r') as f:
                for line in f:
                    # Active
                    match = hb_pattern.search(line)
                    if match:
                        t_id = int(match.group(1))
                        if t_id < 220: continue
                        entry = float(match.group(2))
                        price = float(match.group(3))
                        trade_entries[t_id] = entry
                        trade_curves[t_id].append(price)
                        continue
                        
                    # Post-Exit
                    match = post_hb_pattern.search(line)
                    if match:
                        t_id = int(match.group(1))
                        if t_id < 220: continue
                        entry = float(match.group(2))
                        price = float(match.group(3))
                        trade_entries[t_id] = entry
                        trade_curves[t_id].append(price)
                        
        except Exception as e:
            pass

    print(f"Reconstructed full market curves for {len(trade_curves)} trades.")

    # Simulation Function
    def simulate_strategy(hard_sl, activation, trail_delta):
        net_pnl = 0.0
        winners = 0
        losers = 0
        
        for t_id, prices in trade_curves.items():
            entry = trade_entries[t_id]
            peak = entry
            closed = False
            pnl = 0.0
            
            for price in prices:
                # Update Peak
                if price > peak:
                    peak = price
                    
                gain = price - entry
                peak_gain = peak - entry
                
                # 1. Hard SL Check
                if gain <= -hard_sl:
                    pnl = -hard_sl
                    closed = True
                    break
                    
                # 2. Trailing Stop Check
                if peak_gain >= activation:
                    stop_target = peak - trail_delta
                    # Minimum safe exit (breakeven + small buffer)
                    stop_target = max(stop_target, entry + 0.005)
                    
                    if price <= stop_target:
                        # Exited via Trailing Stop
                        pnl = stop_target - entry
                        closed = True
                        break
            
            # 3. Hard Stop (Window Expired)
            if not closed:
                # Forced liquidation at the final known price
                final_price = prices[-1]
                pnl = final_price - entry
                
            net_pnl += pnl
            if pnl > 0: winners += 1
            else: losers += 1
            
        return net_pnl, winners, losers

    print("\n=== TRAILING STOP SIMULATIONS (Hard SL locked at 0.05) ===")
    
    scenarios = [
        {"act": 0.10, "trail": 0.10, "name": "Current Baseline"},
        {"act": 0.10, "trail": 0.15, "name": "Wider Trail (Let Winners Run)"},
        {"act": 0.15, "trail": 0.10, "name": "Late Activation, Tight Trail"},
        {"act": 0.15, "trail": 0.15, "name": "Late Activation, Wide Trail"},
        {"act": 0.05, "trail": 0.05, "name": "Early Activation, Super Tight"},
        {"act": 0.10, "trail": 0.20, "name": "Maximum Breathing Room"},
    ]

    for s in scenarios:
        pnl, wins, loss = simulate_strategy(hard_sl=0.05, activation=s['act'], trail_delta=s['trail'])
        print(f"[{s['name']}] Act: {s['act']}, Trail: {s['trail']}  =>  Net PnL: {pnl:+.3f}  (Wins: {wins}, Loss: {loss})")

if __name__ == "__main__":
    run_trailing_simulator()
