import re
import glob

LOG_PATH = "/home/ubuntu/polytest-final/logs/open_positions.log*"

def run_pnl_simulator():
    trades = {}
    log_files = glob.glob(LOG_PATH)
    
    hb_pattern = re.compile(r"\[HEARTBEAT\] \[Bot G\] Trade #(\d+).*?Entry:\s*([0-9.]+).*?(?:Internal|Current):\s*([0-9.]+)")
    exit_pattern = re.compile(r"Closed at:\s*([0-9.]+)\s*\(([^)]+)\)")
    entry_pattern = re.compile(r"Trade #(\d+)\s*\(([^)]+)\).*?Entry:\s*([0-9.]+)")

    for file in log_files:
        try:
            with open(file, 'r') as f:
                for line in f:
                    t_match = re.search(r"Trade #(\d+)", line)
                    if not t_match: continue
                    trade_id = int(t_match.group(1))
                    
                    if trade_id < 220:
                        continue
                        
                    if trade_id not in trades:
                        trades[trade_id] = {
                            'id': trade_id,
                            'entry': 0.0,
                            'closed_at': 0.0,
                            'min_price': 99.0,
                            'exit_reason': 'unknown',
                            'closed': False
                        }
                    
                    if trades[trade_id]['entry'] == 0.0:
                        em = entry_pattern.search(line)
                        if em: trades[trade_id]['entry'] = float(em.group(3))

                    exit_match = exit_pattern.search(line)
                    is_post_exit = "[POST-EXIT HB]" in line
                    
                    if exit_match:
                        trades[trade_id]['closed_at'] = float(exit_match.group(1))
                        trades[trade_id]['exit_reason'] = exit_match.group(2)
                        trades[trade_id]['closed'] = True
                    elif is_post_exit:
                        trades[trade_id]['closed'] = True

                    if not trades[trade_id]['closed']:
                        hb_match = hb_pattern.search(line)
                        if hb_match:
                            current_val = float(hb_match.group(3))
                            if current_val < trades[trade_id]['min_price']:
                                trades[trade_id]['min_price'] = current_val

        except Exception as e:
            pass

    real_pnl_total = 0.0
    hypo_03_pnl_total = 0.0
    hypo_05_pnl_total = 0.0
    hypo_10_pnl_total = 0.0
    
    analyzed_trades = 0

    print("=== ULTIMATE PNL SIMULATION RESULTS ===")
    
    for t_id, data in sorted(trades.items()):
        if data['exit_reason'] == 'unknown' or data['min_price'] == 99.0 or data['entry'] == 0.0:
            continue
            
        analyzed_trades += 1
        
        entry = data['entry']
        closed_at = data['closed_at']
        min_price = data['min_price']
        
        real_pnl = closed_at - entry
        real_pnl_total += real_pnl
        
        pain = entry - min_price
        
        # Hypo 0.03
        if pain >= 0.03:
            hypo_03_pnl = -0.03
        else:
            hypo_03_pnl = real_pnl
        hypo_03_pnl_total += hypo_03_pnl
        
        # Hypo 0.05
        if pain >= 0.05:
            hypo_05_pnl = -0.05
        else:
            hypo_05_pnl = real_pnl
        hypo_05_pnl_total += hypo_05_pnl
        
        # Hypo 0.10
        if pain >= 0.10:
            hypo_10_pnl = -0.10
        else:
            hypo_10_pnl = real_pnl
        hypo_10_pnl_total += hypo_10_pnl

    print(f"Total Trades Analyzed: {analyzed_trades}")
    print(f"\nREALITY (0.15 SL):")
    print(f"Net PnL: {real_pnl_total:+.3f}")
    
    print(f"\nHYPOTHETICAL (0.10 SL):")
    print(f"Net PnL: {hypo_10_pnl_total:+.3f} (Diff: {hypo_10_pnl_total - real_pnl_total:+.3f})")

    print(f"\nHYPOTHETICAL (0.05 SL):")
    print(f"Net PnL: {hypo_05_pnl_total:+.3f} (Diff: {hypo_05_pnl_total - real_pnl_total:+.3f})")
    
    print(f"\nHYPOTHETICAL (0.03 SL):")
    print(f"Net PnL: {hypo_03_pnl_total:+.3f} (Diff: {hypo_03_pnl_total - real_pnl_total:+.3f})")

if __name__ == "__main__":
    run_pnl_simulator()
