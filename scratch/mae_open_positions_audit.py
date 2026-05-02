import re
import glob

LOG_PATH = "/home/ubuntu/polytest-final/logs/open_positions.log*"

def run_open_positions_audit(sl_threshold=0.05):
    # Dict to store: trade_id -> {'entry': float, 'min_price': float, 'max_price': float, 'exit_reason': str, 'asset': str, 'closed': bool}
    trades = {}
    
    log_files = glob.glob(LOG_PATH)
    
    # We only care about prices while the trade is ACTIVE. 
    # [HEARTBEAT] means active. [POST-EXIT HB] means the trade is already over.
    hb_pattern = re.compile(r"\[HEARTBEAT\] \[Bot G\] Trade #(\d+)\s*\(([^)]+)\).*?Entry:\s*([0-9.]+).*?(?:Internal|Current):\s*([0-9.]+)")
    exit_pattern = re.compile(r"Closed at:\s*[0-9.]+\s*\(([^)]+)\)")

    for file in log_files:
        try:
            with open(file, 'r') as f:
                for line in f:
                    if "Trade #" not in line:
                        continue
                        
                    # First, check if it's an exit log to record the result and MARK AS CLOSED
                    exit_match = exit_pattern.search(line)
                    is_post_exit = "[POST-EXIT HB]" in line
                    
                    # Extract Trade ID to mark it closed if it's an exit log
                    t_match = re.search(r"Trade #(\d+)", line)
                    if not t_match: continue
                    trade_id = int(t_match.group(1))
                    
                    if trade_id < 220:
                        continue
                        
                    if trade_id not in trades:
                        trades[trade_id] = {
                            'id': trade_id,
                            'asset': 'UNKNOWN',
                            'entry': 0.0,
                            'min_price': 99.0,
                            'max_price': 0.0,
                            'exit_reason': 'unknown',
                            'closed': False
                        }
                    
                    if exit_match:
                        trades[trade_id]['exit_reason'] = exit_match.group(1)
                        trades[trade_id]['closed'] = True
                    elif is_post_exit:
                        trades[trade_id]['closed'] = True

                    # ONLY extract price pain if the trade is still actively open!
                    if not trades[trade_id]['closed']:
                        match = hb_pattern.search(line)
                        if match:
                            asset_str = match.group(2)
                            entry = float(match.group(3))
                            current_val = float(match.group(4))
                            
                            trades[trade_id]['asset'] = asset_str.split('-')[0].upper()
                            trades[trade_id]['entry'] = entry
                            
                            if current_val < trades[trade_id]['min_price']:
                                trades[trade_id]['min_price'] = current_val
                            if current_val > trades[trade_id]['max_price']:
                                trades[trade_id]['max_price'] = current_val

        except Exception as e:
            print(f"Error reading {file}: {e}")

    if not trades:
        print("No trades found in open_positions.log matching criteria.")
        return

    winners_analyzed = 0
    losers_analyzed = 0
    killed_winners = []
    saved_losses = []

    print(f"\n--- TRUE MAE AUDIT (ACTIVE TRADES ONLY) (SL: {sl_threshold}) ---")
    
    for t_id, data in sorted(trades.items()):
        if data['exit_reason'] == 'unknown' or data['min_price'] == 99.0:
            continue
            
        pain = data['entry'] - data['min_price']
        survived = pain < sl_threshold
        
        is_winner = 'ratchet' in data['exit_reason'].lower()
        
        if is_winner:
            winners_analyzed += 1
            if not survived:
                killed_winners.append(data)
        else:
            losers_analyzed += 1
            if pain >= sl_threshold:
                saved_losses.append(data)

    print(f"Total Success Trades Analyzed: {winners_analyzed}")
    print(f"Successes that would be KILLED by {sl_threshold} SL: {len(killed_winners)}")
    if killed_winners:
        for kw in killed_winners:
            pain_val = kw['entry'] - kw['min_price']
            print(f"  #{kw['id']} {kw['asset']}: Dipped to {kw['min_price']} (Pain: {pain_val:.3f}) before winning.")
            
    print(f"\nTotal Losers Analyzed: {losers_analyzed}")
    print(f"Losses that would be CUT SOONER: {len(saved_losses)}")
    if saved_losses:
        for sl in saved_losses:
            pain_val = sl['entry'] - sl['min_price']
            print(f"  #{sl['id']} {sl['asset']}: Reached pain of {pain_val:.3f}. Could have saved money.")

if __name__ == "__main__":
    import sys
    t = 0.05
    if len(sys.argv) > 1: t = float(sys.argv[1])
    run_open_positions_audit(t)
