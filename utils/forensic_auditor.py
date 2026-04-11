import asyncio
import aiohttp
import sqlite3
import json
import logging
import os
import random
from datetime import datetime
from typing import Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

GAMMA_API   = "https://gamma-api.polymarket.com"
CLOB_API    = "https://clob.polymarket.com"
DB_PATHS    = ["data/bot_g_paper.db", "bot_g_paper.db"]
CONCURRENCY = 5 # Slow down to avoid 403 detection
HEADERS     = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Origin': 'https://polymarket.com',
    'Referer': 'https://polymarket.com/',
}

def ts_to_unix(ts: str) -> int:
    dt_str = ts.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(dt_str)
    except:
        dt = datetime.strptime(dt_str.split('.')[0], "%Y-%m-%d %H:%M:%S")
    return int(dt.timestamp())

async def fetch_token_id(session: aiohttp.ClientSession, row: dict) -> Optional[str]:
    cid = row.get("market_id")
    direction = row.get("direction")
    if not cid: return None
    try:
        url = f"{GAMMA_API}/markets"
        async with session.get(url, params={"conditionId": cid}, timeout=10) as resp:
            if resp.status == 200:
                data = await resp.json()
                if not data: return None
                tokens = data[0].get("clobTokenIds", [])
                if isinstance(tokens, str): tokens = json.loads(tokens)
                if direction == "long" and len(tokens) > 0: return tokens[0]
                if direction == "short" and len(tokens) > 1: return tokens[1]
    except: pass
    return None

async def fetch_price_history(session: aiohttp.ClientSession, token_id: str, ts_entry: str, ts_exit: str) -> list[dict]:
    url = f"{CLOB_API}/prices-history"
    params = {"market": token_id, "interval": "1m", "fidelity": 10}
    # Add small human-like delay
    await asyncio.sleep(random.uniform(0.1, 0.5))
    try:
        async with session.get(url, params=params, timeout=15) as resp:
            if resp.status == 200:
                data = await resp.json()
                history = data.get("history", [])
                start = ts_to_unix(ts_entry)
                end = ts_to_unix(ts_exit)
                return [p for p in history if start <= p["t"] <= end]
            else:
                logger.error(f"CLOB 403 hit. Status: {resp.status}")
    except Exception as e:
        logger.error(f"Error fetching history: {e}")
    return []

async def process_row(session: aiohttp.ClientSession, sem: asyncio.Semaphore, row: dict) -> dict:
    async with sem:
        token_id = await fetch_token_id(session, row)
        if not token_id: return {**row, "error": "no_token_id"}
        history = await fetch_price_history(session, token_id, row["ts_entry"], row["ts_exit"])
        if not history: return {**row, "error": "no_history"}
        
        prices = [float(p["p"]) for p in history]
        if not prices: return {**row, "error": "empty_prices"}
        
        entry_odds = float(row["entry_odds"])
        if row["direction"] == "long":
            deepest_point = min(prices)
            mae = entry_odds - deepest_point
        else:
            deepest_point = max(prices)
            mae = deepest_point - entry_odds
            
        return {**row, "token_id": token_id, "mae": round(mae, 4), "deepest_point": round(deepest_point, 4)}

async def run_audit():
    all_rows = []
    for db_path in DB_PATHS:
        if not os.path.exists(db_path): continue
        logger.info(f"Loading from {db_path}...")
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT slug, market_id, ts_entry, ts_exit, direction, entry_odds, exit_odds, exit_reason FROM trades WHERE exit_reason IN ('hard_sl_hit', 'profit_ratchet_exit')")
            all_rows.extend([dict(r) for r in cur.fetchall()])
            conn.close()
        except: continue

    logger.info(f"Stealth audit of {len(all_rows)} trades starting...")
    sem = asyncio.Semaphore(CONCURRENCY)
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        tasks = [process_row(session, sem, row) for row in all_rows]
        results = await asyncio.gather(*tasks)

    with open("full_mae_audit.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    
    successful = [r for r in results if 'error' not in r]
    logger.info(f"Audit final result: {len(successful)} successful.")

if __name__ == "__main__":
    asyncio.run(run_audit())
