import sqlite3
import re
import os
from datetime import datetime

LOG_FILE = "logs/open_positions.log"
DB_FILE = "data/bot_g_paper.db"

def parse_logs():
    trades_in_logs = {}
    
    if not os.path.exists(LOG_FILE):
        print(f"Log file {LOG_FILE} not found.")
        return {}
        
    with open(LOG_FILE, 'r') as f:
        for line in f:
            # Parse [EXIT] lines
            if "[EXIT]" in line:
                match = re.search(r"Trade #(\d+) \| (.*?) \| Current Price: ([\d.]+) \| Executed Polymarket Limit Fill: ([\d.]+)", line)
                if match:
                    trade_id = int(match.group(1))
                    reason = match.group(2)
                    current_price = float(match.group(3))
                    fill_price = float(match.group(4))
                    
                    if trade_id not in trades_in_logs:
                        trades_in_logs[trade_id] = {"heartbeats": [], "exit": None}
                    
                    trades_in_logs[trade_id]["exit"] = {
                        "reason": reason,
                        "current_price": current_price,
                        "fill_price": fill_price,
                        "timestamp": line[:23]
                    }
                    
            # Parse [HEARTBEAT] lines
            elif "[HEARTBEAT]" in line:
                match = re.search(r"Trade #(\d+) \((.*?)\) \| Conf: ([\d.-]+) \| Entry: ([\d.]+) \| Internal: ([\d.]+) \| RATCHET: (.*?) \| Hard SL: ([\d.]+)", line)
                if match:
                    trade_id = int(match.group(1))
                    slug = match.group(2)
                    conf = float(match.group(3))
                    entry = float(match.group(4))
                    internal_price = float(match.group(5))
                    ratchet = match.group(6)
                    hard_sl = float(match.group(7))
                    
                    if trade_id not in trades_in_logs:
                        trades_in_logs[trade_id] = {"heartbeats": [], "exit": None}
                    
                    trades_in_logs[trade_id]["heartbeats"].append({
                        "slug": slug,
                        "internal_price": internal_price,
                        "timestamp": line[:23]
                    })
                    
    return trades_in_logs

def check_db(log_data):
    if not os.path.exists(DB_FILE):
        print(f"DB file {DB_FILE} not found.")
        return
        
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    print("\n" + "="*80)
    print(f"{'TRADE RECONCILIATION REPORT':^80}")
    print("="*80)
    print(f"{'ID':<6} | {'Slug':<25} | {'Status':<10} | {'Log Exit':<15} | {'DB Exit':<15} | {'Diff'}")
    print("-"*80)
    
    for trade_id, data in sorted(log_data.items()):
        cursor.execute("SELECT * FROM trades WHERE id = ?", (trade_id,))
        db_row = cursor.fetchone()
        
        slug = data["heartbeats"][0]["slug"] if data["heartbeats"] else "Unknown"
        
        if not db_row:
            status = "MISSING_IN_DB"
            log_exit = data["exit"]["fill_price"] if data["exit"] else "N/A"
            print(f"{trade_id:<6} | {slug:<25} | {status:<10} | {log_exit:<15} | {'N/A':<15} | !!!")
            continue
            
        db_exit_price = db_row["exit_odds"]
        log_exit_price = data["exit"]["fill_price"] if data["exit"] else None
        
        status = "MATCH"
        if data["exit"] and not db_row["resolved"]:
            status = "DB_UNRESOLVED"
        elif not data["exit"] and db_row["resolved"]:
            status = "LOG_MISSING_EXIT"
        elif log_exit_price and db_exit_price and abs(log_exit_price - db_exit_price) > 0.001:
            status = "PRICE_MISMATCH"
            
        log_exit_str = f"{log_exit_price:.3f}" if log_exit_price else "N/A"
        db_exit_str = f"{db_exit_price:.3f}" if db_exit_price else "N/A"
        
        diff = ""
        if status != "MATCH":
            diff = "!!!"
            
        print(f"{trade_id:<6} | {slug:<25} | {status:<10} | {log_exit_str:<15} | {db_exit_str:<15} | {diff}")

    conn.close()

if __name__ == "__main__":
    log_data = parse_logs()
    check_db(log_data)
