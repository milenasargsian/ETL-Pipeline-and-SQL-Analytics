# ETL-Pipeline-and-SQL-Analytics

## Overview

This project implements a production-style ETL pipeline that ingests cryptocurrency market data from the Binance Spot API, cleans and normalizes it, and loads it into a partitioned PostgreSQL data warehouse optimized for analytical queries.

### Data Model
#### Schemas & Tables

All tables are stored under the market_etl schema.

Dimension Tables

* assets — unique crypto assets (BTC, ETH, USDT, …)
* markets — trading pairs (BTC/USDT, ETH/USDT, …)


Fact Tables

* candles — OHLCV data (partitioned by open_time)
* trades — aggregated trades (partitioned by trade_time)
* tickers_24h — daily 24h market snapshots

Time-based partitions are created monthly for high-performance queries.

### Configuration
All pipeline behavior is controlled via config.json:

```
{
  "base_url": "https://api.binance.com",  // Binance Spot REST API
  "quote_asset": "USDT",                  // Filters markets (USDT pairs only)
  "top_n_markets": 20,                    // Selects top markets by 24h volume
  "kline_interval": "5m",                 // 5m → 288 rows/day
  "start_date_utc": "2025-05-01",
  "end_date_utc": null, 
  "trades_per_market": 5000                // Trade volume cap per market
}
```


(Binance has: ~3000 total symbols, ~400–600 USDT pairs, filter top 20 markets sort by quoteVolume (24h))

### Order to run the project 

1.   scraper.py
2.   clean_data.py
3.   schema.sql
4.   insert_to_db.py
5.   queries.sql


### The project includes:

* 2 reusable SQL views
* 10 analytical SQL queries demonstrating:
    * JOINs (INNER, LEFT)
    * Aggregations (COUNT, SUM, AVG)
    * Window functions (ROW_NUMBER, LAG, running totals)
    * Subqueries and CTEs
    * CASE logic and NULL handling
    * Date/time functions
    * Partition-aware filtering
* 2 queries analyzed with EXPLAIN ANALYZE
