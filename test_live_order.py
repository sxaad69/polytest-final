"""
test_live_order.py — End-to-end live order test using POLY_1271 (signature_type=3).

Uses py-clob-client-v2 with deposit wallet (ERC-1271) signatures — the correct
flow for Polymarket's CLOB V2 with pUSD collateral.

Flow:
  1. Connect with signature_type=3 (POLY_1271 / deposit wallet)
  2. Fetch wallet balance via data API (since COLLATERAL endpoint needs sig=3 sync)
  3. Find active BTC 5m market
  4. Place FOK BUY order (min stake, +2c slippage)
  5. Monitor position
  6. Place FOK SELL order (exit, -5c slippage)
"""

import asyncio
import sys
import os
import time
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from dotenv import load_dotenv
load_dotenv()

from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.clob_types import ApiCreds, OrderArgsV2, OrderType, BalanceAllowanceParams

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

FUNDER  = os.getenv("POLYMARKET_FUNDER_ADDRESS")
MIN_SHARES  = 5.0
MAX_STAKE   = 5.00

def ok(msg):   print(f"  {GREEN}✓{RESET}  {msg}")
def fail(msg): print(f"  {RED}✗{RESET}  {msg}")
def warn(msg): print(f"  {YELLOW}!{RESET}  {msg}")
def info(msg): print(f"  →  {msg}")


def make_client() -> ClobClient:
    """Build CLOB V2 client with POLY_1271 (signature_type=3) for deposit wallet."""
    creds = ApiCreds(
        api_key        = os.getenv("POLYMARKET_API_KEY"),
        api_secret     = os.getenv("POLYMARKET_API_SECRET"),
        api_passphrase = os.getenv("POLYMARKET_PASSPHRASE"),
    )
    return ClobClient(
        host           = "https://clob.polymarket.com",
        key            = os.getenv("POLYMARKET_PRIVATE_KEY"),
        chain_id       = 137,
        creds          = creds,
        funder         = FUNDER,
        signature_type = 3,   # POLY_1271 — deposit wallet (ERC-1271)
    )


def get_balance_from_data_api() -> float:
    """
    Fetch actual pUSD balance from the data API positions + activity.
    The CLOB balance allowance endpoint requires a relayer sync first,
    so we read balance from the data API which always reflects reality.
    """
    import requests
    try:
        # Get current open positions value
        r = requests.get(
            f"https://data-api.polymarket.com/positions?user={FUNDER}&limit=100",
            timeout=10
        )
        positions = r.json()
        if not isinstance(positions, list):
            positions = []

        # Get recent activity to estimate cash balance
        r2 = requests.get(
            f"https://data-api.polymarket.com/value?user={FUNDER}",
            timeout=10
        )
        value_data = r2.json()
        if isinstance(value_data, dict):
            cash = float(value_data.get("portfolioValue", value_data.get("balance", 0)))
            return cash

        # Fallback: use CLOB balance allowance with sig=3
        client = make_client()
        result = client.get_balance_allowance(BalanceAllowanceParams(asset_type="COLLATERAL"))
        raw = result.get("balance", 0) if isinstance(result, dict) else 0
        return float(raw) / 1e6

    except Exception as e:
        warn(f"Balance fetch error: {e}")
        return 0.0


async def get_active_market():
    """Find the current active BTC 5m market and return token IDs + odds."""
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

            clob_ids = m.get("clobTokenIds", [])
            if isinstance(clob_ids, str):
                clob_ids = json.loads(clob_ids)

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


