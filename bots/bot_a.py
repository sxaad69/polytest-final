"""Bot A — Pure Chainlink Lag Arbitrage"""

import logging
from config import BOT_A_BANKROLL, BOT_A_DB_PATH
from bots.base_bot import BaseBot
from signals.signal_a import BotASignal

logger = logging.getLogger("bot_a")


class BotA(BaseBot):

    BOT_ID            = "A"
    DB_PATH           = BOT_A_DB_PATH
    STARTING_BANKROLL = BOT_A_BANKROLL

    def __init__(self, binance, chainlink, poly, wallet_address=None, polymarket_client=None):
        super().__init__(binance, chainlink, poly, wallet_address=wallet_address, polymarket_client=polymarket_client)
        self._signal = BotASignal()

    def evaluate_signal(self):
        result = self._signal.evaluate(
            lag_signal    = self.chainlink.lag_signal,
            lag_sustained = self.chainlink.lag_sustained,
            lag_detected  = self.chainlink.lag_detected,
        )
        if not result or not result.tradeable:
            return result

        import config

        # 1. Sustain Threshold Filter (DATA: >= 4s removes 70% of 1s transient wicks)
        min_sustain = getattr(config, "BOT_A_MIN_SUSTAIN_SECS", 4)
        if result.lag_sustained < min_sustain:
            result.tradeable = False
            result.skip_reason = f"lag_sustain_too_short:{result.lag_sustained:.1f}s<{min_sustain}s"
            return result

        # 2. Odds Bracket Filter (DATA: [0.40, 0.55] sweet spot nets +20.27 USDC, eliminates negative R:R > 0.55)
        trade_odds = self.poly.up_odds if result.direction == "long" else self.poly.down_odds
        min_odds = getattr(config, "BOT_A_MIN_ODDS", 0.40)
        max_odds = getattr(config, "BOT_A_MAX_ODDS", 0.55)
        if trade_odds is not None:
            if trade_odds < min_odds:
                result.tradeable = False
                result.skip_reason = f"odds_below_floor:{trade_odds:.3f}<{min_odds}"
                return result
            if trade_odds > max_odds:
                result.tradeable = False
                result.skip_reason = f"odds_above_ceiling:{trade_odds:.3f}>{max_odds}"
                return result

        # 3. Spot Momentum Confluence (DATA: Binance 60s momentum alignment)
        if getattr(config, "BOT_A_REQUIRE_SPOT_MOM", True) and hasattr(self.binance, "get_momentum"):
            mom_60s = self.binance.get_momentum("BTC", 60)
            if result.direction == "long" and mom_60s < -0.015:
                result.tradeable = False
                result.skip_reason = f"spot_contradiction_dump:mom={mom_60s:.3f}%"
                return result
            elif result.direction == "short" and mom_60s > 0.015:
                result.tradeable = False
                result.skip_reason = f"spot_contradiction_pump:mom={mom_60s:.3f}%"
                return result

        return result
