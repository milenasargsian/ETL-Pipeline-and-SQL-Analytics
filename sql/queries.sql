-- sql/queries.sql

-- Q1: Top markets by latest snapshot quote volume
WITH latest_d AS (
    SELECT max(snapshot_date) AS d
    FROM market_etl.tickers_24h
)

SELECT m.market_symbol,
       t.quote_volume
FROM market_etl.tickers_24h t
JOIN latest_d
    ON t.snapshot_date = latest_d.d
JOIN market_etl.markets m
    ON m.market_id = t.market_id
ORDER BY t.quote_volume DESC NULLS LAST
LIMIT 10;

-- Q2: Last 30 daily returns for BTCUSDT
SELECT c.open_time::date AS day,
       (c.close_price / NULLIF(c.open_price,0) - 1) AS daily_return
FROM market_etl.candles c
JOIN market_etl.markets m
    ON m.market_id=c.market_id
WHERE m.market_symbol = 'BTCUSDT'
  AND c.interval = '1d'
ORDER BY day DESC
LIMIT 30;

-- Q3: 30-day rolling volatility (window)
WITH r AS (
    SELECT market_id,
         open_time::date AS day,
         (close_price / NULLIF(open_price,0) - 1) AS ret
    FROM market_etl.candles
    WHERE interval = '1d'
)

SELECT m.market_symbol, day,
       stddev_samp(ret) OVER (PARTITION BY r.market_id ORDER BY day ROWS BETWEEN 29 PRECEDING AND CURRENT ROW) AS vol_30d
FROM r
JOIN market_etl.markets m
    ON m.market_id=r.market_id
ORDER BY day DESC
LIMIT 200;

-- Q4: Markets by total candle trade_count
SELECT m.market_symbol,
       SUM(c.trade_count) AS trades
FROM market_etl.candles c
JOIN market_etl.markets m
    ON m.market_id=c.market_id
-- WHERE c.interval = '1d'
GROUP BY 1
ORDER BY trades DESC
LIMIT 10;

-- Q5: Latest bid/ask spread
WITH latest_d AS (
    SELECT max(snapshot_date) AS d
    FROM market_etl.tickers_24h
)

SELECT m.market_symbol,
       (t.ask_price - t.bid_price) AS spread_abs,
       (t.ask_price / NULLIF(t.bid_price,0) - 1) AS spread_pct
FROM market_etl.tickers_24h t
JOIN latest_d
    ON t.snapshot_date = latest_d.d
JOIN market_etl.markets m
    ON m.market_id=t.market_id
ORDER BY spread_pct DESC NULLS LAST
LIMIT 20;

-- Q6: Trades per hour for BTCUSDT
SELECT date_trunc('hour', tr.trade_time) AS hour,
       COUNT(*) AS n_trades,
       SUM(tr.qty) AS base_qty
FROM market_etl.trades tr
JOIN market_etl.markets m ON m.market_id=tr.market_id
WHERE m.market_symbol = 'BTCUSDT'
GROUP BY 1
ORDER BY hour DESC
LIMIT 48;

-- Q7: Buyer-maker ratio by market
SELECT m.market_symbol,
       AVG(CASE WHEN tr.is_buyer_maker THEN 1 ELSE 0 END)::numeric AS buyer_maker_ratio
FROM market_etl.trades tr
JOIN market_etl.markets m
    ON m.market_id=tr.market_id
GROUP BY 1
ORDER BY buyer_maker_ratio DESC NULLS LAST
LIMIT 20;

-- Q8: Show base/quote assets
SELECT m.market_symbol,
       ab.symbol AS base_asset,
       aq.symbol AS quote_asset
FROM market_etl.markets m
JOIN market_etl.assets ab
    ON ab.asset_id=m.base_asset_id
JOIN market_etl.assets aq
    ON aq.asset_id=m.quote_asset_id
ORDER BY m.market_symbol
LIMIT 50;

-- Q9: Volume spike detection for BTCUSDT (30d avg)
WITH x AS (
    SELECT c.open_time::date AS day, c.volume,
         AVG(c.volume) OVER (ORDER BY c.open_time ROWS BETWEEN 29 PRECEDING AND CURRENT ROW) AS avg30
    FROM market_etl.candles c
    JOIN market_etl.markets m
        ON m.market_id=c.market_id
    WHERE m.market_symbol = 'BTCUSDT'
      AND c.interval = '1d'
)

SELECT day,
       volume,
       avg30,
       (volume / NULLIF(avg30, 0)) AS spike
FROM x
ORDER BY spike DESC NULLS LAST
LIMIT 20;

-- Q10: 7-day returns for latest day across markets
WITH d AS (
    SELECT market_id,
         open_time::date AS day,
         close_price,
         LAG(close_price, 7) OVER (PARTITION BY market_id ORDER BY open_time) AS close_7d_ago
    FROM market_etl.candles
),
latest AS (
    SELECT max(open_time::date) AS day
    FROM market_etl.candles
)

SELECT m.market_symbol,
       (d.close_price / NULLIF(d.close_7d_ago,0)-1) AS ret_7d
FROM d
JOIN latest
    ON d.day=latest.day
JOIN market_etl.markets m
    ON m.market_id=d.market_id
ORDER BY ret_7d DESC NULLS LAST
LIMIT 20;

-- EXPLAIN ANALYZE #1: partition pruning candles (Jan 2025)
EXPLAIN ANALYZE
SELECT COUNT(*)
FROM market_etl.candles
WHERE open_time >= TIMESTAMPTZ '2025-05-01 00:00:00+00'
  AND open_time < TIMESTAMPTZ '2025-06-01 00:00:00+00';

-- EXPLAIN ANALYZE #2: join+agg
EXPLAIN ANALYZE
SELECT m.market_symbol,
       AVG(c.close_price) AS avg_close
FROM market_etl.candles c
JOIN market_etl.markets m
    ON m.market_id = c.market_id
GROUP BY 1
ORDER BY avg_close DESC
LIMIT 20;
