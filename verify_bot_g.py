import asyncio
import logging
import sys
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime

# Mocking the environment
sys.path.append("/home/ubuntu/polytest")

import config
from bots.bot_g import BotG

class TestBotGFilters(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.binance = MagicMock()
        self.chainlink = MagicMock()
        self.poly = MagicMock()
        self.bot = BotG(self.binance, self.chainlink, self.poly)
        self.bot.executor = MagicMock()
        async def mock_enter(*args, **kwargs): pass
        self.bot.executor.enter = MagicMock(side_effect=mock_enter)
        self.bot.executor._positions = {}
        self.bot.db = MagicMock()
        self.bot.filters = MagicMock()
        self.bot.sizer = MagicMock()
        
        # Default mock values
        self.binance.get_momentum.return_value = 0.01
        self.binance.get_price.return_value = 50000.0
        self.poly.markets = {}

    @patch("bots.bot_g.datetime")
    @patch("bots.bot_g.time.time")
    async def test_active_hours_filter(self, mock_time, mock_datetime):
        # Case 1: Active Hour
        mock_datetime.utcnow.return_value = datetime(2026, 3, 25, 5, 0, 0)
        mock_time.return_value = 1711324800 # Match win_start
        
        m = {
            "condition_id": "math_1",
            "slug": "btc-updown-5m-1711324800",
            "odds": 0.45,
            "win_start": 1711324800,
            "win_end": 1711325100
        }
        
        # Reset mock_datetime to an ACTIVE hour for evaluate_market tests
        mock_datetime.utcnow.return_value = datetime(2026, 3, 25, 5, 0, 0)
        
        # Test Direction: Long (Should fail as we want SHORT ONLY)
        with patch("config.BOT_G_DIRECTION", "short"):
            # Mock signal to return LONG
            self.bot._signal.evaluate = MagicMock()
            self.bot._signal.evaluate.return_value = MagicMock(tradeable=True, direction="long", score=0.1)
            
            await self.bot._evaluate_market("tid1", m)
            self.bot.executor.enter.assert_not_called()
            print("✅ Direction Filter: Rejected LONG correctly")

        # Test Momentum: High (Should fail)
        with patch("config.BOT_G_MAX_MOMENTUM_30S", 0.05):
            self.binance.get_momentum.return_value = 0.15 
            await self.bot._evaluate_market("tid1", m)
            self.bot.executor.enter.assert_not_called()
            print("✅ Momentum Filter: Rejected high momentum correctly")

        # Test Odds: High (Should fail)
        with patch("config.BOT_G_MAX_ENTRY_ODDS", 0.55):
            m_bad_odds = m.copy()
            m_bad_odds["odds"] = 0.65
            await self.bot._evaluate_market("tid1", m_bad_odds)
            self.bot.executor.enter.assert_not_called()
            print("✅ Odds Filter: Rejected high odds correctly")

        # Test FULL PASS
        with patch("config.BOT_G_DIRECTION", "short"), \
             patch("config.BOT_G_MAX_MOMENTUM_30S", 0.05), \
             patch("config.BOT_G_MAX_ENTRY_ODDS", 0.55):
            
            self.binance.get_momentum.return_value = 0.02
            self.bot._signal.evaluate.return_value = MagicMock(
                tradeable=True, direction="short", score=0.1, 
                components={"asset_price": 50000}
            )
            # Short tokens are peer_id's odds
            self.poly.markets = {"peer_1": {"odds": 0.45}}
            m_good = m.copy()
            m_good["peer_id"] = "peer_1"
            
            # Filters.check must pass
            self.bot.filters.check.return_value = (True, "OK")
            # Sizer must pass
            self.bot.sizer.calculate.return_value = 10.0
            
            await self.bot._evaluate_market("tid1", m_good)
            self.bot.executor.enter.assert_called_once()
            print("✅ Full Pass: Bot G entered correct Short position under optimal settings")

if __name__ == "__main__":
    unittest.main()
