import sqlite3
import pandas as pd
from tabulate import tabulate

DB_B = "/home/ubuntu/polytest/data/bot_b_paper.db"

def run_analysis():
    conn = sqlite3.connect(DB_B)
    query = "SELECT t.id, t.ts_entry, t.direction, t.pnl_usdc, t.outcome, t.exit_reason FROM trades t WHERE t.resolved = 1"
    trades = pd.read_sql_query(query, conn)
    conn.close()

    if trades.empty:
        print("No trades found.")
        return

    total_trades = len(trades)
    total_wins = (trades['outcome'] == 'win').sum()
    total_pnl = trades['pnl_usdc'].sum()
    
    print(f"Total Trades: {total_trades}")
    print(f"Win Rate:     {round(total_wins/total_trades*100, 1)}%")
    print(f"Total PnL:    ${round(total_pnl, 2)}")
    print(f"Expectancy:   ${round(total_pnl/total_trades, 4) if total_trades > 0 else 0}")

    # Directional
    dir_stats = trades.groupby('direction').agg(
        trades=('id', 'count'),
        wins=('outcome', lambda x: (x == 'win').sum()),
        pnl=('pnl_usdc', 'sum')
    ).reset_index()
    dir_stats['win_rate'] = (dir_stats['wins'] / dir_stats['trades'] * 100).round(1)
    print("\n=== Directional ===")
    print(tabulate(dir_stats, headers='keys', tablefmt='psql'))

    # Exit Reason
    exit_stats = trades.groupby('exit_reason').agg(
        trades=('id', 'count'),
        pnl=('pnl_usdc', 'sum')
    ).reset_index()
    print("\n=== Exit Reason ===")
    print(tabulate(exit_stats, headers='keys', tablefmt='psql'))

if __name__ == "__main__":
    run_analysis()