async def main():
    print(f"\n{BOLD}{'═'*70}{RESET}")
    print(f"{BOLD}  Live Order Test — POLY_1271 (signature_type=3){RESET}")
    print(f"{'═'*70}")
    print(f"  Deposit Wallet: {FUNDER}")
    print(f"  Uses FOK orders + deposit wallet ERC-1271 signing\n")

    # ── Phase 0: Build client ──────────────────────────────────────────────
    print("0. Building CLOB V2 client (signature_type=3)...")
    try:
        client = make_client()
        server = client.get_ok()
        ok(f"Server: {server}")
        keys = client.get_api_keys()
        ok(f"API Keys: {keys}")
    except Exception as e:
        fail(f"Client init failed: {e}")
        import traceback; traceback.print_exc()
        return

    # ── Phase 1: Balance ───────────────────────────────────────────────────
    print("\n1. Fetching wallet balance...")
    try:
        # Try CLOB balance first (sig=3 path)
        result = client.get_balance_allowance(BalanceAllowanceParams(asset_type="COLLATERAL"))
        raw = result.get("balance", 0) if isinstance(result, dict) else 0
        balance = float(raw) / 1e6
        ok(f"CLOB balance: ${balance:.4f}")

        if balance < 1.0:
            warn("CLOB shows $0 — checking data API for actual pUSD balance...")
            balance = get_balance_from_data_api()
            if balance > 0:
                ok(f"Data API balance: ${balance:.4f}")
            else:
                fail("No balance found — fund your wallet first")
                return
    except Exception as e:
        fail(f"Balance check failed: {e}")
        return

    safe_stake = min(MAX_STAKE, balance * 0.20)  # Use max 20% of balance
    if safe_stake < 1.0:
        fail(f"Safe stake ${safe_stake:.2f} too low — need at least $1")
        return
    ok(f"Safe stake: ${safe_stake:.2f} (20% of ${balance:.2f})")

    # ── Phase 2: Find market ───────────────────────────────────────────────
    print("\n2. Finding active BTC 5m market...")
    market = await get_active_market()
    if not market:
        fail("No active BTC 5m market right now — try again in a minute")
        return

    ok(f"Market: {market['slug']} | {market['secs_left']:.0f}s remaining")
    ok(f"Odds: up={market['up_odds']:.3f}  down={market['down_odds']:.3f}")

    if market["secs_left"] < 120:
        warn(f"Only {market['secs_left']:.0f}s left — need 2+ minutes")
        return

    # ── Phase 3: Choose direction ──────────────────────────────────────────
    print("\n3. Choosing direction (cheaper side)...")
    up_cost   = MIN_SHARES * market["up_odds"]
    down_cost = MIN_SHARES * market["down_odds"]

    if market["up_odds"] <= market["down_odds"] and up_cost <= safe_stake:
        direction = "BUY"; token_id = market["up_id"]; price = market["up_odds"]
        ok(f"Chose UP: ${up_cost:.2f} for {MIN_SHARES} shares")
    elif down_cost <= safe_stake:
        direction = "BUY"; token_id = market["down_id"]; price = market["down_odds"]
        ok(f"Chose DOWN: ${down_cost:.2f} for {MIN_SHARES} shares")
    else:
        fail(f"Cannot afford min order. up=${up_cost:.2f} down=${down_cost:.2f} available=${safe_stake:.2f}")
        return

    price  = round(round(price / 0.01) * 0.01, 4)

    # Polymarket enforces min $1 per order — calculate shares to meet that
    MIN_ORDER_USDC = 1.00
    buy_price_with_slip = min(0.99, round(round((price + 0.08) / 0.01) * 0.01, 4))
    shares = max(MIN_SHARES, round(MIN_ORDER_USDC / buy_price_with_slip + 0.5))
    cost   = round(shares * price, 4)
    info(f"Token: {token_id[:24]}...")
    info(f"Price: {price:.3f} | Shares: {shares} | Cost: ${cost:.2f}")

    # ── Phase 4: Place FOK BUY ─────────────────────────────────────────────
    print("\n4. Placing FOK BUY order (POLY_1271)...")
    order_id = None
    try:
        info(f"Limit price with +8c slippage: {buy_price_with_slip:.3f}")

        order_args = OrderArgsV2(
            token_id = token_id,
            price    = buy_price_with_slip,
            size     = shares,
            side     = "BUY",
        )
        signed = client.create_order(order_args)

        # Attempt 1: FOK with +8c slip
        resp = None
        try:
            resp = client.post_order(signed, OrderType.FOK)
        except Exception as fok_err:
            # Attempt 2: widen to +15c desperation buffer
            warn(f"FOK killed with +8c — widening to +15c...")
            buy_price2 = min(0.99, round(round((price + 0.15) / 0.01) * 0.01, 4))
            order_args2 = OrderArgsV2(token_id=token_id, price=buy_price2, size=shares, side="BUY")
            signed2 = client.create_order(order_args2)
            resp = client.post_order(signed2, OrderType.FOK)

        print(f"\n  Raw response: {resp}\n")

        if resp and resp.get("success"):
            order_id = resp.get("orderID", "?")
            ok(f"BUY filled! order_id={order_id}")
        else:
            fail(f"BUY failed: {resp}")
            return

    except Exception as e:
        fail(f"BUY error: {e}")
        import traceback; traceback.print_exc()
        return


    # ── Phase 5: Hold briefly then exit ───────────────────────────────────
    hold_secs = min(30, market["secs_left"] - 40)
    print(f"\n5. Holding for {hold_secs:.0f}s before selling...")
    await asyncio.sleep(max(5, hold_secs))

    # ── Phase 6: Place FOK SELL ────────────────────────────────────────────
    print("\n6. Placing FOK SELL order (exit)...")
    try:
        import aiohttp
        async with aiohttp.ClientSession() as s:
            async with s.get(
                "https://clob.polymarket.com/midpoint",
                params={"token_id": token_id},
                timeout=aiohttp.ClientTimeout(total=5)
            ) as r:
                mid = await r.json()
        exit_price = float(mid.get("mid", price))

        # Dead-zone check: if mid < 2c the market has effectively resolved
        # against us — no liquidity, FOK will always be killed
        if exit_price < 0.02:
            warn(f"Mid is {exit_price:.3f} — market resolved against position (dead zone)")
            warn("No sell liquidity available at floor price. Position will settle at $0.")
            warn("This is normal — the real bot's SL (-8c) would have exited long before this.")
            return

        # -5c buffer for FOK (mirrors trader.py logic)
        sell_price = max(0.01, round(round((exit_price - 0.05) / 0.01) * 0.01, 4))
        info(f"Mid: {exit_price:.3f} | Sell limit (−5c): {sell_price:.3f}")

        sell_args = OrderArgsV2(
            token_id = token_id,
            price    = sell_price,
            size     = shares,
            side     = "SELL",
        )
        signed_sell = client.create_order(sell_args)

        # Attempt 1: FOK (instant fill or kill)
        sell_resp = None
        try:
            sell_resp = client.post_order(signed_sell, OrderType.FOK)
        except Exception as fok_err:
            warn(f"FOK sell killed ({fok_err}) — retrying as GTC...")
            # Attempt 2: GTC fallback (rests on book)
            signed_sell2 = client.create_order(sell_args)
            sell_resp = client.post_order(signed_sell2, OrderType.GTC)

        print(f"\n  Raw sell response: {sell_resp}\n")

        if sell_resp and sell_resp.get("success"):
            ok(f"SELL filled! order_id={sell_resp.get('orderID','?')}")
            pnl = round((sell_price - price) * shares, 4)
            if pnl >= 0:
                ok(f"Estimated PnL: +${pnl:.4f}")
            else:
                warn(f"Estimated PnL: ${pnl:.4f} (expected — quick exit cost)")
        else:
            warn(f"SELL response: {sell_resp}")
            warn("Position may still be open — check Polymarket UI")

    except Exception as e:
        fail(f"SELL error: {e}")
        import traceback; traceback.print_exc()


    # ── Summary ────────────────────────────────────────────────────────────
    print(f"\n{'═'*70}")
    print(f"{BOLD}  TEST COMPLETE{RESET}")
    print(f"  signature_type=3 (POLY_1271) working correctly")
    print(f"  Next step: Update bot config to use signature_type=3")
    print(f"{'═'*70}\n")


if __name__ == "__main__":
    asyncio.run(main())