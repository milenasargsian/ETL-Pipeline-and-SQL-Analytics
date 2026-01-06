-- View for latest candles
CREATE OR REPLACE VIEW market_etl.v_latest_candles AS
SELECT m.market_symbol,
       c.interval,
       c.open_time,
       c.close_price,
       c.volume
FROM market_etl.candles c
JOIN market_etl.markets m
    ON m.market_id = c.market_id
WHERE c.open_time = (
    SELECT MAX(c2.open_time)
    FROM market_etl.candles c2
    WHERE c2.market_id = c.market_id
      AND c2.interval = c.interval
);

-- View for markets with asset names
CREATE OR REPLACE VIEW market_etl.v_markets_enriched AS
SELECT m.market_id,
       m.market_symbol,
       a1.symbol AS base_asset,
       a2.symbol AS quote_asset,
       m.status
FROM market_etl.markets m
JOIN market_etl.assets a1
    ON a1.asset_id = m.base_asset_id
JOIN market_etl.assets a2
    ON a2.asset_id = m.quote_asset_id;

-- Latest candle data with base and quote asset symbols
SELECT lc.market_symbol,
       me.base_asset,
       me.quote_asset,
       lc.close_price,
       lc.volume
FROM market_etl.v_latest_candles lc
JOIN market_etl.v_markets_enriched me
    ON me.market_symbol = lc.market_symbol;

-- Ranks markets by latest closing price
SELECT lc.market_symbol,
       lc.close_price,
       RANK() OVER (ORDER BY lc.close_price DESC) AS price_rank
FROM market_etl.v_latest_candles lc;

-- Top markets by latest snapshot quote volume
WITH latest_d AS (
    SELECT max(snapshot_date) AS snapshot_date
    FROM market_etl.tickers_24h
)

SELECT m.market_symbol,
       t.quote_volume
FROM market_etl.tickers_24h t
JOIN latest_d
    ON t.snapshot_date = latest_d.snapshot_date
JOIN market_etl.markets m
    ON m.market_id = t.market_id
ORDER BY t.quote_volume DESC NULLS LAST
LIMIT 100;

-- Last 30 daily returns for BTCUSDT
SELECT m.market_symbol,
       c.open_time::date AS day,
       (c.close_price / NULLIF(c.open_price, 0) - 1) AS daily_return
FROM market_etl.candles c
JOIN market_etl.markets m
    ON m.market_id=c.market_id
WHERE m.market_symbol = 'BTCUSDT'
ORDER BY day DESC
LIMIT 30;

-- 30-day rolling volatility
WITH r AS (
    SELECT market_id,
         open_time::date AS day,
         (close_price / NULLIF(open_price,0) - 1) AS ret
    FROM market_etl.candles
)

SELECT m.market_symbol, day,
       stddev_samp(ret) OVER (PARTITION BY r.market_id ORDER BY day ROWS BETWEEN 29 PRECEDING AND CURRENT ROW) AS vol_30d
FROM r
JOIN market_etl.markets m
    ON m.market_id = r.market_id
ORDER BY day DESC
LIMIT 200;

-- Markets by total candle trade_count
SELECT m.market_symbol,
       SUM(c.trade_count) AS trades
FROM market_etl.candles c
JOIN market_etl.markets m
    ON m.market_id=c.market_id
GROUP BY 1
ORDER BY trades DESC
LIMIT 10;

-- Q5: Latest bid/ask spread
WITH latest_d AS (
    SELECT max(snapshot_date) AS snapshot_date
    FROM market_etl.tickers_24h
)

SELECT m.market_symbol,
       (t.ask_price - t.bid_price) AS spread_abs,
       (t.ask_price / NULLIF(t.bid_price,0) - 1) AS spread_pct
FROM market_etl.tickers_24h t
JOIN latest_d
    ON t.snapshot_date = latest_d.snapshot_date
JOIN market_etl.markets m
    ON m.market_id=t.market_id
ORDER BY spread_pct DESC NULLS LAST
LIMIT 20;

-- Trades per hour
SELECT m.market_symbol,
       date_trunc('hour', tr.trade_time) AS hour,
       COUNT(*) AS n_trades,
       SUM(tr.qty) AS base_qty
FROM market_etl.trades tr
JOIN market_etl.markets m
    ON m.market_id=tr.market_id
-- WHERE m.market_symbol = 'BTCUSDT'
GROUP BY 1, 2
ORDER BY hour DESC
LIMIT 50;

-- Buyer-maker ratio by market
SELECT m.market_symbol,
       AVG(CASE WHEN tr.is_buyer_maker THEN 1 ELSE 0 END)::numeric AS buyer_maker_ratio
FROM market_etl.trades tr
JOIN market_etl.markets m
    ON m.market_id=tr.market_id
GROUP BY 1
ORDER BY buyer_maker_ratio DESC
LIMIT 20;

