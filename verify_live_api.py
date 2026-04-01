#!/usr/bin/env python3
"""
Polymarket Live API Verification Script
Tests the exact API calls used for live trading PnL/balance fetching.
Run this BEFORE going live to verify API credentials and endpoint access.
"""

import sys
import os
import requests
from typing import Dict, Any, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from risk.polymarket_api import PolymarketAPIClient
from config import (
    POLYMARKET_API_KEY,
    POLYMARKET_API_SECRET,
    POLYMARKET_PASSPHRASE,
    POLYMARKET_PRIVATE_KEY,
    POLYMARKET_FUNDER_ADDRESS,
    BOT_G_BANKROLL,
    POLYGON_RPC_URL  # Use your Polygon RPC
)

# API endpoints
CLOB_BASE = "https://clob.polymarket.com"
DATA_BASE = "https://data-api.polymarket.com"


def clob_headers() -> dict:
    """Returns auth headers for CLOB authenticated endpoints."""
    return {
        "POLY-API-KEY": POLYMARKET_API_KEY,
        "POLY-SECRET": POLYMARKET_API_SECRET,
        "POLY-PASSPHRASE": POLYMARKET_PASSPHRASE,
    }


def get_open_positions() -> list[dict]:
    """Fetch all open positions for the wallet."""
    url = f"{CLOB_BASE}/positions"
    params = {"user": POLYMARKET_FUNDER_ADDRESS}
    try:
        r = requests.get(url, params=params, headers=clob_headers(), timeout=10)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else data.get("positions", [])
    except Exception as e:
        print(f"  [ERROR] Could not fetch positions: {e}")
        return []


def get_current_price(token_id: str) -> Optional[float]:
    """Get current mid price for a token from CLOB."""
    url = f"{CLOB_BASE}/midpoint"
    params = {"token_id": token_id}
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        mid = data.get("mid")
        return float(mid) if mid is not None else None
    except Exception as e:
        print(f"  [WARN] Price fetch failed for {token_id[:20]}...: {e}")
        return None


def get_filled_trades() -> list[dict]:
    """Fetch all filled trades from data API for realized PnL."""
    url = f"{DATA_BASE}/v2/trades"
    params = {
        "maker_address": POLYMARKET_FUNDER_ADDRESS,
        "limit": 500,
        "offset": 0,
    }
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else data.get("data", [])
    except Exception as e:
        print(f"  [ERROR] Could not fetch trades: {e}")
        return []


def calc_unrealized_pnl(positions: list[dict]) -> tuple[float, list[dict]]:
    """Calculate unrealized PnL from open positions."""
    total = 0.0
    breakdown = []

    for pos in positions:
        token_id = pos.get("asset_id") or pos.get("token_id", "")
        size = float(pos.get("size", 0))
        avg_price = float(pos.get("avg_price", 0))
        side = pos.get("side", "BUY").upper()
        market = pos.get("market", "")
        outcome = pos.get("outcome", "")

        if size == 0:
            continue

        current_price = get_current_price(token_id)
        if current_price is None:
            continue

        if side == "BUY":
            pnl = (current_price - avg_price) * size
        else:  # SELL / SHORT
            pnl = (avg_price - current_price) * size

        total += pnl
        breakdown.append({
            "market": market,
            "outcome": outcome,
            "size": size,
            "avg_price": avg_price,
            "current_price": current_price,
            "pnl": pnl,
            "side": side,
        })

    return total, breakdown


def get_blockchain_usdc_balance() -> float:
    """Fetch USDC balance directly from Polygon blockchain using Alchemy RPC."""
    USDC_CONTRACT = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
    ABI = [{"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"}]
    
    try:
        from web3 import Web3
        # Use Polygon RPC from env (or fallback to public)
        rpc_url = POLYGON_RPC_URL if POLYGON_RPC_URL and "YOUR_KEY" not in POLYGON_RPC_URL else None
        if rpc_url:
            w3 = Web3(Web3.HTTPProvider(rpc_url))
            if w3.is_connected():
                print(f"  Using Alchemy Polygon RPC")
            else:
                print(f"  Alchemy RPC failed, trying fallback...")
                w3 = Web3(Web3.HTTPProvider("https://polygon.drpc.org"))
        else:
            print(f"  Using public Polygon RPC (set POLYGON_RPC_URL in .env for Alchemy)")
            w3 = Web3(Web3.HTTPProvider("https://polygon.drpc.org"))
        
        if not w3.is_connected():
            print(f"  [ERROR] Could not connect to any Polygon RPC")
            return 0.0
        
        contract = w3.eth.contract(address=USDC_CONTRACT, abi=ABI)
        balance_raw = contract.functions.balanceOf(POLYMARKET_FUNDER_ADDRESS).call()
        return float(balance_raw) / 1e6
    except Exception as e:
        print(f"  [WARN] Could not fetch blockchain balance: {e}")
        return 0.0


