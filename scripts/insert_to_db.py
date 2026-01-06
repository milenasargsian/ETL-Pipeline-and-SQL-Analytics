# scripts/insert_to_db.py
from __future__ import annotations

import json
import psycopg2
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLEAN_DIR = ROOT / "data" / "clean"

DB_CFG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "final",
    "user": "postgres",
    "password": "postgres",
}


def load_json(path: Path):
    """
        Centralizes file reading
        Avoids duplicated I/O code
    """
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    conn = psycopg2.connect(**DB_CFG)
    cur = conn.cursor()

    # ASSETS
    assets = load_json(CLEAN_DIR / "assets.json")

    cur.executemany(
        """
        INSERT INTO market_etl.assets(symbol)
        VALUES (%s)
        ON CONFLICT (symbol) DO NOTHING
        """,
        [(a["symbol"],) for a in assets],
    )

    cur.execute("SELECT asset_id, symbol FROM market_etl.assets")
    asset_map = {symbol: asset_id for asset_id, symbol in cur.fetchall()}

    print(f"Assets loaded: {len(asset_map)}")

    # MARKETS
    markets = load_json(CLEAN_DIR / "markets.json")

    market_payload = []
    for m in markets:
        if m["base_symbol"] not in asset_map or m["quote_symbol"] not in asset_map:
            continue

        market_payload.append(
            (
                m["exchange"],
                asset_map[m["base_symbol"]],
                asset_map[m["quote_symbol"]],
                m["market_symbol"],
                m["status"],
            )
        )

    cur.executemany(
        """
        INSERT INTO market_etl.markets (
            exchange,
            base_asset_id,
            quote_asset_id,
            market_symbol,
            status
        )
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (market_symbol) DO NOTHING
        """,
        market_payload,
    )

    cur.execute("SELECT market_id, market_symbol FROM market_etl.markets")
    market_map = {symbol: market_id for market_id, symbol in cur.fetchall()}

    print(f"Markets loaded: {len(market_map)}")

    # CANDLES
    total_candles = 0
    skipped_candles = 0

    for f in CLEAN_DIR.glob("candles_*.json"):
        rows = load_json(f)
        payload = []

        for r in rows:
            mid = market_map.get(r["market_symbol"])
            if not mid:
                skipped_candles += 1
                continue

            payload.append({**r, "market_id": mid})

        if payload:
            cur.executemany(
                """
                INSERT INTO market_etl.candles (
                    market_id,
                    interval,
                    open_time,
                    close_time,
                    open_price,
                    high_price,
                    low_price,
                    close_price,
                    volume,
                    quote_volume,
                    trade_count,
                    taker_buy_base_volume,
                    taker_buy_quote_volume
                )
                VALUES (
                    %(market_id)s,
                    %(interval)s,
                    %(open_time)s,
                    %(close_time)s,
                    %(open_price)s,
                    %(high_price)s,
                    %(low_price)s,
                    %(close_price)s,
                    %(volume)s,
                    %(quote_volume)s,
                    %(trade_count)s,
                    %(taker_buy_base_volume)s,
                    %(taker_buy_quote_volume)s
                )
                ON CONFLICT DO NOTHING
                """,
                payload,
            )

        total_candles += len(payload)

    print(f"Candles inserted: {total_candles}")
    print(f"Candles skipped (unknown market): {skipped_candles}")

    # TRADES
    total_trades = 0
    skipped_trades = 0

    for f in CLEAN_DIR.glob("trades_*.json"):
        rows = load_json(f)
        payload = []

        for r in rows:
            mid = market_map.get(r["market_symbol"])
            if not mid:
                skipped_trades += 1
                continue

            payload.append({**r, "market_id": mid})

        if payload:
            cur.executemany(
                """
                INSERT INTO market_etl.trades (
                    market_id,
                    trade_id,
                    trade_time,
                    price,
                    qty,
                    quote_qty,
                    is_buyer_maker
                )
                VALUES (
                    %(market_id)s,
                    %(trade_id)s,
                    %(trade_time)s,
                    %(price)s,
                    %(qty)s,
                    %(quote_qty)s,
                    %(is_buyer_maker)s
                )
                ON CONFLICT DO NOTHING
                """,
                payload,
            )

        total_trades += len(payload)

    print(f"Trades inserted: {total_trades}")
    print(f"Trades skipped (unknown market): {skipped_trades}")

    # TICKERS 24H
    tickers = load_json(CLEAN_DIR / "tickers_24h.json")

    payload = []
    skipped_tickers = 0

    for r in tickers:
        mid = market_map.get(r["market_symbol"])
        if not mid:
            skipped_tickers += 1
            continue

        payload.append({**r, "market_id": mid})

    if payload:
        cur.executemany(
            """
            INSERT INTO market_etl.tickers_24h (
                market_id,
                snapshot_date,
                price_change,
                price_change_percent,
                weighted_avg_price,
                prev_close_price,
                last_price,
                last_qty,
                bid_price,
                bid_qty,
                ask_price,
                ask_qty,
                open_price,
                high_price,
                low_price,
                volume,
                quote_volume,
                open_time,
                close_time,
                first_id,
                last_id,
                count
            )
            VALUES (
                %(market_id)s,
                %(snapshot_date)s,
                %(price_change)s,
                %(price_change_percent)s,
                %(weighted_avg_price)s,
                %(prev_close_price)s,
                %(last_price)s,
                %(last_qty)s,
                %(bid_price)s,
                %(bid_qty)s,
                %(ask_price)s,
                %(ask_qty)s,
                %(open_price)s,
                %(high_price)s,
                %(low_price)s,
                %(volume)s,
                %(quote_volume)s,
                %(open_time)s,
                %(close_time)s,
                %(first_id)s,
                %(last_id)s,
                %(count)s
            )
            ON CONFLICT DO NOTHING
            """,
            payload,
        )

    print(f"Tickers inserted: {len(payload)}")
    print(f"Tickers skipped (unknown market): {skipped_tickers}")

    conn.commit()
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()


"""
    2026-01-06
    Assets loaded: 732
    Markets loaded: 3452
    Candles inserted: 1390000
    Candles skipped (unknown market): 0
    Trades inserted: 100000
    Trades skipped (unknown market): 0
    Tickers inserted: 3452
    Tickers skipped (unknown market): 3
"""