-- Volume spike detection for BTCUSDT (30d avg)
WITH x AS (
    SELECT c.open_time::date AS day, c.volume,
         AVG(c.volume) OVER (ORDER BY c.open_time ROWS BETWEEN 29 PRECEDING AND CURRENT ROW) AS avg30
    FROM market_etl.candles c
    JOIN market_etl.markets m
        ON m.market_id=c.market_id
    WHERE m.market_symbol = 'BTCUSDT'
)

SELECT day,
       volume,
       avg30,
       (volume / NULLIF(avg30, 0)) AS spike
FROM x
ORDER BY spike DESC
LIMIT 20;

-- 7-day returns for latest day across markets
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
       (d.close_price / NULLIF(d.close_7d_ago,0) - 1) AS ret_7d
FROM d
JOIN latest
    ON d.day=latest.day
JOIN market_etl.markets m
    ON m.market_id = d.market_id
ORDER BY ret_7d DESC NULLS LAST
LIMIT 20;

-- Aggregates total traded quantity per market
SELECT m.market_symbol,
       SUM(t.qty) AS total_qty
FROM market_etl.trades t
JOIN market_etl.markets m
    ON m.market_id = t.market_id
GROUP BY m.market_symbol
ORDER BY total_qty DESC;

-- Finds markets without any recorded trades
SELECT m.market_symbol,
       COUNT(t.trade_id) AS trade_count
FROM market_etl.markets m
LEFT JOIN market_etl.trades t ON t.market_id = m.market_id
GROUP BY m.market_symbol
HAVING COUNT(t.trade_id) = 0;


-- Finds markets trading above average volume
SELECT market_symbol,
       total_volume
FROM (
    SELECT
        m.market_symbol,
        SUM(c.volume) AS total_volume
    FROM market_etl.candles c
    JOIN market_etl.markets m ON m.market_id = c.market_id
    GROUP BY m.market_symbol
) s
WHERE total_volume > (
                        SELECT AVG(volume)
                        FROM market_etl.candles
                    );


-- Classifies markets based on trade volume
SELECT m.market_symbol,
       COALESCE(SUM(t.qty), 0) AS total_qty,
       CASE
           WHEN SUM(t.qty) > 100000 THEN 'HIGH'
           WHEN SUM(t.qty) > 10000 THEN 'MEDIUM'
           ELSE 'LOW'
       END AS activity_level
FROM market_etl.markets m
LEFT JOIN market_etl.trades t
    ON t.market_id = m.market_id
GROUP BY m.market_symbol
order by total_qty desc
limit 20;

-- Compares current candle close price to previous one
SELECT m.market_symbol,
       c.open_time,
       c.close_price,
       c.close_price - LAG(c.close_price) OVER (PARTITION BY c.market_id ORDER BY c.open_time) AS price_change
FROM market_etl.candles c
JOIN market_etl.markets m
    ON m.market_id = c.market_id
ORDER BY price_change DESC NULLS LAST
LIMIT 100;

-- Running total of traded quantity per market
SELECT
    m.market_symbol,
    t.trade_time,
    SUM(t.qty) OVER (PARTITION BY t.market_id ORDER BY t.trade_time ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running_volume
FROM market_etl.trades t
JOIN market_etl.markets m
    ON m.market_id = t.market_id
ORDER BY trade_time,
         running_volume DESC
LIMIT 100;

-- Gets latest candle per market
SELECT market_symbol,
        open_time,
        close_price
FROM (
    SELECT
        m.market_symbol,
        c.open_time,
        c.close_price,
        ROW_NUMBER() OVER (
            PARTITION BY m.market_id
            ORDER BY c.open_time DESC
        ) AS rn
    FROM market_etl.candles c
    JOIN market_etl.markets m
        ON m.market_id = c.market_id
) ranked
WHERE rn = 1;

SELECT m.market_symbol,
       DATE_TRUNC('day', c.open_time) AS day,
       SUM(c.volume) AS daily_volume
FROM market_etl.candles c
JOIN market_etl.markets m ON m.market_id = c.market_id
WHERE c.open_time >= now() - INTERVAL '7 days'
GROUP BY 1, 2
ORDER BY day DESC;

-- EXPLAIN ANALYZE
EXPLAIN ANALYZE
SELECT COUNT(*)
FROM market_etl.candles
WHERE open_time >= TIMESTAMPTZ '2025-05-01 00:00:00+00'
  AND open_time < TIMESTAMPTZ '2025-06-01 00:00:00+00';

EXPLAIN ANALYZE
SELECT m.market_symbol,
       AVG(c.close_price) AS avg_close
FROM market_etl.candles c
JOIN market_etl.markets m
    ON m.market_id = c.market_id
GROUP BY 1
ORDER BY avg_close DESC
LIMIT 20;