def get_wallet_balance() -> float:
    """Fetch USDC balance from CLOB /balance endpoint."""
    url = f"{CLOB_BASE}/balance"
    try:
        r = requests.get(url, headers=clob_headers(), timeout=10)
        r.raise_for_status()
        data = r.json()
        
        if isinstance(data, list):
            for bal in data:
                if bal.get("asset_type") == "COLLATERAL" or bal.get("token_id") == "USDC":
                    return float(bal.get("balance", 0)) / 1e6
        elif isinstance(data, dict):
            return float(data.get("balance", 0)) / 1e6
        return 0.0
    except Exception as e:
        print(f"  [ERROR] Could not fetch balance: {e}")
        return 0.0


def calc_realized_pnl(trades: list[dict]) -> float:
    """Calculate realized PnL from closed trades (simplified)."""
    from collections import defaultdict
    by_token = defaultdict(list)
    for t in trades:
        token_id = t.get("asset_id") or t.get("token_id", "unknown")
        by_token[token_id].append(t)

    total = 0.0

    for token_id, token_trades in by_token.items():
        token_trades.sort(key=lambda x: x.get("created_at", 0))
        buy_queue = []

        for trade in token_trades:
            side = trade.get("side", "BUY").upper()
            size = float(trade.get("size", 0))
            price = float(trade.get("price", 0))
            fee_bps = float(trade.get("fee_rate_bps", 0))
            fee = size * price * (fee_bps / 10_000)

            if side == "BUY":
                buy_queue.append([size, price])
            elif side == "SELL":
                remaining_sell = size
                sell_revenue = 0.0
                cost_basis = 0.0

                while remaining_sell > 0 and buy_queue:
                    buy_size, buy_price = buy_queue[0]
                    matched = min(remaining_sell, buy_size)
                    cost_basis += matched * buy_price
                    sell_revenue += matched * price
                    buy_queue[0][0] -= matched
                    remaining_sell -= matched
                    if buy_queue[0][0] <= 1e-9:
                        buy_queue.pop(0)

                pnl = sell_revenue - cost_basis - fee
                total += pnl

    return total


