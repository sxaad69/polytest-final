"""
Polymarket CLOB API client for live trading P&L fetching.
Uses py_clob_client for authenticated endpoints and direct HTTP for public endpoints.
"""

import logging
import requests
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class PolymarketAPIClient:
    """
    Polymarket CLOB API client for live trading P&L fetching.
    Uses py_clob_client for Level 2 authenticated endpoints.
    """
    def __init__(self, api_key: str, api_secret: str, api_passphrase: str, private_key: str, funder_address: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.api_passphrase = api_passphrase
        self.private_key = private_key
        self.funder_address = funder_address
        self.clob_base = "https://clob.polymarket.com"
        self.data_base = "https://data-api.polymarket.com"
        self._client = None  # Lazy init py_clob_client
    
    def _get_client(self):
        """Lazy initialize py_clob_client for Level 2 authenticated calls."""
        if self._client is None:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import ApiCreds
            from py_clob_client.constants import POLYGON
            
            creds = ApiCreds(
                api_key=self.api_key,
                api_secret=self.api_secret,
                api_passphrase=self.api_passphrase,
            )
            self._client = ClobClient(
                host=self.clob_base,
                key=self.private_key,
                chain_id=POLYGON,
                creds=creds,
                funder=self.funder_address,
                signature_type=1,  # EOA
            )
        return self._client
    
    def get_positions(self, address: str, hours_back: int = 1) -> Dict[str, Any]:
        """Fetch currently open positions by calculating net position from recent trades.
        
        Args:
            address: Wallet address
            hours_back: Only include trades from last N hours (default 1 for current session)
        """
        try:
            from collections import defaultdict
            from datetime import datetime, timedelta
            
            # Get filled trades
            all_trades = self.get_filled_trades(limit=500)
            
            # Filter to recent trades only (current trading session)
            cutoff = datetime.utcnow() - timedelta(hours=hours_back)
            trades = []
            
            for t in all_trades:
                ts = t.get("match_time") or t.get("timestamp") or t.get("created_at")
                if ts:
                    if isinstance(ts, str):
                        try:
                            ts = float(ts)
                        except:
                            continue
                    
                    if isinstance(ts, (int, float)):
                        if ts > 1e12:  # Milliseconds
                            ts = ts / 1000
                        trade_dt = datetime.fromtimestamp(ts)
                        if trade_dt >= cutoff:
                            trades.append(t)
            
            # Calculate net position per token from recent trades
            by_token = defaultdict(lambda: {"size": 0.0, "avg_price": 0.0})
            
            for trade in trades:
                token_id = trade.get("asset_id") or trade.get("token_id", "")
                if not token_id:
                    continue
                    
                side = trade.get("side", "BUY").upper()
                size = float(trade.get("size", 0))
                price = float(trade.get("price", 0))
                
                if size == 0:
                    continue
                
                pos = by_token[token_id]
                
                if side == "BUY":
                    # Add to position with weighted average price
                    total_cost = pos["size"] * pos["avg_price"]
                    new_cost = size * price
                    pos["size"] += size
                    if pos["size"] > 0:
                        pos["avg_price"] = (total_cost + new_cost) / pos["size"]
                elif side == "SELL":
                    # Reduce position (avg_price stays same)
                    pos["size"] = max(0, pos["size"] - size)
            
            # Build positions list (only where net size > 0)
            positions = []
            for token_id, pos_data in by_token.items():
                if pos_data["size"] > 0.01:  # Minimum 0.01 shares
                    positions.append({
                        "asset_id": token_id,
                        "token_id": token_id,
                        "size": pos_data["size"],
                        "avg_price": pos_data["avg_price"],
                        "side": "BUY",
                        "market": "",
                    })
            
            return {
                "positions": positions,
                "count": len(positions),
                "success": True
            }
        except Exception as e:
            logger.error("[POLYMARKET-API] Positions fetch failed: %s", e)
            return {"success": False, "error": str(e), "positions": [], "count": 0}
    
    def get_current_price(self, token_id: str, mode: str = "bid") -> Optional[float]:
        """Get current price (bid, ask, or mid) for a token from CLOB."""
        try:
            # Use /book for bid/ask, fall back to /midpoint for mid mode or if book unavailable
            url = f"{self.clob_base}/book"
            params = {"token_id": token_id}
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            # EXPLICIT error check — /book returns {"error": ...} for invalid/inactive tokens
            # without raising an HTTP error, so we must check the JSON directly.
            if "error" in data:
                raise ValueError(f"Book API error: {data['error']}")

            if mode == "bid":
                # The highest price someone is willing to pay you (Selling price)
                bids = data.get("bids", [])
                if bids:
                    return float(bids[0].get("price"))
            elif mode == "ask":
                # The lowest price someone is willing to sell to you (Buying price)
                asks = data.get("asks", [])
                if asks:
                    return float(asks[0].get("price"))

            # Fall through to midpoint if bids/asks list is empty — do NOT raise, just fall through
            logger.debug("[POLYMARKET-API] Empty bids/asks for %s — falling back to midpoint", token_id[:20])

        except Exception as e:
            logger.debug("[POLYMARKET-API] /book fetch failed for %s (%s), falling back to /midpoint", token_id[:20], e)
            # Fallback to midpoint — always reliable, just slightly optimistic
            try:
                m_url = f"{self.clob_base}/midpoint"
                m_res = requests.get(m_url, params={"token_id": token_id}, timeout=5)
                m_data = m_res.json()
                if "error" not in m_data:
                    return float(m_data.get("mid", 0))
            except Exception:
                pass
            return None
    
    def get_filled_trades(self, since: Optional[int] = None, limit: int = 500) -> list[dict]:
        """Fetch filled trades from CLOB via py_clob_client.
        
        Args:
            since: Unix timestamp - only fetch trades after this time (for efficient filtering)
            limit: Maximum trades to fetch
        """
        try:
            client = self._get_client()
            from py_clob_client.clob_types import TradeParams
            
            # Use native API filtering if 'since' timestamp provided
            if since:
                params = TradeParams(
                    maker_address=self.funder_address,
                    after=since
                )
            else:
                params = TradeParams(maker_address=self.funder_address)
            
            trades_result = client.get_trades(params)
            
            # Extract trades from result
            if isinstance(trades_result, dict):
                trades = trades_result.get("trades", [])
            elif isinstance(trades_result, list):
                trades = trades_result
            else:
                trades = []
            
            return trades[:limit]
        except Exception as e:
            logger.error("[POLYMARKET-API] Trades fetch failed: %s", e)
            return []
    
    def get_wallet_balance(self) -> float:
        """Fetch USDC balance from CLOB via py_clob_client."""
        try:
            client = self._get_client()
            from py_clob_client.clob_types import BalanceAllowanceParams
            
            params = BalanceAllowanceParams(asset_type="COLLATERAL")
            result = client.get_balance_allowance(params)
            
            # Result contains balance field
            if isinstance(result, dict):
                balance = result.get("balance", 0)
                return float(balance) / 1e6 if balance else 0.0
            return 0.0
        except Exception as e:
            logger.warning("[POLYMARKET-API] Balance fetch failed: %s", e)
            return 0.0

    def get_token_balance(self, token_id: str) -> float:
        """Fetch specific ERC1155 token share balance from CLOB via py_clob_client."""
        try:
            client = self._get_client()
            from py_clob_client.clob_types import BalanceAllowanceParams
            
            params = BalanceAllowanceParams(asset_type="CONDITIONAL", token_id=token_id)
            result = client.get_balance_allowance(params)
            
            # Tokens have 6 decimals just like USDC on Polymarket
            if isinstance(result, dict):
                balance = result.get("balance", 0)
                return float(balance) / 1e6 if balance else 0.0
            return 0.0
        except Exception as e:
            logger.warning("[POLYMARKET-API] Token balance fetch failed for %s: %s", token_id, e)
            return 0.0
    
    def calc_unrealized_pnl(self, positions: list[dict]) -> float:
        """Calculate REALISTIC unrealized PnL from open positions.
        
        Uses Bid prices (what you can actually sell at) and subtracts
        estimated total fees (0.2%) to give a 'True Liquidation' value.
        """
        total = 0.0
        ESTIMATED_TOTAL_FEE_PCT = 0.002 # 0.1% entry + 0.1% exit
        
        for pos in positions:
            token_id = pos.get("asset_id") or pos.get("token_id", "")
            size = float(pos.get("size", 0))
            avg_price = float(pos.get("avg_price", 0))
            side = pos.get("side", "BUY").upper()
            
            if size == 0:
                continue
            
            # Use "bid" mode for liquidation valuation
            current_price = self.get_current_price(token_id, mode="bid")
            if current_price is None:
                continue
            
            if side == "BUY":
                # Net PnL = (Market_Bid - Entry_Price) * Size - (Transaction_Fees)
                pnl = (current_price - avg_price) * size
                # Subtract fees based on the total capital locked
                friction = (size * avg_price) * ESTIMATED_TOTAL_FEE_PCT
                pnl -= friction
            else:  # SELL / SHORT
                pnl = (avg_price - current_price) * size
                friction = (size * avg_price) * ESTIMATED_TOTAL_FEE_PCT
                pnl -= friction
            
            total += pnl
        
        return total
    
    def calc_realized_pnl(self, trades: list[dict], hours_back: int = 24, since_ts: float = None) -> float:
        """Calculate realized PnL from closed trades using FIFO matching.
        
        Args:
            trades: List of trade dicts
            hours_back: Only include trades from last N hours (default 24 for daily PnL)
            since_ts: Unix timestamp — if set, only include trades AFTER this time (overrides hours_back)
        """
        from collections import defaultdict
        
        # Filter trades by timestamp
        # If since_ts provided, use that as absolute cutoff (for session-based P&L)
        # Otherwise fall back to hours_back window (for daily P&L)
        if since_ts is not None:
            cutoff = datetime.utcfromtimestamp(since_ts)
        else:
            cutoff = datetime.utcnow() - timedelta(hours=hours_back)
        recent_trades = []
        
        for t in trades:
            # Polymarket uses 'match_time' field for trade timestamps
            ts = t.get("match_time") or t.get("timestamp") or t.get("created_at")
            if ts:
                # Handle different timestamp formats
                if isinstance(ts, str):
                    try:
                        ts = float(ts)
                    except:
                        continue
                
                if isinstance(ts, (int, float)):
                    # Unix timestamp (seconds or milliseconds)
                    if ts > 1e12:  # Milliseconds
                        ts = ts / 1000
                    trade_dt = datetime.fromtimestamp(ts)
                else:
                    # ISO string
                    try:
                        trade_dt = datetime.fromisoformat(ts.replace('Z', '+00:00').replace('+00:00', ''))
                    except:
                        continue
                
                if trade_dt >= cutoff:
                    recent_trades.append(t)
        
        by_token = defaultdict(list)
        for t in recent_trades:
            token_id = t.get("asset_id") or t.get("token_id") or t.get("market", "unknown")
            by_token[token_id].append(t)
        
        total = 0.0
        
        for token_id, token_trades in by_token.items():
            # Sort by match_time (Polymarket's timestamp field)
            token_trades.sort(key=lambda x: x.get("match_time") or x.get("timestamp") or 0)
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
    
    def get_portfolio_value(self, address: str, since_ts: float = None) -> Dict[str, Any]:
        """Get portfolio value and PnL breakdown from CLOB.
        
        Args:
            address: Wallet address
            since_ts: Unix timestamp — if set, realized PnL only counts trades after this time
        """
        try:
            # Get positions
            positions_result = self.get_positions(address)
            positions = positions_result.get("positions", [])
            
            # Calculate unrealized PnL from positions
            unrealized_pnl = self.calc_unrealized_pnl(positions)
            
            # Calculate positions value (size * current price)
            positions_value = 0.0
            for pos in positions:
                token_id = pos.get("asset_id") or pos.get("token_id", "")
                size = float(pos.get("size", 0))
                current_price = self.get_current_price(token_id)
                if current_price is not None:
                    positions_value += size * current_price
            
            # Get filled trades: use session cutoff if provided, otherwise last 24h
            if since_ts is not None:
                cutoff_ts = int(since_ts)
            else:
                cutoff_ts = int((datetime.utcnow() - timedelta(hours=24)).timestamp())
            trades = self.get_filled_trades(since=cutoff_ts, limit=100)
            realized_pnl = self.calc_realized_pnl(trades, since_ts=since_ts)
            
            # Get actual wallet balance from CLOB
            cash_balance = self.get_wallet_balance()
            
            # Total value = cash + positions value
            total_value = cash_balance + positions_value
            total_pnl = realized_pnl + unrealized_pnl
            
            return {
                "total_value": total_value,
                "cash_balance": cash_balance,
                "positions_value": positions_value,
                "unrealized_pnl": unrealized_pnl,
                "realized_pnl": realized_pnl,
                "total_pnl": total_pnl,
                "success": True
            }
            
        except Exception as e:
            logger.error("[POLYMARKET-API] Portfolio value fetch failed: %s", e)
            return {"success": False, "error": str(e)}
    
    def get_pnl_summary(self, address: str, initial_bankroll: float, since_ts: float = None) -> Dict[str, Any]:
        """Get complete P&L summary for circuit breaker checks.
        
        Args:
            address: Wallet address
            initial_bankroll: Starting balance for percentage calculations
            since_ts: Unix timestamp — if set, realized PnL is session-only (from this time onwards)
        """
        portfolio = self.get_portfolio_value(address, since_ts=since_ts)
        
        if not portfolio["success"]:
            return {
                "success": False,
                "error": portfolio.get("error"),
                "source": "polymarket_api"
            }
        
        total_pnl = portfolio.get("total_pnl", 0)
        current_value = initial_bankroll + total_pnl
        total_pnl_pct = total_pnl / max(initial_bankroll, 1.0) if initial_bankroll > 0 else 0
        
        return {
            "success": True,
            "total_value": current_value,
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl_pct,
            "realized_pnl": portfolio.get("realized_pnl", 0),
            "unrealized_pnl": portfolio.get("unrealized_pnl", 0),
            "cash_balance": portfolio.get("cash_balance", 0),
            "position_count": portfolio.get("positions_count", 0),
            "source": "polymarket_api"
        }
    
    def close_position(self, position_id: str, size: float) -> Dict[str, Any]:
        """Close a specific position - requires py-clob-client for order signing"""
        logger.warning("[POLYMARKET-API] close_position requires py-clob-client for order signing")
        return {"success": False, "error": "Not implemented - use place_order in feeds/polymarket.py", "position_id": position_id}
    
    def close_all_positions(self, address: str) -> Dict[str, Any]:
        """
        Close all positions on Polymarket using py-clob-client.
        Sells each position at current market price (best bid).
        """
        # First, get all open positions
        positions_result = self.get_positions(address)
        if not positions_result["success"]:
            return {"success": False, "error": positions_result.get("error")}
        
        positions = positions_result.get("positions", [])
        if not positions:
            return {"success": True, "message": "No open positions", "closed": []}
        
        # Try to close each position using py-clob-client
        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType
            from py_clob_client.constants import POLYGON
            
            creds = ApiCreds(
                api_key        = self.api_key,
                api_secret     = self.api_secret,
                api_passphrase = self.api_passphrase,
            )
            client = ClobClient(
                host           = self.clob_base,
                key            = self.private_key,
                chain_id       = POLYGON,
                creds          = creds,
                funder         = self.funder_address,
                signature_type = 1,   # EOA
            )
            
            closed_positions = []
            failed_positions = []
            
            for pos in positions:
                token_id = pos.get("asset_id") or pos.get("token_id", "")
                size = float(pos.get("size", 0))
                side = pos.get("side", "BUY").upper()
                
                if not token_id or size <= 0:
                    continue
                
                try:
                    # Get current price (best bid) for selling
                    current_price = self.get_current_price(token_id)
                    if current_price is None:
                        current_price = 0.01  # Fallback
                    
                    # Round to valid tick
                    rounded_price = round(round(current_price / 0.01) * 0.01, 4)
                    
                    # Calculate shares
                    shares = round(size / rounded_price, 2) if rounded_price > 0 else size
                    
                    # Create and submit sell order
                    order_args = OrderArgs(
                        token_id = token_id,
                        price    = rounded_price,
                        size     = shares,
                        side     = "SELL",
                    )
                    
                    signed_order = client.create_order(order_args)
                    resp = client.post_order(signed_order, OrderType.GTC)
                    
                    if resp and resp.get("success"):
                        closed_positions.append({
                            "token_id": token_id,
                            "size": shares,
                            "price": float(resp.get("price", rounded_price)),
                            "order_id": resp.get("orderID"),
                        })
                        logger.info("[POLYMARKET-API] Closed position %s: %s shares @ %.3f",
                                   token_id[:20], shares, rounded_price)
                    else:
                        failed_positions.append({
                            "token_id": token_id,
                            "error": resp.get("error") if resp else "Unknown error"
                        })
                        logger.error("[POLYMARKET-API] Failed to close position %s: %s",
                                    token_id[:20], resp)
                        
                except Exception as e:
                    failed_positions.append({
                        "token_id": token_id,
                        "error": str(e)
                    })
                    logger.error("[POLYMARKET-API] Exception closing position %s: %s",
                               token_id[:20], e)
            
            return {
                "success": len(failed_positions) == 0,
                "closed_count": len(closed_positions),
                "failed_count": len(failed_positions),
                "total_positions": len(positions),
                "closed": closed_positions,
                "failed": failed_positions,
            }
            
        except ImportError:
            logger.error("[POLYMARKET-API] py-clob-client not installed - cannot close positions")
            return {
                "success": False,
                "error": "py-clob-client not installed",
                "total_positions": len(positions),
                "positions": positions,
            }
        except Exception as e:
            logger.error("[POLYMARKET-API] Exception in close_all_positions: %s", e)
            return {
                "success": False,
                "error": str(e),
                "total_positions": len(positions),
            }
