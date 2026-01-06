# scripts/clean_data.py

"""
    Transforms raw Binance API responses into normalized, schema-aligned datasets.
    Positional arrays are converted into named fields, timestamps are standardized to UTC,
    and dimension data is deduplicated to ensure referential integrity during database loading.
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Any


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
CLEAN_DIR = ROOT / "data" / "clean"

CLEAN_DIR.mkdir(parents=True, exist_ok=True)


def ts_ms_to_utc(ms: int) -> str:
    """
        Binance timestamps are milliseconds since epoch
        Database expects TIMESTAMPTZ
    """
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def load_json(path: Path) -> Any:
    """
        Centralizes file reading
        Avoids duplicated I/O code
    """
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def clean_assets_markets(exchange_info: Dict[str, Any]) -> Dict[str, List[Dict]]:
    """
        Returns normalized assets and markets
    """
    assets = {}  # ensures uniqueness
    markets = []

    for s in exchange_info["symbols"]:
        base = s["baseAsset"]
        quote = s["quoteAsset"]

        assets.setdefault(base, {"symbol": base})
        assets.setdefault(quote, {"symbol": quote})

        markets.append({
            "exchange": "binance",
            "base_symbol": base,
            "quote_symbol": quote,
            "market_symbol": s["symbol"],
            "status": s["status"].lower()
        })

    return {
        "assets": list(assets.values()),
        "markets": markets
    }


def clean_klines(market_symbol: str, interval: str, klines: List[list]) -> List[Dict]:
    """
        Converts into explicit, named fields
        Removes positional ambiguity
        Matches DB schema exactly
    """
    rows = []
    for k in klines:
        rows.append({
            "market_symbol": market_symbol,
            "interval": interval,
            "open_time": ts_ms_to_utc(k[0]),
            "close_time": ts_ms_to_utc(k[6]),
            "open_price": k[1],
            "high_price": k[2],
            "low_price": k[3],
            "close_price": k[4],
            "volume": k[5],
            "quote_volume": k[7],
            "trade_count": k[8],
            "taker_buy_base_volume": k[9],
            "taker_buy_quote_volume": k[10],
        })
    return rows


def clean_trades(market_symbol: str, trades: List[Dict]) -> List[Dict]:
    """
        Converts into explicit, named fields
        Matches DB schema
    """
    rows = []
    for t in trades:
        rows.append({
            "market_symbol": market_symbol,
            "trade_id": t["a"],
            "trade_time": ts_ms_to_utc(t["T"]),
            "price": t["p"],
            "qty": t["q"],
            "quote_qty": t.get("Q"),
            "is_buyer_maker": t["m"]
        })
    return rows


def clean_ticker(snapshot_date: str, ticker: List[Dict]) -> List[Dict]:
    """
        Converts rolling 24h stats into daily snapshots
        Acts as a slowly changing fact table
    """
    rows = []
    for t in ticker:
        rows.append({
            "market_symbol": t["symbol"],
            "snapshot_date": snapshot_date,
            "price_change": t.get("priceChange"),
            "price_change_percent": t.get("priceChangePercent"),
            "weighted_avg_price": t.get("weightedAvgPrice"),
            "prev_close_price": t.get("prevClosePrice"),
            "last_price": t.get("lastPrice"),
            "last_qty": t.get("lastQty"),
            "bid_price": t.get("bidPrice"),
            "bid_qty": t.get("bidQty"),
            "ask_price": t.get("askPrice"),
            "ask_qty": t.get("askQty"),
            "open_price": t.get("openPrice"),
            "high_price": t.get("highPrice"),
            "low_price": t.get("lowPrice"),
            "volume": t.get("volume"),
            "quote_volume": t.get("quoteVolume"),
            "open_time": ts_ms_to_utc(t["openTime"]) if t.get("openTime") else None,
            "close_time": ts_ms_to_utc(t["closeTime"]) if t.get("closeTime") else None,
            "first_id": t.get("firstId"),
            "last_id": t.get("lastId"),
            "count": t.get("count")
        })
    return rows


def main():
    exchange_info = load_json(RAW_DIR / "exchange_info.json")
    assets_markets = clean_assets_markets(exchange_info)

    (CLEAN_DIR / "assets.json").write_text(json.dumps(assets_markets["assets"], indent=2))
    (CLEAN_DIR / "markets.json").write_text(json.dumps(assets_markets["markets"], indent=2))

    # process klines
    for f in RAW_DIR.glob("klines_*_*.json"):
        _, interval, symbol, _ = f.stem.split("_", 3)
        kl = load_json(f)
        out = clean_klines(symbol, interval, kl)
        (CLEAN_DIR / f"candles_{symbol}_{interval}.json").write_text(json.dumps(out))

    # process trades
    for f in RAW_DIR.glob("aggTrades_*.json"):
        symbol = f.stem.split("_")[1]
        tr = load_json(f)
        out = clean_trades(symbol, tr)
        (CLEAN_DIR / f"trades_{symbol}.json").write_text(json.dumps(out))

    # process ticker
    ticker_file = next(RAW_DIR.glob("ticker_24h_*.json"))
    snapshot_date = ticker_file.stem.split("_")[-1]
    ticker = load_json(ticker_file)
    out = clean_ticker(snapshot_date, ticker)
    (CLEAN_DIR / "tickers_24h.json").write_text(json.dumps(out))


if __name__ == "__main__":
    main()
