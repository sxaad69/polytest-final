import sqlite3
import pandas as pd
from tabulate import tabulate
import json

DB_G = "/home/ubuntu/polytest/data/bot_g_paper.db"

def run_analysis():
    conn = sqlite3.connect(DB_G)
    
    # 1. Load data
    trades = pd.read_sql_query("""
        SELECT 
            t.id, t.ts_entry, t.window_end, t.direction, t.entry_odds, 
            t.exit_reason, t.outcome, t.pnl_usdc, t.slug,
            s.confidence_score, s.momentum_30s, s.rsi, s.volume_zscore, s.features_json
        FROM trades t
        LEFT JOIN signals s ON t.signal_id = s.id
        WHERE t.resolved = 1
    """, conn)
    conn.close()

    if trades.empty:
        print("No resolved trades found for Bot G.")
        return

    # 2. Preprocess
    trades['ts_dt'] = pd.to_datetime(trades['ts_entry'])
    trades['hour_utc'] = trades['ts_dt'].dt.hour
    trades['win_end_dt'] = pd.to_datetime(trades['window_end'])
    trades['secs_remaining'] = (trades['win_end_dt'] - trades['ts_dt']).dt.total_seconds()
    
    # Extract asset from slug (e.g. "btc-updown-5m-1711324800")
    trades['asset'] = trades['slug'].apply(lambda x: x.split('-')[0].upper() if isinstance(x, str) else 'UNKNOWN')

    def get_stats(df, group_col):
        if df.empty: return pd.DataFrame()
        res = df.groupby(group_col).agg(
            trades=('id', 'count'),
            wins=('outcome', lambda x: (x == 'win').sum()),
            pnl=('pnl_usdc', 'sum'),
            expectancy=('pnl_usdc', 'mean')
        ).reset_index()
        res['win_rate'] = (res['wins'] / res['trades'] * 100).round(1)
        res['pnl'] = res['pnl'].round(2)
        res['expectancy'] = res['expectancy'].round(4)
        return res[['filter' if 'filter' in res.columns else group_col, 'trades', 'win_rate', 'pnl', 'expectancy']]

    print("\n=== Bot G: Overall Stats ===")
    total_trades = len(trades)
    total_wins = (trades['outcome'] == 'win').sum()
    total_pnl = trades['pnl_usdc'].sum()
    print(f"Total Trades: {total_trades}")
    print(f"Win Rate:     {round(total_wins/total_trades*100, 1) if total_trades > 0 else 0}%")
    print(f"Total PnL:    ${round(total_pnl, 2)}")
    print(f"Expectancy:   ${round(total_pnl/total_trades, 4) if total_trades > 0 else 0}")

    print("\n=== Bot G: Performance by Asset ===")
    asset_stats = get_stats(trades, 'asset')
    print(tabulate(asset_stats.sort_values('pnl', ascending=False), headers='keys', tablefmt='psql', showindex=False))

    print("\n=== Bot G: Hourly Performance (UTC) ===")
    hourly = get_stats(trades, 'hour_utc')
    print(tabulate(hourly.sort_values('expectancy', ascending=False), headers='keys', tablefmt='psql', showindex=False))

    print("\n=== Bot G: Directional Bias by Asset ===")
    dir_asset = trades.groupby(['asset', 'direction']).agg(
        trades=('id', 'count'),
        wins=('outcome', lambda x: (x == 'win').sum()),
        pnl=('pnl_usdc', 'sum')
    ).reset_index()
    dir_asset['win_rate'] = (dir_asset['wins'] / dir_asset['trades'] * 100).round(1)
    print(tabulate(dir_asset.sort_values(['asset', 'pnl'], ascending=[True, False]), headers='keys', tablefmt='psql', showindex=False))

    print("\n=== Bot G: Odds Bucket Analysis ===")
    trades['odds_bucket'] = (trades['entry_odds'] * 10).round() / 10
    odds = get_stats(trades, 'odds_bucket')
    print(tabulate(odds, headers='keys', tablefmt='psql', showindex=False))

    print("\n=== Bot G: Entry Timing (Seconds Remaining) ===")
    trades['time_bucket'] = pd.cut(trades['secs_remaining'], bins=[0, 60, 120, 180, 240, 300, 999], labels=['<60s', '60-120s', '120-180s', '180-240s', '240-300s', '>300s'])
    timing = get_stats(trades, 'time_bucket')
    print(tabulate(timing, headers='keys', tablefmt='psql', showindex=False))

    print("\n=== Bot G: Exit Reason Analysis ===")
    exit_stats = get_stats(trades, 'exit_reason')
    print(tabulate(exit_stats, headers='keys', tablefmt='psql', showindex=False))

    print("\n=== Bot G: Momentum (30s) Analysis ===")
    trades['mom_bucket'] = pd.cut(trades['momentum_30s'], bins=[-999, -0.05, -0.02, 0, 0.02, 0.05, 999])
    mom = get_stats(trades, 'mom_bucket')
    print(tabulate(mom, headers='keys', tablefmt='psql', showindex=False))

    print("\n=== Bot G: Confidence Score Analysis ===")
    trades['conf_bucket'] = pd.cut(trades['confidence_score'], bins=[0, 0.03, 0.05, 0.08, 0.12, 1.0])
    conf = get_stats(trades, 'conf_bucket')
    print(tabulate(conf, headers='keys', tablefmt='psql', showindex=False))

    # Cumulative PnL for Drawdown Analysis
    trades = trades.sort_values('ts_dt')
    trades['cum_pnl'] = trades['pnl_usdc'].cumsum()
    trades['bankroll'] = 100 + trades['cum_pnl']
    print(f"\nMax Drawdown: ${round(100 - trades['bankroll'].min(), 2)} (Lowest Bankroll: ${round(trades['bankroll'].min(), 2)})")
    print(f"Max Bankroll: ${round(trades['bankroll'].max(), 2)}")
    print(f"Final Bankroll: ${round(trades['bankroll'].iloc[-1], 2)}")

if __name__ == "__main__":
    run_analysis()
