#!/usr/bin/env python3
"""
Emergency Liquidation Script
Closes all open positions immediately for all active bots.

Usage:
    python emergency_liquidate.py --dry-run          # Preview only
    python emergency_liquidate.py --execute          # Actually close all
    python emergency_liquidate.py --execute --bots A B   # Close specific bots
"""

import sys
import asyncio
import argparse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from feeds.polymarket import PolymarketFeed
from database.db import Database
from config import (
    BOT_G_DB_PATH, BOT_A_DB_PATH, BOT_B_DB_PATH,
    POLYMARKET_API_KEY, POLYMARKET_API_SECRET, POLYMARKET_PASSPHRASE,
    POLYMARKET_PRIVATE_KEY, POLYMARKET_FUNDER_ADDRESS,
    PAPER_TRADING
)

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
DB_PATHS = {
    'A': BOT_A_DB_PATH,
    'B': BOT_B_DB_PATH,
    'G': BOT_G_DB_PATH,
}

MAX_RETRIES       = 3       # retry partial fills this many times
RETRY_DISCOUNT    = 0.02    # lower price by 2¢ each retry to force fill
ORDER_DELAY       = 0.4     # seconds between orders (rate limit safety)
PARTIAL_THRESHOLD = 0.01    # treat as fully filled if remainder < 1¢ in shares


# ══════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def shares_from_trade(trade: dict) -> float:
    """
    Calculate number of shares held from a trade record.
    shares = stake_usdc / entry_price (entry_odds)
    Falls back to stake if entry_odds missing (best effort).
    """
    stake      = float(trade.get('stake_usdc', 0))
    entry_odds = float(trade.get('entry_odds') or 0)

    if entry_odds > 0:
        return stake / entry_odds

    # Fallback: if shares were stored directly
    if trade.get('shares'):
        return float(trade['shares'])

    # Last resort: use stake as shares (will be wrong — log a warning)
    print(f"  [WARN] Trade #{trade['id']}: No entry_odds found, using stake as shares. Check your DB schema.")
    return stake


async def get_best_bid(feed: PolymarketFeed, token_id: str) -> float | None:
    """
    Fetch the current best bid price for a token from the order book.
    We sell at the best bid to guarantee an immediate fill (taker order).
    Returns None if order book is empty or fetch fails.
    """
    try:
        book = await feed.get_order_book(token_id)
        # Expected structure: {'bids': [{'price': '0.82', 'size': '100'}, ...], 'asks': [...]}
        bids = book.get('bids', [])
        if not bids:
            return None
        # Bids are sorted best-first by most APIs; take the top one
        best = max(bids, key=lambda b: float(b['price']))
        return float(best['price'])
    except Exception as e:
        print(f"  [WARN] Could not fetch order book for {token_id[:20]}: {e}")
        return None


