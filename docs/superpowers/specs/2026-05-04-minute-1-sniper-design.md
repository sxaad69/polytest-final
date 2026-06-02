# Minute 1 Sniper Strategy Design Spec

**Date:** 2026-05-04
**Goal:** Implement a high-alpha "Minute 1 Sniper" bot using the proven Bot G infrastructure for Polymarket Updown markets.

## 1. Overview
The Sniper Strategy capitalizes on the "Picker" phase of a 5-minute market window (the first 60 seconds). It uses specific entry price bands (0.33–0.54) and a trailing take-profit mechanism to capture early momentum while protecting capital.

## 2. Architecture
The system will be implemented as a new bot class, `BotSniper`, which inherits from the `BotG` class. This ensures it reuses the proven:
- WebSocket-driven market data handlers.
- Multi-asset discovery logic.
- `ExecutionLayer` (trader.py) for position tracking and Trailing Stop management.

## 3. Configuration (config.py / .env)
New configuration variables to be introduced:
- `SNIPER_ENABLED`: (bool)
- `SNIPER_STRIKE_ASSETS`: (list) Assets to monitor (e.g., BTC, ETH, SOL).
- `SNIPER_DIRECTION`: (str/None) "long" for YES only, `None` for both sides.
- `SNIPER_MIN_MOMENTUM`: (float/None) Threshold for Binance momentum. `None` for blind entry.
- `SNIPER_BANKROLL`: (float) Starting balance (e.g., $35.00).
- `SNIPER_STAKE`: (float) Per-trade entry size (e.g., $3.00).

## 4. Entry Logic (The "Sniper Gate")
For every WebSocket price tick received for a discovered market:
1. **Time Check:** If `elapsed_secs` > 60, reject.
2. **Momentum Check:** If `SNIPER_MIN_MOMENTUM` is set and asset momentum < threshold, reject.
3. **Band Check (YES):** 
   - If `YES_price` in [0.33, 0.54] AND `SNIPER_DIRECTION` in ["long", None]:
     - Trigger **YES** entry via `ExecutionLayer`.
4. **Band Check (NO):**
   - If `NO_price` in [0.33, 0.54] AND `SNIPER_DIRECTION` is None:
     - Trigger **NO** entry via `ExecutionLayer`.

## 5. Exit Logic (Profit Ratchet)
Managed by `ExecutionLayer` with the following parameters:
- **Hard Stop Loss:** -5 cents from entry.
- **TTP Activation:** +8 cents from entry.
- **TTP Trail:** 3 cents from peak profit.

## 6. Success Criteria
- Bot enters 100% of trades within the first 60 seconds.
- Bot never enters a trade outside the 0.33–0.54 band.
- Positions are heart-beated every 1s to `logs/open_positions.log`.
- Rejections are logged to `logs/bot_sniper_rejections.log`.
