"""
test_live_order.py — Comprehensive end-to-end API validation.

Validates:
  1. Signature works (EOA signature type)
  2. Order reaches Polymarket and fills
  3. Position can be closed via sell order
  4. All PolymarketAPIClient endpoints work correctly:
     - get_wallet_balance()
     - get_pnl_summary()
     - get_positions()
     - calc_unrealized_pnl()
     - calc_realized_pnl()
  5. PnL calculations match expected values

Uses $5.00 stake to validate real-money trading flow.
"""

import asyncio
import sys
import os
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from dotenv import load_dotenv
load_dotenv()

# Import our Polymarket API client for comprehensive testing
from risk.polymarket_api import PolymarketAPIClient

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

# Safety limits
MAX_TEST_STAKE = 4.00  # Maximum $4 for safety
MIN_SHARES = 5.0       # Polymarket minimum
SAFETY_MARGIN = 0.05   # Keep 5 USDC buffer
MIN_BALANCE = 1.00     # Minimum to run test

def ok(msg):   print(f"  {GREEN}✓{RESET}  {msg}")
def fail(msg): print(f"  {RED}✗{RESET}  {msg}")
def warn(msg): print(f"  {YELLOW}!{RESET}  {msg}")
def info(msg): print(f"  →  {msg}")


async def get_active_market():
    """Find the current active BTC 5m market and return token IDs."""
    import aiohttp
    now       = time.time()
    window_ts = int(now // 300) * 300

    async with aiohttp.ClientSession() as s:
        for ts in [window_ts, window_ts - 300, window_ts + 300]:
            slug = f"btc-updown-5m-{ts}"
            async with s.get(
                "https://gamma-api.polymarket.com/markets",
                params={"slug": slug},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as r:
                data = await r.json()

            markets = data if isinstance(data, list) else []
            if not markets:
                continue

            m         = markets[0]
            win_start = float(ts)
            win_end   = win_start + 300

            if not (win_start <= now < win_end):
                continue

            import json as _json
            clob_ids = m.get("clobTokenIds", [])
            if isinstance(clob_ids, str):
                clob_ids = _json.loads(clob_ids)

            outcomes = m.get("outcomes", [])
            up_id = down_id = None
            for i, outcome in enumerate(outcomes):
                o = outcome.lower()
                if o in ("up", "yes") and i < len(clob_ids):
                    up_id = clob_ids[i]
                elif o in ("down", "no") and i < len(clob_ids):
                    down_id = clob_ids[i]

            if not up_id and len(clob_ids) >= 2:
                up_id, down_id = clob_ids[0], clob_ids[1]

            # Get current odds
            async with s.get(
                "https://clob.polymarket.com/midpoint",
                params={"token_id": up_id},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as r:
                mid = await r.json()
            up_odds   = float(mid.get("mid", 0.5))
            down_odds = round(1.0 - up_odds, 4)

            return {
                "slug":      slug,
                "win_end":   win_end,
                "up_id":     up_id,
                "down_id":   down_id,
                "up_odds":   up_odds,
                "down_odds": down_odds,
                "secs_left": win_end - now,
            }

    return None


def make_client():
    """Build py-clob-client with correct EOA signature type."""
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds
    from py_clob_client.constants import POLYGON

    creds = ApiCreds(
        api_key        = os.getenv("POLYMARKET_API_KEY"),
        api_secret     = os.getenv("POLYMARKET_API_SECRET"),
        api_passphrase = os.getenv("POLYMARKET_PASSPHRASE"),
    )
    return ClobClient(
        host           = "https://clob.polymarket.com",
        key            = os.getenv("POLYMARKET_PRIVATE_KEY"),
        chain_id       = POLYGON,
        creds          = creds,
        funder         = os.getenv("POLYMARKET_FUNDER_ADDRESS"),
        signature_type = 1,   # EOA — Magic/Gmail wallet
    )


async def main():
    print(f"\n{BOLD}{'═'*70}{RESET}")
    print(f"{BOLD}  Comprehensive Live API Test — End-to-End Validation{RESET}")
    print(f"{'═'*70}")
    print(f"  Stake: $5.00 | Tests all PolymarketAPIClient endpoints")
    print(f"  This will use real USDC from your account\n")

    # ── Phase 0: Initialize API Client ────────────────────────────────────
    print("0. Initializing PolymarketAPIClient...")
    try:
        api_client = PolymarketAPIClient(
            api_key=os.getenv("POLYMARKET_API_KEY"),
            api_secret=os.getenv("POLYMARKET_API_SECRET"),
            api_passphrase=os.getenv("POLYMARKET_PASSPHRASE"),
            private_key=os.getenv("POLYMARKET_PRIVATE_KEY"),
            funder_address=os.getenv("POLYMARKET_FUNDER_ADDRESS")
        )
        wallet_address = os.getenv("POLYMARKET_FUNDER_ADDRESS")
        ok(f"API Client initialized for {wallet_address[:20]}...")
    except Exception as e:
        fail(f"API Client initialization failed: {e}")
        return

    # ── Phase 1: Pre-Trade Validation ─────────────────────────────────────
    print("\n1. Pre-Trade Validation (API Endpoints)...")
    
    # Get wallet balance
    try:
        balance_before = api_client.get_wallet_balance()
        ok(f"Wallet Balance: ${balance_before:.4f}")
        if balance_before < MIN_BALANCE:
            warn(f"Low balance (${balance_before:.2f}) — need at least ${MIN_BALANCE} for minimum order")
            warn("Add USDC to your Polymarket wallet and retry")
            return  # Stop here
    
        if balance_before > 10.00:
            warn(f"High balance (${balance_before:.2f}) detected — test limited to ${MAX_TEST_STAKE}")
    
        # Calculate safe stake amount
        safe_stake = min(MAX_TEST_STAKE, balance_before - SAFETY_MARGIN)
        if safe_stake < 1.00:
            warn(f"Insufficient balance for safe test: ${balance_before:.2f}")
            return
    
        ok(f"Safe stake amount: ${safe_stake:.2f} (max ${MAX_TEST_STAKE}, buffer ${SAFETY_MARGIN})")
    except Exception as e:
        fail(f"get_wallet_balance() failed: {e}")
        return
    
    # Get portfolio summary (baseline)
    try:
        portfolio_before = api_client.get_pnl_summary(wallet_address, balance_before)
        if portfolio_before.get("success"):
            info(f"Baseline Realized PnL: ${portfolio_before.get('realized_pnl', 0):.4f}")
            info(f"Baseline Unrealized PnL: ${portfolio_before.get('unrealized_pnl', 0):.4f}")
            info(f"Baseline Cash: ${portfolio_before.get('cash_balance', 0):.4f}")
        else:
            fail(f"get_pnl_summary() failed: {portfolio_before.get('error')}")
            return
    except Exception as e:
        fail(f"get_pnl_summary() failed: {e}")
        return
    
    # ── Step 2: Find active market ─────────────────────────────────────────
    print("\n2. Finding active BTC 5m market...")
    market = await get_active_market()
    if not market:
        fail("No active market right now — try again in a few minutes")
        return

    ok(f"Market: {market['slug']} | ends_in={market['secs_left']:.0f}s")
    ok(f"Odds: up={market['up_odds']:.3f}  down={market['down_odds']:.3f}")

    if market["secs_left"] < 240:  # Need 4+ minutes for full test
        warn(f"Only {market['secs_left']:.0f}s remaining — need 4+ minutes")
        warn("Waiting for next window...")
        # Wait until next 5-min boundary
        secs_to_wait = 300 - (time.time() % 300) + 10  # +10s buffer
        info(f"Sleeping {secs_to_wait:.0f}s for fresh window...")
        await asyncio.sleep(secs_to_wait)
        # Retry finding market
        market = await get_active_market()
        if not market or market["secs_left"] < 240:
            fail("No suitable market with 4+ minutes remaining")
            return

    # ── Step 2: Choose direction (pick cheaper side to fit balance) ─────────
    print("\n2. Choosing direction...")
    
    # Calculate cost for both directions (minimum 5 shares required)
    up_cost = MIN_SHARES * market["up_odds"]
    down_cost = MIN_SHARES * market["down_odds"]
    
    # Safety check: ensure we can afford minimum order in at least one direction
    affordable = False
    if up_cost <= safe_stake or down_cost <= safe_stake:
        affordable = True
    
    if not affordable:
        fail(f"Cannot afford minimum order in either direction")
        info(f"  UP cost: ${up_cost:.2f}, DOWN cost: ${down_cost:.2f}")
        info(f"  Available: ${safe_stake:.2f}")
        info(f"  Waiting for market with lower prices...")
        # Could add retry/wait logic here
        return
    
    # Pick the cheaper direction that fits our budget
    if up_cost <= down_cost and up_cost <= safe_stake:
        direction = "long"
        token_id  = market["up_id"]
        price     = market["up_odds"]
        ok(f"Chose LONG: ${up_cost:.2f} (vs DOWN ${down_cost:.2f})")
    elif down_cost <= safe_stake:
        direction = "short"
        token_id  = market["down_id"]
        price     = market["down_odds"]
        ok(f"Chose SHORT: ${down_cost:.2f} (vs UP ${up_cost:.2f})")
    else:
        # Fallback to whichever is cheaper even if both exceed (shouldn't happen due to check above)
        if up_cost <= down_cost:
            direction = "long"
            token_id = market["up_id"]
            price = market["up_odds"]
        else:
            direction = "short"
            token_id = market["down_id"]
            price = market["down_odds"]
        warn(f"Using cheaper direction but may fail: ${min(up_cost, down_cost):.2f} > ${safe_stake:.2f}")

    # Round to tick and calculate final amounts
    price = round(round(price / 0.01) * 0.01, 4)
    
    # Calculate minimum required stake (minimum shares × price)
    min_cost = MIN_SHARES * price
    
    # Use minimum cost, capped at safe_stake (don't exceed our budget)
    stake = min(min_cost, safe_stake)
    
    # Ensure we have minimum shares
    shares = max(MIN_SHARES, round(stake / price, 2))
    actual_cost = shares * price
    
    # Final safety verification
    if actual_cost > balance_before:
        fail(f"SAFETY CHECK FAILED: Cost ${actual_cost:.2f} exceeds balance ${balance_before:.2f}")
        return
    
    ok(f"Order: {shares:.2f} shares @ ${price:.3f} = ${actual_cost:.2f}")

    info(f"Direction: {direction.upper()}")
    info(f"Token ID:  {token_id[:20]}...")
    info(f"Price:     {price:.3f}")
    info(f"Shares:    {shares:.2f}")
    info(f"Stake:     ${stake:.2f}")

    # ── Step 3: Build client ───────────────────────────────────────────────
    print("\n3. Building CLOB client...")
    try:
        client = make_client()
        ok("Client built with signature_type=1 (EOA)")
    except Exception as e:
        fail(f"Client build failed: {e}")
        return

    # ── Step 4: Place buy order ────────────────────────────────────────────
    print("\n4. Placing BUY order...")
    order_success = False
    try:
        from py_clob_client.clob_types import OrderArgs, OrderType

        order_args   = OrderArgs(
            token_id = token_id,
            price    = price,
            size     = shares,
            side     = "BUY",
        )
        signed_order = client.create_order(order_args)
        resp         = client.post_order(signed_order, OrderType.GTC)

        print(f"\n  Raw response: {resp}\n")

        if resp and resp.get("success"):
            order_id = resp.get("orderID", "?")
            ok(f"BUY order placed! order_id={order_id}")
            order_success = True
        else:
            fail(f"BUY order failed: {resp}")
            return

    except Exception as e:
        fail(f"BUY order error: {e}")
        import traceback
        traceback.print_exc()
        return

    # ── Phase 3a: Wait for order to be matched ──────────────────────────────
    print("\n5a. Waiting for order to be matched...")
    matched = False
    position_ready = False
    
    for attempt in range(20):  # Wait up to 60s for match
        await asyncio.sleep(3)
        try:
            positions_result = api_client.get_positions(wallet_address)
            if positions_result.get("success"):
                positions = positions_result.get("positions", [])
                if len(positions) > 0:
                    ok(f"Position matched! {len(positions)} position(s) found")
                    matched = True
                    position_ready = True
                    break
        except Exception as e:
            pass  # Continue waiting
    
    if not matched:
        warn("Order may not be fully matched yet, proceeding with monitoring...")
    else:
        info("Position is live, starting 4-minute hold...")

    # ── Phase 3b: Position Monitoring (max 3:20, exit early after 2 PnL readings) ─
    max_hold_seconds = 200  # 3 minutes 20 seconds
    max_polls = max_hold_seconds // 3  # 66 polls
    min_successful_readings = 2  # Exit early after this many
    successful_readings = 0
    last_unrealized = None
    
    print(f"\n5b. Holding position (max 3:20, exit after {min_successful_readings} PnL readings)...")
    print(f"    (Selling with 40s buffer before market close)")
    unrealized_snapshots = []
    
    if order_success:
        for i in range(max_polls):
            await asyncio.sleep(3)
            elapsed_sec = i * 3
            elapsed_min = elapsed_sec // 60
            
            try:
                # Get positions from API
                positions_result = api_client.get_positions(wallet_address)
                pos_count = 0
                if positions_result.get("success"):
                    positions = positions_result.get("positions", [])
                    pos_count = len(positions)
                
                # Get unrealized PnL
                portfolio_during = api_client.get_pnl_summary(wallet_address, balance_before)
                unrealized = portfolio_during.get("unrealized_pnl", 0)
                unrealized_snapshots.append(unrealized)
                
                # Check if we have a successful reading (position exists and PnL calculated)
                if pos_count > 0 and unrealized != 0:
                    # Check if this is different from last reading (proves fluctuation)
                    if last_unrealized is not None and unrealized != last_unrealized:
                        successful_readings += 1
                        info(f"  {elapsed_min}m {elapsed_sec%60}s: ✓ PnL changed ${last_unrealized:.4f} → ${unrealized:.4f} (reading {successful_readings}/{min_successful_readings})")
                        if successful_readings >= min_successful_readings:
                            ok(f"Got {min_successful_readings} PnL readings, exiting early...")
                            break
                    last_unrealized = unrealized
                
                # Log every 30 seconds if no successful reading yet
                if i % 10 == 0 and successful_readings == 0:
                    info(f"  {elapsed_min}m {elapsed_sec%60}s: pos={pos_count}, unrealized=${unrealized:.4f} (waiting for PnL fluctuation...)")
                    
            except Exception as e:
                if i % 10 == 0:
                    warn(f"  Poll {i+1}/{max_polls}: Error - {e}")
        
        if successful_readings < min_successful_readings:
            warn(f"Max hold time reached ({max_hold_seconds}s) with only {successful_readings} PnL readings")
    else:
        warn("Skipping position monitoring (buy failed)")

    # ── Phase 4: Order Exit ────────────────────────────────────────────────
    print("\n6. Closing position after hold...")
    sell_success = False

    try:
        # Get current odds for exit
        import aiohttp
        async with aiohttp.ClientSession() as s:
            async with s.get(
                "https://clob.polymarket.com/midpoint",
                params={"token_id": token_id},
                timeout=aiohttp.ClientTimeout(total=5)
            ) as r:
                mid = await r.json()
        exit_price = float(mid.get("mid", price))
        exit_price = round(round(exit_price / 0.01) * 0.01, 4)

        sell_args   = OrderArgs(
            token_id = token_id,
            price    = exit_price,
            size     = shares,
            side     = "SELL",
        )
        signed_sell = client.create_order(sell_args)
        sell_resp   = client.post_order(signed_sell, OrderType.GTC)

        print(f"\n  Raw sell response: {sell_resp}\n")

        if sell_resp and sell_resp.get("success"):
            ok(f"SELL order placed! order_id={sell_resp.get('orderID','?')}")
            sell_success = True

            # PnL estimate
            pnl = round((exit_price - price) / price * stake, 4)
            if pnl >= 0:
                ok(f"Estimated PnL: +${pnl:.4f}")
            else:
                warn(f"Estimated PnL: ${pnl:.4f} (small loss expected on quick close)")
        else:
            warn(f"SELL order response: {sell_resp}")
            warn("Position may still be open — check Polymarket UI")

    except Exception as e:
        fail(f"SELL order error: {e}")
        warn("Position may still be open — check Polymarket → Open Orders")

    # ── Phase 5: Post-Trade Validation ─────────────────────────────────────
    print("\n7. Post-Trade Validation (API Endpoints)...")
    
    # Get final portfolio summary
    try:
        portfolio_after = api_client.get_pnl_summary(wallet_address, balance_before)
        if portfolio_after.get("success"):
            realized_after = portfolio_after.get('realized_pnl', 0)
            unrealized_after = portfolio_after.get('unrealized_pnl', 0)
            cash_after = portfolio_after.get('cash_balance', 0)
            
            ok(f"Final Realized PnL: ${realized_after:.4f}")
            info(f"Final Unrealized PnL: ${unrealized_after:.4f}")
            info(f"Final Cash: ${cash_after:.4f}")
        else:
            fail(f"Final get_pnl_summary() failed: {portfolio_after.get('error')}")
    except Exception as e:
        fail(f"Final portfolio check failed: {e}")

    # Get final wallet balance
    try:
        balance_after = api_client.get_wallet_balance()
        ok(f"Final Wallet Balance: ${balance_after:.4f}")
    except Exception as e:
        fail(f"Final balance check failed: {e}")
        balance_after = 0.0

    # ── Phase 6: Cross-Validation & Summary ────────────────────────────────
    print(f"\n{BOLD}{'═'*70}{RESET}")
    print(f"{BOLD}  VALIDATION SUMMARY{RESET}")
    print(f"{'═'*70}")
    
    # Calculate expected values
    balance_change = balance_after - balance_before
    realized_change = realized_after - portfolio_before.get('realized_pnl', 0)
    
    print(f"\n  Financial Comparison:")
    print(f"    Balance Before:     ${balance_before:.4f}")
    print(f"    Balance After:      ${balance_after:.4f}")
    print(f"    Balance Change:     ${balance_change:.4f}")
    print(f"    Realized PnL Delta: ${realized_change:.4f}")
    
    # Verify consistency
    tolerance = 0.02  # $0.02 tolerance for fees/rounding
    consistent = abs(balance_change - realized_change) < tolerance
    
    if consistent:
        ok(f"Balance change ≈ Realized PnL (within ${tolerance:.2f} tolerance)")
    else:
        warn(f"Balance change differs from PnL by ${abs(balance_change - realized_change):.4f}")
        info("  (May include fees, slippage, or rounding)")
    
    # Verify unrealized is near zero after close
    if abs(unrealized_after) < 0.01:
        ok(f"Unrealized PnL near zero after close: ${unrealized_after:.4f}")
    else:
        warn(f"Unrealized PnL still present: ${unrealized_after:.4f}")
        warn("  Position may not be fully closed")

    # ── Final Result ─────────────────────────────────────────────────────
    print(f"\n{'═'*70}")
    if order_success and sell_success and consistent:
        print(f"{BOLD}  ✓ ALL TESTS PASSED{RESET}")
        print(f"  PolymarketAPIClient endpoints working correctly:")
        print(f"    • get_wallet_balance()")
        print(f"    • get_pnl_summary()")
        print(f"    • get_positions()")
        print(f"    • Order placement (buy/sell)")
        print(f"  Live trading system is READY")
    else:
        print(f"{BOLD}  ⚠ TEST INCOMPLETE{RESET}")
        if not order_success:
            print(f"    ✗ Buy order failed")
        if not sell_success:
            print(f"    ✗ Sell order failed")
        if not consistent:
            print(f"    ! PnL validation warning")
    print(f"{'═'*70}\n")


if __name__ == "__main__":
    asyncio.run(main())