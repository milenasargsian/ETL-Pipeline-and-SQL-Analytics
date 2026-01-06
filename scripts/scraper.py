# scripts/scraper.py

"""
    Scraper implements a controlled, rate-limited historical data ingestion pipeline for Binance spot markets.
    Markets are selected based on liquidity, data is paginated safely using exchange timestamps,
    and all raw data is stored immutably for reproducibility and downstream ETL processing.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
CONFIG_PATH = ROOT / "config.json"

RAW_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class Cfg:
    base_url: str
    quote_asset: str
    top_n_markets: int
    kline_interval: str
    start_date_utc: str
    end_date_utc: Optional[str]
    trades_per_market: int
    sleep_sec: float


def load_cfg() -> Cfg:
    """
        Reads config.json
        Applies defaults
        Converts types safely
    """
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        c = json.load(f)

    return Cfg(
        base_url=c["base_url"].rstrip("/"),
        quote_asset=c.get("quote_asset", "USDT"),
        top_n_markets=int(c.get("top_n_markets", 30)),
        kline_interval=c.get("kline_interval", "1m"),
        start_date_utc=c.get("start_date_utc", "2025-05-01"),
        end_date_utc=c.get("end_date_utc"),
        trades_per_market=int(c.get("trades_per_market", 100_000)),
        sleep_sec=float(c.get("sleep_sec", 0.2)),  # Controls API throttling
    )


def get_json(url: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """
        Single place for HTTP logic
        Returns parsed JSON
    """
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def utc_ms(date_str: str) -> int:
    """
        Converts YYYY-MM-DD → milliseconds
        Since Binance API requires timestamps in milliseconds
    """
    return int(
        datetime.strptime(date_str, "%Y-%m-%d")
        .replace(tzinfo=timezone.utc)
        .timestamp() * 1000
    )


def now_ms() -> int:
    """
        Returns current UTC timestamp in milliseconds
        Used when end_date_utc = null.
    """
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def now_utc_date() -> str:
    """
        Generates a snapshot date for filenames like 20260105
    """
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def fetch_exchange_info(cfg: Cfg) -> Dict[str, Any]:
    """
        Returns
            All trading symbols
            Base/quote assets
            Market status
        Used for dimension tables
    """
    return get_json(f"{cfg.base_url}/api/v3/exchangeInfo")


def fetch_ticker_24h(cfg: Cfg) -> List[Dict[str, Any]]:
    """
        Returns
            24-hour rolling statistics
        Used to rank markets by liquidity
    """
    return get_json(f"{cfg.base_url}/api/v3/ticker/24hr")


def select_top_markets(exchange_info: Dict[str, Any], ticker: List[Dict[str, Any]],
                       quote_asset: str, top_n: int) -> List[str]:
    """
        Filter eligible symbols, attach liquidity metric, sort and select top_n markets
    """
    eligible = {
        s["symbol"]
        for s in exchange_info["symbols"]
        if s["status"] == "TRADING"
        and s["quoteAsset"] == quote_asset
        and s.get("isSpotTradingAllowed", True)
    }

    rows = []
    for t in ticker:
        sym = t["symbol"]
        if sym in eligible:
            rows.append((sym, float(t.get("quoteVolume", 0) or 0)))

    rows.sort(key=lambda x: x[1], reverse=True)
    return [s for s, _ in rows[:top_n]]


def fetch_klines(cfg: Cfg, symbol: str, start_ms: int, end_ms: int) -> List[list]:
    """
        Paginates through historical candles (Binance limit is 1000 rows per request)
        Moves forward using open time
    """
    url = f"{cfg.base_url}/api/v3/klines"
    out: List[list] = []
    cur = start_ms

    while cur < end_ms:
        params = {
            "symbol": symbol,
            "interval": cfg.kline_interval,
            "startTime": cur,
            "endTime": end_ms,
            "limit": 1000,
        }
        data = get_json(url, params)
        if not data:
            break

        out.extend(data)
        cur = data[-1][0] + 1 # Prevents duplicate candles and infinite loops
        time.sleep(cfg.sleep_sec)

    return out


def fetch_agg_trades(cfg: Cfg, symbol: str, start_ms: int, end_ms: int) -> List[Dict[str, Any]]:
    """
        Uses trade timestamp (T)
        Predictable data volume
        No accidental millions of rows
    """
    url = f"{cfg.base_url}/api/v3/aggTrades"
    out: List[Dict[str, Any]] = []
    cur = start_ms

    while cur < end_ms and len(out) < cfg.trades_per_market:
        params = {
            "symbol": symbol,
            "startTime": cur,
            "endTime": end_ms,
            "limit": 1000,
        }
        data = get_json(url, params)
        if not data:
            break

        out.extend(data)
        cur = data[-1]["T"] + 1
        time.sleep(cfg.sleep_sec)

    return out[: cfg.trades_per_market]


def main():
    cfg = load_cfg()

    start_ms = utc_ms(cfg.start_date_utc)
    end_ms = utc_ms(cfg.end_date_utc) if cfg.end_date_utc else now_ms()
    snapshot = now_utc_date()

    print("Fetching exchange info...")
    exchange_info = fetch_exchange_info(cfg)
    (RAW_DIR / "exchange_info.json").write_text(json.dumps(exchange_info, indent=2))

    print("Fetching 24h ticker...")
    ticker = fetch_ticker_24h(cfg)
    (RAW_DIR / f"ticker_24h_{snapshot}.json").write_text(json.dumps(ticker, indent=2))

    # Select markets
    symbols = select_top_markets(
        exchange_info, ticker, cfg.quote_asset, cfg.top_n_markets
    )

    print(f"Selected {len(symbols)} markets")

    # Fetch candles per market
    for i, sym in enumerate(symbols, 1):
        print(f"[{i}/{len(symbols)}] klines {cfg.kline_interval} {sym}")
        kl = fetch_klines(cfg, sym, start_ms, end_ms)
        (RAW_DIR / f"klines_{cfg.kline_interval}_{sym}_{snapshot}.json").write_text(
            json.dumps(kl)
        )

    # Fetch trades per market
    for i, sym in enumerate(symbols, 1):
        print(f"[{i}/{len(symbols)}] aggTrades {sym}")
        tr = fetch_agg_trades(cfg, sym, start_ms, end_ms)
        (RAW_DIR / f"aggTrades_{sym}_{snapshot}.json").write_text(json.dumps(tr))


if __name__ == "__main__":
    main()