async def close_single_trade(
    feed: PolymarketFeed,
    db: Database,
    trade: dict,
    bot_id: str,
    dry_run: bool,
) -> str:
    """
    Attempts to fully close a single open trade.

    Returns one of: 'closed', 'partial', 'failed', 'skipped'
    """
    trade_id   = trade['id']
    token_id   = trade.get('token_id')
    direction  = trade.get('direction', 'BUY')
    stake      = float(trade.get('stake_usdc', 0))
    entry_odds = float(trade.get('entry_odds') or 0.5)

    if not token_id:
        print(f"  [SKIP] Trade #{trade_id}: Missing token_id in DB")
        return 'skipped'

    shares_to_sell = shares_from_trade(trade)

    if shares_to_sell <= PARTIAL_THRESHOLD:
        print(f"  [SKIP] Trade #{trade_id}: Position too small ({shares_to_sell:.4f} shares)")
        return 'skipped'

    if dry_run:
        print(f"  [DRY RUN] Trade #{trade_id}: Would sell {shares_to_sell:.4f} shares | token {token_id[:20]}...")
        return 'skipped'

    # ── Fetch best bid ──────────────────────────────────────────
    best_bid = await get_best_bid(feed, token_id)

    if best_bid is None:
        # No buyers in book — use a very low fallback to force a market sell
        # This means you accept whatever is available
        best_bid = 0.01
        print(f"  [WARN] Trade #{trade_id}: Empty order book, using fallback price 0.01")

    # ── Retry loop for partial fills ────────────────────────────
    remaining_shares = shares_to_sell
    total_filled     = 0.0
    total_revenue    = 0.0
    final_price      = best_bid
    attempt          = 0
    status           = 'failed'

    while remaining_shares > PARTIAL_THRESHOLD and attempt < MAX_RETRIES:
        attempt += 1
        sell_price = max(0.01, final_price - (RETRY_DISCOUNT * (attempt - 1)))

        print(f"  [ATTEMPT {attempt}] Trade #{trade_id}: Selling {remaining_shares:.4f} shares @ {sell_price:.4f}")

        try:
            order = await feed.place_order(
                direction="sell",
                token_id=token_id,
                size=remaining_shares,
                price=sell_price,
                bot_id=bot_id,
                paper=PAPER_TRADING,
            )
        except Exception as e:
            print(f"  [ERROR] Trade #{trade_id} attempt {attempt}: {e}")
            await asyncio.sleep(ORDER_DELAY)
            continue

        order_status   = order.get('status', '')
        filled_size    = float(order.get('filled_size', 0) or order.get('size_matched', 0))
        filled_price   = float(order.get('filled_price', sell_price) or sell_price)

        if order_status == 'filled':
            total_filled  += filled_size or remaining_shares
            total_revenue += (filled_size or remaining_shares) * filled_price
            remaining_shares = 0
            final_price      = filled_price
            status           = 'closed'
            print(f"  [FILLED] Trade #{trade_id}: {total_filled:.4f} shares @ {filled_price:.4f}")
            break

        elif order_status in ('partial', 'partially_filled'):
            total_filled     += filled_size
            total_revenue    += filled_size * filled_price
            remaining_shares -= filled_size
            final_price       = filled_price
            print(f"  [PARTIAL] Trade #{trade_id}: {filled_size:.4f} filled, {remaining_shares:.4f} remaining")
            await asyncio.sleep(ORDER_DELAY)

        else:
            print(f"  [REJECTED] Trade #{trade_id} attempt {attempt}: {order.get('reason', 'unknown')}")
            # Lower the price and try again
            final_price = sell_price
            await asyncio.sleep(ORDER_DELAY)

    # ── Determine final status ──────────────────────────────────
    if remaining_shares <= PARTIAL_THRESHOLD:
        status = 'closed'
    elif total_filled > 0:
        status = 'partial'
    else:
        status = 'failed'

    # ── Log exit in DB if anything was filled ───────────────────
    if total_filled > 0:
        avg_exit_price = total_revenue / total_filled if total_filled > 0 else final_price

        db.log_exit(trade_id, {
            'ts_exit':        now_iso(),
            'entry_odds':     entry_odds,
            'exit_odds':      avg_exit_price,
            'peak_odds':      trade.get('peak_odds', entry_odds),
            'stake_usdc':     stake,
            'exit_reason':    f'emergency_liquidation_{status}',
            'chainlink_close': None,
        })

        pnl = (avg_exit_price - entry_odds) * total_filled
        pnl_str = f"+${pnl:.4f}" if pnl >= 0 else f"-${abs(pnl):.4f}"
        print(f"  [{status.upper()}] Trade #{trade_id}: avg exit {avg_exit_price:.4f} | P&L {pnl_str}")

    return status


# ══════════════════════════════════════════════
# BOT LIQUIDATION
# ══════════════════════════════════════════════

