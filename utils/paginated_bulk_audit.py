import urllib.request
import sqlite3
import json
import logging
import time
import sys

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

DB_PATH = "data/bot_g_paper.db"
GAMMA_URL = "https://gamma-api.polymarket.com/markets"

def fetch_page(offset):
    """Fetch a page of 500 closed markets from Gamma API."""
    url = f"{GAMMA_URL}?limit=500&offset={offset}&closed=true&order=endDate&ascending=false"
    logger.info(f"Fetching page: offset={offset}")
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            if resp.getcode() != 200:
                logger.error(f"API Error {resp.getcode()} at offset {offset}")
                return None
            return json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        logger.error(f"Network error at offset {offset}: {e}")
        return None

def get_winner_index(market_data):
    """Identifies the winning index based on outcomePrices."""
    try:
        prices = market_data.get("outcomePrices")
        if isinstance(prices, str):
            prices = json.loads(prices)
        if not prices:
            return None
        for i, p in enumerate(prices):
            if str(p) in ("1", "1.0", 1, 1.0):
                return i
        return None
    except:
        return None

def bulk_audit():
    logger.info(f"Starting Paginated Bulk Audit for {DB_PATH}")
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    # 1. Get all unique slugs from DB that are resolved but need true outcome
    trades = conn.execute("""
        SELECT id, slug, direction 
        FROM trades 
        WHERE resolved = 1 
          AND (outcome_index IS NULL OR outcome_index = -1)
    """).fetchall()
    
    if not trades:
        logger.info("No trades found in DB requiring audit.")
        conn.close()
        return

    db_slugs = {t['slug']: t['id'] for t in trades}
    logger.info(f"Searching for resolutions for {len(db_slugs)} unique slugs.")

    # 2. Paginate through Gamma until we find our slugs or hit a limit
    offset = 0
    max_pages = 10 # 5,000 markets total
    found_count = 0
    
    results_map = {} # slug -> winner_index

    while offset < (max_pages * 500) and len(results_map) < len(db_slugs):
        page_data = fetch_page(offset)
        if not page_data:
            break
        
        for market in page_data:
            m_slug = market.get('slug')
            if m_slug in db_slugs:
                w_idx = get_winner_index(market)
                if w_idx is not None:
                    results_map[m_slug] = w_idx
                    found_count += 1
        
        logger.info(f"Progress: Found {found_count}/{len(db_slugs)} resolutions...")
        
        if len(page_data) < 500:
            logger.info("Reached end of available API data.")
            break
            
        offset += 500
        time.sleep(0.5) # Be kind to API

    # 3. Update DB with findings
    updates = 0
    for slug, w_idx in results_map.items():
        conn.execute("UPDATE trades SET outcome_index = ? WHERE slug = ?", (w_idx, slug))
        updates += 1
    
    conn.commit()
    logger.info(f"Audit Complete. Updated {updates} trades with real resolution data.")

    # 4. Final Final Statistics
    # winner_idx 0 = UP/LONG, 1 = DOWN/SHORT
    logger.info("\n=== FINAL SHAKEOUT REPORT (TRUTH-MATCHED) ===")
    
    stats = conn.execute("""
        SELECT 
            SUM(CASE WHEN exit_reason = 'hard_sl_hit' AND 
                ((direction = 'long' AND outcome_index = 0) OR (direction = 'short' AND outcome_index = 1)) 
                THEN 1 ELSE 0 END) as shakeouts,
            SUM(CASE WHEN exit_reason = 'hard_sl_hit' AND 
                ((direction = 'long' AND outcome_index = 1) OR (direction = 'short' AND outcome_index = 0)) 
                THEN 1 ELSE 0 END) as legit_losses,
            SUM(CASE WHEN exit_reason = 'take_profit_hit' THEN 1 ELSE 0 END) as winners
        FROM trades 
        WHERE outcome_index IS NOT NULL
    """).fetchone()

    s = stats['shakeouts'] or 0
    l = stats['legit_losses'] or 0
    w = stats['winners'] or 0
    
    total_sl = s + l
    
    logger.info(f"  Real Winners (TP Hit): {w}")
    logger.info(f"  Total Hard SL Exits:  {total_sl}")
    logger.info(f"  └─ SHAKEOUTS (Right but Stopped): {s}")
    logger.info(f"  └─ LEGIT LOSSES (Wrong Direction): {l}")
    
    if total_sl > 0:
        logger.info(f"  Shakeout Rate: {(s/total_sl)*100:.1f}%")
        logger.info(f"  Directional Failure Rate: {(l/total_sl)*100:.1f}%")

    conn.close()

if __name__ == "__main__":
    bulk_audit()
