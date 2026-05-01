"""
Market Tape Logger
==================
A passive, zero-cost "Dashcam" for all Polymarket WebSocket price ticks.
Writes one CSV row per price update received from the live WebSocket stream
for all subscribed markets (not just open positions).

Features:
  - Daily rotating files: logs/market_tape_YYYY-MM-DD.csv
  - Auto-cleanup of files older than `retention_days`
  - Thread-safe writes via threading.Lock
  - No extra API calls — reads only from the existing WebSocket stream
"""

import csv
import glob
import logging
import os
import threading
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# CSV column headers
_HEADERS = [
    "timestamp",
    "market_slug",
    "asset",
    "poly_mid",
    "poly_bid",
    "poly_ask",
    "binance_mom",
]


class MarketTapeLogger:
    """
    Appends one row to a daily CSV file for every WebSocket price tick
    received from PolymarketFeed._handle().

    Usage (in main.py):
        tape = MarketTapeLogger(log_dir="logs", retention_days=7)
        poly_feed._tape_logger = tape
        poly_feed._binance_ref  = binance_feed
    """

    def __init__(self, log_dir: str = "logs", retention_days: int = 7):
        self._log_dir        = log_dir
        self._retention_days = retention_days
        self._lock           = threading.Lock()
        self._current_date   = None   # tracks the date of the open file
        self._file           = None   # open file handle
        self._writer         = None   # csv.writer for the open file

        os.makedirs(log_dir, exist_ok=True)
        self._cleanup_old_files()
        self._rotate_if_needed()      # open today's file immediately

    # ── Public API ─────────────────────────────────────────────────────────────

    def log_tick(
        self,
        slug: str,
        asset: str,
        poly_mid: float,
        bid: float,
        ask: float,
        binance_mom: float,
    ) -> None:
        """Write one tick row to the CSV. Called from PolymarketFeed._handle()."""
        now = datetime.utcnow()
        with self._lock:
            self._rotate_if_needed(now)
            try:
                self._writer.writerow([
                    now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],  # ms precision
                    slug,
                    asset,
                    round(poly_mid, 4),
                    round(bid, 4),
                    round(ask, 4),
                    round(binance_mom, 6),
                ])
                self._file.flush()   # ensure data survives a crash
            except Exception as e:
                logger.warning("[MarketTape] Write error: %s", e)

    def close(self) -> None:
        """Flush and close the current CSV file cleanly on bot shutdown."""
        with self._lock:
            if self._file:
                try:
                    self._file.close()
                except Exception:
                    pass
                self._file   = None
                self._writer = None

    # ── Internal Helpers ───────────────────────────────────────────────────────

    def _rotate_if_needed(self, now: datetime = None) -> None:
        """Open a new hourly file if the hour has changed since last write."""
        if now is None:
            now = datetime.utcnow()
        
        # Use year-month-day_hour as the unique key for rotation
        current_hour_key = now.strftime("%Y-%m-%d_%H")

        if self._current_date == current_hour_key:
            return  # same hour — nothing to do

        # Close previous file if open
        if self._file:
            try:
                self._file.close()
            except Exception:
                pass

        # Open new hourly file
        filename  = f"market_tape_{current_hour_key}.csv"
        filepath  = os.path.join(self._log_dir, filename)
        is_new    = not os.path.exists(filepath)

        self._file         = open(filepath, "a", newline="", buffering=1)
        self._writer       = csv.writer(self._file)
        self._current_date = current_hour_key

        if is_new:
            self._writer.writerow(_HEADERS)   # write header on brand new files
            self._file.flush()

        logger.info("[MarketTape] Logging ticks to %s", filepath)

    def _cleanup_old_files(self) -> None:
        """Delete market_tape_*.csv files older than retention_days."""
        cutoff = datetime.utcnow().date() - timedelta(days=self._retention_days)
        pattern = os.path.join(self._log_dir, "market_tape_*.csv")
        for path in glob.glob(pattern):
            fname = os.path.basename(path)
            # Extract date from filename: market_tape_YYYY-MM-DD_HH.csv or market_tape_YYYY-MM-DD.csv
            try:
                # Remove prefix and extension
                date_part = fname.replace("market_tape_", "").replace(".csv", "")
                
                # Take only the date part (YYYY-MM-DD) even if it has _HH
                date_only = date_part.split("_")[0]
                
                file_date = datetime.strptime(date_only, "%Y-%m-%d").date()
                if file_date < cutoff:
                    os.remove(path)
                    logger.info("[MarketTape] Deleted old tape: %s", fname)
            except (ValueError, OSError):
                pass   # not our file format — skip silently
