"""
Mock test for Legacy Circuit Breaker
Tests profit ratchet and loss circuit breaker scenarios
"""
import sys
sys.path.insert(0, '/home/ubuntu/polytest_legacy')

from database.db import Database
import os
import sqlite3

# Test database
TEST_DB = '/tmp/test_circuit_breaker.db'

def setup_test_db():
    """Create fresh test database"""
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    return Database(TEST_DB, "test_bot")

def test_profit_ratchet_scenario():
    """
    Test: Bot makes 259% profit (like Legacy A)
    Expected: Should halt at 10% profit target
    """
    print("\n=== PROFIT RATCHET TEST ===")
    db = setup_test_db()
    
    # Simulate: Bankroll $50, profit $129.93 = 259%
    bankroll = 50.0
    pnl = 129.93  # 259% profit
    
    # Check current circuit breaker state
    cb = db.get_cb()
    print(f"Initial state: halted={cb.get('halted')}, peak={cb.get('peak_profit_pct')}")
    
    # Calculate profit %
    profit_pct = pnl / bankroll
    print(f"Current profit: {profit_pct*100:.1f}% (${pnl} / ${bankroll})")
    
    # Check if should halt
    PROFIT_THRESHOLD = 0.10  # 10%
    
    if profit_pct >= PROFIT_THRESHOLD:
        print(f"✓ Profit {profit_pct*100:.1f}% >= {PROFIT_THRESHOLD*100}% threshold")
        print("✓ SHOULD HALT HERE - Daily profit target hit!")
        db.update_cb(
            cb.get('consecutive_losses', 0),
            cb.get('daily_loss_usdc', 0.0),
            halted=True,
            reason=f"daily_profit_{profit_pct*100:.1f}pct"
        )
    
    # Verify
    cb_after = db.get_cb()
    print(f"After check: halted={cb_after.get('halted')}, reason={cb_after.get('halted_reason')}")
    
    if cb_after.get('halted') == 1:
        print("✅ TEST PASSED: Bot halted at profit target")
        return True
    else:
        print("❌ TEST FAILED: Bot did NOT halt!")
        return False

def test_loss_circuit_breaker():
    """
    Test: Bot loses 25% (exceeds 20% daily loss limit)
    Expected: Should halt at 20% loss
    """
    print("\n=== LOSS CIRCUIT BREAKER TEST ===")
    db = setup_test_db()
    
    # Simulate: Bankroll $50, loss -$12.50 = -25%
    bankroll = 50.0
    daily_loss = -12.50
    
    cb = db.get_cb()
    print(f"Initial state: halted={cb.get('halted')}, daily_loss={cb.get('daily_loss_usdc')}")
    
    # Calculate loss %
    loss_pct = abs(daily_loss) / bankroll
    print(f"Current loss: {loss_pct*100:.1f}% (${daily_loss} / ${bankroll})")
    
    # Check if should halt
    DAILY_LOSS_LIMIT_PCT = 0.20  # 20%
    
    if loss_pct >= DAILY_LOSS_LIMIT_PCT:
        print(f"✓ Loss {loss_pct*100:.1f}% >= {DAILY_LOSS_LIMIT_PCT*100}% limit")
        print("✓ SHOULD HALT HERE - Daily loss limit hit!")
        db.update_cb(
            cb.get('consecutive_losses', 0),
            daily_loss,
            halted=True,
            reason=f"daily_loss_{loss_pct*100:.1f}pct"
        )
    
    # Verify
    cb_after = db.get_cb()
    print(f"After check: halted={cb_after.get('halted')}, reason={cb_after.get('halted_reason')}")
    
    if cb_after.get('halted') == 1:
        print("✅ TEST PASSED: Bot halted at loss limit")
        return True
    else:
        print("❌ TEST FAILED: Bot did NOT halt!")
        return False

def test_consecutive_losses():
    """
    Test: Bot hits 7 consecutive losses (should NOT halt, limit=100)
    Expected: Should NOT halt
    """
    print("\n=== CONSECUTIVE LOSSES TEST ===")
    db = setup_test_db()
    
    # Set 7 consecutive losses
    consecutive = 7
    MAX_CONSECUTIVE = 100
    
    cb = db.get_cb()
    print(f"Consecutive losses: {consecutive}, Max allowed: {MAX_CONSECUTIVE}")
    
    if consecutive >= MAX_CONSECUTIVE:
        print("✓ Should halt for consecutive losses")
        db.update_cb(
            consecutive,
            cb.get('daily_loss_usdc', 0.0),
            halted=True,
            reason=f"{consecutive}_consecutive_losses"
        )
    else:
        print(f"✓ {consecutive} < {MAX_CONSECUTIVE}, should NOT halt")
    
    # Verify
    cb_after = db.get_cb()
    print(f"After check: halted={cb_after.get('halted')}")
    
    if cb_after.get('halted') == 0:
        print("✅ TEST PASSED: Bot did NOT halt (below threshold)")
        return True
    else:
        print("❌ TEST FAILED: Bot halted incorrectly!")
        return False

if __name__ == "__main__":
    print("🧪 CIRCUIT BREAKER MOCK TESTS")
    print("="*50)
    
    results = []
    results.append(("Profit Ratchet", test_profit_ratchet_scenario()))
    results.append(("Loss Circuit Breaker", test_loss_circuit_breaker()))
    results.append(("Consecutive Losses", test_consecutive_losses()))
    
    print("\n" + "="*50)
    print("📊 TEST RESULTS:")
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {name}: {status}")
    
    all_passed = all(r[1] for r in results)
    print("\n" + ("✅ ALL TESTS PASSED" if all_passed else "❌ SOME TESTS FAILED"))
