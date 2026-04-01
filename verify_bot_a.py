import sys
import os
from datetime import datetime

# Add polytest to path
project_root = "/home/ubuntu/polytest"
sys.path.append(project_root)

# Mocking config before import to test fallback
import config

# Mocking feeds for BotA
class MockBinance:
    price = 60000.0
    momentum_30s = 0.05
    momentum_60s = 0.05
    rsi_14 = 50
    volume_zscore = 0
    lag_signal = 0
    lag_sustained = 0
    lag_detected = False
    
class MockChainlink:
    price = 60000.1
    deviation_pct = 0.25 # Inside [0.20, 0.30]
    lag_signal = 1
    lag_sustained = 5
    lag_detected = True

class MockPoly:
    market_id = "test_market"
    seconds_remaining = 60 # Inside [45, 120]
    up_odds = 0.4 # Inside [0.30, 0.50]
    down_odds = 0.6
    window_end = 1711324800.0
    ts_entry = 1711324700.0
    
# Mocking Signal result
class MockSignalResult:
    def __init__(self):
        self.direction = "long"
        self.score = 0.8
        self.tradeable = True

class MockBotASignal:
    def evaluate(self, **kwargs):
        return MockSignalResult()

from bots.bot_a import BotA

def test_bot_a_rules():
    print(f"--- Verification Test: Current Time ---")
    current_hour = datetime.utcnow().hour
    print(f"Current UTC Hour: {current_hour}")
    print(f"Bot A Active Hours: {getattr(config, 'BOT_A_ACTIVE_HOURS_UTC', 'NOT SET')}")
    
    binance = MockBinance()
    chainlink = MockChainlink()
    poly = MockPoly()
    
    bot_a = BotA(binance, chainlink, poly)
    # Override signal for deterministic testing
    bot_a._signal = MockBotASignal()
    
    print("\n--- TEST 1: Hour Filter ---")
    if current_hour not in config.BOT_A_ACTIVE_HOURS_UTC:
        print(f"SKIP EXPECTED: Hour {current_hour} is NOT in {config.BOT_A_ACTIVE_HOURS_UTC}")
    else:
        print(f"PASS EXPECTED: Hour {current_hour} IS in {config.BOT_A_ACTIVE_HOURS_UTC}")
        
    result = bot_a.evaluate_signal()
    if result is None:
        print("RESULT: Signal SKIPPED")
    else:
        print(f"RESULT: Signal PASSED | Dir: {result.direction}")

    print("\n--- TEST 2: Time Remaining Filter (200s) ---")
    poly.seconds_remaining = 200
    result = bot_a.evaluate_signal()
    print(f"RESULT (200s): {'SKIPPED' if result is None else 'PASSED'}")

    print("\n--- TEST 3: Odds Filter (0.7) ---")
    poly.seconds_remaining = 60 # reset
    poly.up_odds = 0.7
    result = bot_a.evaluate_signal()
    print(f"RESULT (0.7 odds): {'SKIPPED' if result is None else 'PASSED'}")

    print("\n--- TEST 4: Full Success Case (All conditions met) ---")
    poly.up_odds = 0.4
    poly.seconds_remaining = 60
    # Temporarily force hour to be in active list
    config.BOT_A_ACTIVE_HOURS_UTC.append(current_hour)
    result = bot_a.evaluate_signal()
    print(f"RESULT (Correct conditions): {'SKIPPED' if result is None else 'PASSED'}")

    print("\n--- TEST 5: Stop Loss Disable logic in Trader ---")
    disable_sl = False
    if bot_a.executor.bot_id == "A" and getattr(config, "BOT_A_DISABLE_STOP_LOSS", False):
        disable_sl = True
    print(f"Stop Loss Disabled for Bot A: {disable_sl}")

if __name__ == "__main__":
    test_bot_a_rules()
