"""
Truth Settler — Queries Gamma API for all unexited trades from last 2 hours,
marks confirmed LONG resolutions as exit_odds=1.0 and confirmed SHORT
resolutions as exit_odds=0.0 in the database, then prints full PnL.
"""
import sqlite3
import requests
import json
import os
from datetime import datetime

GAMMA_API = "https://gamma-api.polymarket.com"
DB_PATH   = "data/bot_sniper_paper.db"

def check_slugs(slugs):
    results = {}
    for slug in slugs:
        try:
            resp  = requests.get(f"{GAMMA_API}/events", params={"slug": slug}, timeout=10)
            data  = resp.json()
            if not data:
                results[slug] = "UNRESOLVED"
                continue
            market = data[0]["markets"][0]
            prices = json.loads(market.get("outcomePrices", "[0,0]"))
            if float(prices[0]) == 1.0:
                results[slug] = "LONG"
            elif float(prices[1]) == 1.0:
                results[slug] = "SHORT"
            else:
                results[slug] = "UNRESOLVED"
        except Exception:
            results[slug] = "ERROR"
    return results

def main():
    conn   = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur    = conn.cursor()

    # Pull all unexited trades from last 2 hours
    cur.execute("""
        SELECT id, asset, direction, entry_odds, stake_usdc, slug
        FROM trades
        WHERE exit_odds IS NULL
        AND ts_entry >= datetime('now', '-2 hours')
    """)
    trades = cur.fetchall()

    if not trades:
        print("No unexited trades found in last 2 hours.")
        conn.close()
        return

    slugs     = list(set(t["slug"] for t in trades if t["slug"]))
    print(f"Querying Gamma API for {len(slugs)} unique slugs...")
    truth_map = check_slugs(slugs)

    settled_wins  = []
    settled_loss  = []
    pending       = []

    for t in trades:
        result = truth_map.get(t["slug"], "UNRESOLVED")
        direction = t["direction"]  # "long" or "short"

        if result == "LONG":
            # Long resolved UP
            if direction == "long":
                exit_odds = 1.0   # full win
            else:
                exit_odds = 0.0   # short bet on wrong side → full loss
            cur.execute(
                "UPDATE trades SET exit_odds=?, exit_reason='truth_settled' WHERE id=?",
                (exit_odds, t["id"])
            )
            shares    = t["stake_usdc"] / t["entry_odds"]
            pnl       = (exit_odds * shares) - t["stake_usdc"]
            row       = dict(t) | {"exit_odds": exit_odds, "pnl": pnl, "truth": result}
            (settled_wins if direction == "long" else settled_loss).append(row)

        elif result == "SHORT":
            # Market resolved DOWN
            if direction == "short":
                exit_odds = 1.0   # short wins
            else:
                exit_odds = 0.0   # long bet on wrong side → full loss
            cur.execute(
                "UPDATE trades SET exit_odds=?, exit_reason='truth_settled' WHERE id=?",
                (exit_odds, t["id"])
            )
            shares    = t["stake_usdc"] / t["entry_odds"]
            pnl       = (exit_odds * shares) - t["stake_usdc"]
            row       = dict(t) | {"exit_odds": exit_odds, "pnl": pnl, "truth": result}
            (settled_wins if direction == "short" else settled_loss).append(row)

        else:
            pending.append(dict(t))

    conn.commit()

    # ── Full PnL (closed trades that were already in DB + newly settled)
    cur.execute("""
        SELECT 
            COUNT(*)                                                         AS total,
            ROUND(SUM((exit_odds/entry_odds)*stake_usdc - stake_usdc), 2)   AS net_pnl,
            ROUND(SUM(CASE WHEN exit_odds > entry_odds 
                THEN (exit_odds/entry_odds)*stake_usdc - stake_usdc 
                ELSE 0 END), 2)                                              AS gross_profit,
            ROUND(SUM(CASE WHEN exit_odds <= entry_odds 
                THEN (exit_odds/entry_odds)*stake_usdc - stake_usdc 
                ELSE 0 END), 2)                                              AS gross_loss,
            COUNT(CASE WHEN exit_odds > entry_odds THEN 1 END)               AS wins,
            COUNT(CASE WHEN exit_odds <= entry_odds THEN 1 END)              AS losses
        FROM trades
        WHERE ts_entry >= datetime('now', '-2 hours')
        AND   exit_odds IS NOT NULL
    """)
    row = cur.fetchone()
    conn.close()

    sep = "="*70
    print(f"\n{sep}")
    print(f"  FULL 2-HOUR PNL REPORT  —  {datetime.utcnow().isoformat()[:16]} UTC")
    print(sep)
    print(f"  Newly Settled (Truth)  : {len(settled_wins)} WINS  |  {len(settled_loss)} LOSSES")
    print(f"  Still Pending          : {len(pending)}")
    print(sep)
    print(f"  Total Closed Trades    : {row['total']}")
    print(f"  Trade Wins             : {row['wins']}")
    print(f"  Trade Losses           : {row['losses']}")
    print(f"  Gross Profit           : +${row['gross_profit']}")
    print(f"  Gross Loss             :  -${abs(row['gross_loss'])}")
    print(f"  NET PNL                :  {'+'if row['net_pnl']>=0 else ''}{row['net_pnl']} USD")
    print(sep)

    if settled_loss:
        print("\n  CONFIRMED LOSSES (Resolved SHORT):")
        print(f"  {'ID':<6} {'Asset':<6} {'Entry':<6} {'Stake':<7} {'PnL':<9} Slug")
        print("  " + "-"*65)
        for t in settled_loss:
            print(f"  {t['id']:<6} {t['asset']:<6} {t['entry_odds']:<6.3f} "
                  f"${t['stake_usdc']:<6.2f}  {t['pnl']:>+.2f}     {t['slug']}")

if __name__ == "__main__":
    main()