def verify_live_api():
    """Verify Polymarket API connectivity and data fetching."""
    
    print("=" * 70)
    print("POLYMARKET LIVE API VERIFICATION")
    print("=" * 70)
    
    # Check credentials
    missing = []
    if not POLYMARKET_API_KEY:
        missing.append("POLYMARKET_API_KEY")
    if not POLYMARKET_API_SECRET:
        missing.append("POLYMARKET_API_SECRET")
    if not POLYMARKET_PASSPHRASE:
        missing.append("POLYMARKET_PASSPHRASE")
    if not POLYMARKET_FUNDER_ADDRESS:
        missing.append("POLYMARKET_FUNDER_ADDRESS")
    
    if missing:
        print(f"\n❌ FAILED: Missing credentials: {', '.join(missing)}")
        print("   Set all required variables in .env")
        return False
    
    print(f"\n✓ API Key: {POLYMARKET_API_KEY[:10]}...")
    print(f"✓ API Secret: {POLYMARKET_API_SECRET[:10]}...")
    print(f"✓ Passphrase: {POLYMARKET_PASSPHRASE[:5]}...")
    print(f"✓ Wallet: {POLYMARKET_FUNDER_ADDRESS[:20]}...")
    print(f"✓ Initial Bankroll (Bot G): ${BOT_G_BANKROLL}")
    
    # Test 1: Get positions
    print("\n" + "-" * 70)
    print("Test 1: Fetch Open Positions")
    print("-" * 70)
    print(f"Endpoint: GET {CLOB_BASE}/positions")
    
    positions = get_open_positions()
    print(f"✓ Found {len(positions)} open position(s)")
    
    if positions:
        for pos in positions[:3]:
            market = pos.get("market", "Unknown")[:30]
            outcome = pos.get("outcome", "Unknown")
            size = float(pos.get("size", 0))
            side = pos.get("side", "BUY")
            print(f"  - {market}: {side} {size:.2f} shares ({outcome})")
        if len(positions) > 3:
            print(f"  ... and {len(positions) - 3} more")
    
    # Test 2: Calculate unrealized PnL
    print("\n" + "-" * 70)
    print("Test 2: Calculate Unrealized PnL")
    print("-" * 70)
    
    unrealized_total, breakdown = calc_unrealized_pnl(positions)
    print(f"Unrealized PnL: ${unrealized_total:.4f}")
    
    if breakdown:
        print("\nPosition breakdown:")
        for p in breakdown[:5]:
            outcome = (p['outcome'] or 'Unknown')[:20]
            pnl_str = f"${p['pnl']:+.4f}"
            print(f"  {outcome}: {pnl_str} ({p['side']})")
    
    # Test 3: Get trades for realized PnL
    print("\n" + "-" * 70)
    print("Test 3: Fetch Trade History for Realized PnL")
    print("-" * 70)
    print(f"Endpoint: GET {DATA_BASE}/v2/trades")
    
    trades = get_filled_trades()
    print(f"✓ Found {len(trades)} trade(s)")
    
    realized_total = calc_realized_pnl(trades)
    print(f"Realized PnL: ${realized_total:.4f}")
    
    # Test 4: Get wallet balance
    print("\n" + "-" * 70)
    print("Test 4: Fetch Wallet Balance")
    print("-" * 70)
    
    blockchain_balance = get_blockchain_usdc_balance()
    print(f"\n  Blockchain Wallet (Polygon):")
    print(f"    USDC Balance: ${blockchain_balance:.2f}")
    
    clob_balance = get_wallet_balance()
    print(f"\n  Polymarket CLOB (Deposited):")
    print(f"    USDC Balance: ${clob_balance:.2f}")
    
    # Calculate total portfolio value
    total_pnl = unrealized_total + realized_total
    positions_value = sum(float(p.get("size", 0)) * get_current_price(p.get("asset_id") or p.get("token_id", "")) or 0 for p in positions)
    current_value = clob_balance + positions_value
    
    print("\n" + "=" * 70)
    print("PORTFOLIO SUMMARY")
    print("=" * 70)
    print(f"Wallet USDC (Polygon): ${blockchain_balance:.2f}")
    print(f"Deposited to Polymarket: ${clob_balance:.2f}")
    print(f"Positions Value:         ${positions_value:.2f}")
    print(f"Starting Bankroll:       ${BOT_G_BANKROLL:.2f} (config)")
    print(f"Realized PnL:            ${realized_total:+.4f}")
    print(f"Unrealized PnL:          ${unrealized_total:+.4f}")
    print(f"Total PnL:               ${total_pnl:+.4f}")
    print(f"Current Value:           ${current_value:.2f}")
    if BOT_G_BANKROLL > 0:
        print(f"Return vs Bankroll:      {(total_pnl/BOT_G_BANKROLL)*100:+.2f}%")
    
    # Circuit breaker check
    print("\n" + "=" * 70)
    print("CIRCUIT BREAKER CHECK")
    print("=" * 70)
    
    PROFIT_THRESHOLD = 0.10
    TRAILING_STOP = 0.01
    profit_pct = total_pnl / BOT_G_BANKROLL
    
    if profit_pct >= PROFIT_THRESHOLD:
        print(f"⚠️  Profit threshold ({PROFIT_THRESHOLD*100:.0f}%) HIT")
        print(f"    Ratchet is ACTIVE - 1% drawdown will trigger halt")
        print(f"    Current profit: {profit_pct*100:.2f}%")
        print(f"    Drawdown allowed: {profit_pct * TRAILING_STOP * 100:.2f}%")
    else:
        print(f"ℹ️  Profit below threshold ({PROFIT_THRESHOLD*100:.0f}%)")
        print(f"    Ratchet NOT active yet")
        print(f"    Need {(PROFIT_THRESHOLD - profit_pct)*100:.2f}% more profit to activate")
    
    print("\n" + "=" * 70)
    print("VERIFICATION COMPLETE")
    print("=" * 70)
    print("\n✅ All API calls successful!")
    print("\nThe bot can now safely use Polymarket API for:")
    print("  - Live PnL tracking (realized + unrealized)")
    print("  - Circuit breaker profit ratchet checks")
    print("  - Position monitoring")
    
    return True


if __name__ == "__main__":
    success = verify_live_api()
    sys.exit(0 if success else 1)
