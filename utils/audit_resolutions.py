import urllib.request
import sqlite3
import json
import logging
import time
from datetime import datetime

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

DB_PATH = "data/bot_g_paper.db"
GAMMA_URL = "https://gamma-api.polymarket.com"

def fetch_resolution(condition_id):
    """Fetch market resolution data from Gamma API using standard urllib."""
    url = f"{GAMMA_URL}/markets?conditionId={condition_id}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            if resp.getcode() != 200:
                return None
            data = json.loads(resp.read().decode('utf-8'))
            if not data or not isinstance(data, list):
                return None
            return data[0]
    except Exception as e:
        logger.error(f"Error fetching condition {condition_id}: {e}")
        return None

def get_winner_index(market_data):
    """
    Extracts the winning outcome index from outcomePrices.
    outcomePrices = ["1", "0"] means index 0 (Up/Yes) won.
    outcomePrices = ["0", "1"] means index 1 (Down/No) won.
    """
    try:
        prices = market_data.get("outcomePrices")
        if isinstance(prices, str):
            prices = json.loads(prices)
        
        if not prices:
            return None
            
        for i, price in enumerate(prices):
            if str(price) == "1":
                return i
        return None
    except Exception as e:
        logger.error(f"Error parsing outcome prices: {e}")
        return None

def audit_db():
    logger.info(f"Starting audit for {DB_PATH}")
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    # 1. Find all resolved trades that don't have a true settlement recorded
    # We will use 'outcome_index' to store the true winner.
    trades = conn.execute("""
        SELECT id, market_id, market_condition_id, direction, entry_odds, exit_reason
        FROM trades 
        WHERE resolved = 1 AND market_condition_id IS NOT NULL 
          AND outcome_index IS NULL
    """).fetchall()
    
    if not trades:
        logger.info("No trades found requiring resolution audit.")
        # Re-run analysis even if no new trades were fetched
    else:
        logger.info(f"Found {len(trades)} trades to audit.")

        for trade in trades:
            t_id = trade['id']
            c_id = trade['market_condition_id']
            
            logger.info(f"Auditing Trade #{t_id} (Condition: {c_id[:12]}...)")
            
            m_data = fetch_resolution(c_id)
            if not m_data or not m_data.get('resolved'):
                logger.warning(f"Trade #{t_id} market not resolved or not found yet.")
                continue
            
            winner_idx = get_winner_index(m_data)
            if winner_idx is None:
                logger.warning(f"Could not determine winner for Trade #{t_id}")
                continue
            
            # Record the winner index
            conn.execute("UPDATE trades SET outcome_index = ? WHERE id = ?", (winner_idx, t_id))
            conn.commit()
            logger.info(f"Trade #{t_id} Resolved: Winner Index = {winner_idx}")
            
            # Optional: Short delay to be nice to API
            time.sleep(0.1)

    # 2. Perform the Shakeout Analysis
    # winner_idx 0 = UP/LONG, 1 = DOWN/SHORT
    logger.info("\n--- UPDATING SHAKEOUT ANALYSIS ---")
    
    # Correct direction but stopped
    shakeouts = conn.execute("""
        SELECT COUNT(*) as cnt
        FROM trades 
        WHERE exit_reason = 'hard_sl_hit'
          AND (
            (direction = 'long' AND outcome_index = 0) OR
            (direction = 'short' AND outcome_index = 1)
          )
    """).fetchone()['cnt']
    
    # Wrong direction and stopped
    legit_losses = conn.execute("""
        SELECT COUNT(*) as cnt
        FROM trades 
        WHERE exit_reason = 'hard_sl_hit'
          AND (
            (direction = 'long' AND outcome_index = 1) OR
            (direction = 'short' AND outcome_index = 0)
          )
    """).fetchone()['cnt']

    logger.info(f"Analysis Complete for Active Session:")
    logger.info(f"  Total Hard SL Exits: {shakeouts + legit_losses}")
    logger.info(f"  SHAKEOUTS (Right but Stopped): {shakeouts}")
    logger.info(f"  LEGIT LOSSES (Wrong direction): {legit_losses}")
    if (shakeouts + legit_losses) > 0:
        logger.info(f"  Shakeout Rate: {(shakeouts/(shakeouts+legit_losses))*100:.1f}%")

    conn.close()

if __name__ == "__main__":
    audit_db()