async def liquidate_bot(bot_id: str, db_path: str, dry_run: bool = False) -> dict:
    """Close all open positions for a single bot. Returns result summary."""
    print(f"\n{'═'*52}")
    print(f"  Bot {bot_id} — Emergency Liquidation")
    print(f"{'═'*52}")

    db = Database(db_path, bot_id)
    open_trades = db.open_trades()

    if not open_trades:
        print(f"  No open positions for Bot {bot_id}")
        return {'closed': 0, 'partial': 0, 'failed': 0, 'skipped': 0}

    print(f"  Found {len(open_trades)} open position(s):\n")
    for t in open_trades:
        shares = shares_from_trade(t)
        print(
            f"    Trade #{t['id']}: "
            f"{t.get('direction','?')} | "
            f"${t.get('stake_usdc', 0):.2f} | "
            f"{shares:.4f} shares | "
            f"{str(t.get('market_id',''))[:24]}..."
        )

    results = {'closed': 0, 'partial': 0, 'failed': 0, 'skipped': 0}

    if dry_run:
        print(f"\n  [DRY RUN] Would attempt to close {len(open_trades)} position(s).")
        print(f"  Run with --execute to actually close.\n")
        results['skipped'] = len(open_trades)
        return results

    feed = PolymarketFeed()

    async with feed:
        for i, trade in enumerate(open_trades):
            print()
            outcome = await close_single_trade(feed, db, trade, bot_id, dry_run=False)
            results[outcome] = results.get(outcome, 0) + 1

            # Delay between orders to avoid rate limiting
            if i < len(open_trades) - 1:
                await asyncio.sleep(ORDER_DELAY)

    print(f"\n  Bot {bot_id} — Done: "
          f"{results['closed']} closed | "
          f"{results['partial']} partial | "
          f"{results['failed']} failed | "
          f"{results['skipped']} skipped")

    return results


# ══════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════

async def main():
    parser = argparse.ArgumentParser(description='Emergency liquidation — closes all open Polymarket positions')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--dry-run',  action='store_true', help='Preview positions without closing')
    mode.add_argument('--execute',  action='store_true', help='Actually close all positions NOW')
    parser.add_argument('--bots', nargs='+', choices=['A', 'B', 'G', 'all'],
                        default=['all'], help='Which bots to liquidate (default: all)')
    args = parser.parse_args()

    bots = ['A', 'B', 'G'] if 'all' in args.bots else args.bots

    print("╔══════════════════════════════════════════════════╗")
    print("║        EMERGENCY LIQUIDATION SCRIPT              ║")
    print("╚══════════════════════════════════════════════════╝")
    print(f"  Mode          : {'⚠  DRY RUN — no orders placed' if args.dry_run else '🔴 LIVE — orders will be placed'}")
    print(f"  Bots          : {', '.join(bots)}")
    print(f"  Paper Trading : {PAPER_TRADING}")
    print(f"  Started       : {now_iso()}")

    # Run all bots — sequentially to avoid overwhelming the API
    # Switch to asyncio.gather() if you need parallel execution
    totals = {'closed': 0, 'partial': 0, 'failed': 0, 'skipped': 0}

    for bot_id in bots:
        db_path = DB_PATHS.get(bot_id)

        if not db_path:
            print(f"\n[SKIP] Bot {bot_id}: No DB path configured")
            continue

        if not Path(db_path).exists():
            print(f"\n[SKIP] Bot {bot_id}: Database not found at {db_path}")
            continue

        result = await liquidate_bot(bot_id, db_path, dry_run=args.dry_run)

        for key in totals:
            totals[key] += result.get(key, 0)

    # ── Final summary ─────────────────────────────────────────
    print(f"\n{'═'*52}")
    print(f"  FINAL SUMMARY")
    print(f"{'═'*52}")
    print(f"  ✅ Closed   : {totals['closed']}")
    print(f"  ⚠️  Partial  : {totals['partial']}")
    print(f"  ❌ Failed   : {totals['failed']}")
    print(f"  ⏭️  Skipped  : {totals['skipped']}")
    print(f"{'═'*52}")

    if totals['partial'] > 0:
        print(f"\n  ⚠️  WARNING: {totals['partial']} position(s) only partially closed.")
        print(f"  Re-run --execute to attempt closing the remainder.")

    if totals['failed'] > 0:
        print(f"\n  ❌ {totals['failed']} position(s) could not be closed.")
        print(f"  Check logs above and close manually if needed.")

    if args.dry_run:
        print(f"\n  To actually close, run:")
        print(f"  python emergency_liquidate.py --execute\n")

    return 0 if totals['failed'] == 0 else 1


if __name__ == "__main__":
    exit(asyncio.run(main()))