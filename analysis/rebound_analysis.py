import sqlite3
import os

DB_PATH = "data/aws/bot_sniper_paper_2026-05-05.db"

def run_analysis():
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Total trades
    cursor.execute("SELECT COUNT(*) FROM trades")
    total_trades = cursor.fetchone()[0]

    # Trades that ended in a loss
    cursor.execute("SELECT COUNT(*) FROM trades WHERE pnl_usdc < 0")
    total_losses = cursor.fetchone()[0]

    # Rebound winners: Loss trades where peak_odds reached a winning level
    # We define "winning level" as peak_odds >= entry_odds + 0.10 (a significant move)
    # or just peak_odds > entry_odds (any profit potential)
    
    query = """
    SELECT 
        id, asset, entry_odds, peak_odds, exit_odds, pnl_usdc, exit_reason
    FROM trades 
    WHERE pnl_usdc < 0 AND peak_odds > entry_odds
    ORDER BY (peak_odds - entry_odds) DESC
    """
    cursor.execute(query)
    rebound_trades = cursor.fetchall()

    print("="*60)
    print(f"SNIPER REBOUND ANALYSIS (May 5-6)")
    print("="*60)
    print(f"Total Trades:      {total_trades}")
    print(f"Total Losses:      {total_losses}")
    print(f"Rebound Winners:   {len(rebound_trades)} (Losses that hit profit levels first)")
    print(f"Recovery Rate:     {len(rebound_trades)/total_losses*100:.2f}% of losses had profit potential")
    print("-"*60)
    print(f"{'ID':<5} {'Asset':<6} {'Entry':<6} {'Peak':<6} {'Exit':<6} {'PnL':<8} {'Reason'}")
    print("-"*60)

    for t in rebound_trades[:20]: # Show top 20 biggest missed opportunities
        tid, asset, entry, peak, exit_val, pnl, reason = t
        gain = peak - entry
        print(f"{tid:<5} {asset:<6} {entry:<6.3f} {peak:<6.3f} {exit_val:<6.3f} {pnl:<8.3f} {reason}")

    conn.close()

if __name__ == "__main__":
    run_analysis()
