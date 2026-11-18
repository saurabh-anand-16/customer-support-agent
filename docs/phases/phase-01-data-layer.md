# Phase 1: data layer

**Status:** Done

## Goal
Real product data, policy rules as tables, and synthetic orders with delivery dates placed around each window edge, all in one SQLite database.

## Files
| File | Action | Why |
| --- | --- | --- |
| `data/raw/amazon.csv` | Added (untouched) | Kaggle Amazon sales data |
| `scripts/config.py` | Created | Today's date, seed, sizes, paths |
| `scripts/01_clean_products.py` | Created | Convert text to proper types, keep one copy of each product |
| `scripts/02_build_policy_tables.py` | Created | Policy types, category mapping, refund timelines, policy facts |
| `scripts/03_generate_orders.py` | Created | Customers, orders, items, existing returns |
| `scripts/04_build_db.py` | Created | Build and verify `returns_agent.db` |
| `schema.sql` | Created | Tables and the day-counting views |
| `data/clean/*.csv` | Generated | Every table the scripts write |
| `returns_agent.db` | Generated, not committed | The database |

## What it does
- 1,465 raw rows become 1,351 distinct products.
- Six Amazon policy types are stored as rules, with window lengths and allowed resolutions as data.
- **The category-to-policy mapping is our inference, not Amazon's.** 211 category paths are mapped by ordered rules, each with a confidence: 7 high, 9 low. The reviewer checked the low ones and accepted them.
- 400 customers, 2,500 orders, 3,281 items (2,749 delivered, 270 shipped, 110 processing, 152 cancelled) and 73 existing returns, all synthetic. Delivery dates are placed on purpose around each product's window edge, and the generator guarantees items on the last day and just past it for every policy type.
- Output is identical on every run (fixed seed).

## How it is checked
`04_build_db.py` checks foreign keys, compares the SQL window arithmetic with an independent Python calculation for all delivered items, and checks that each scenario label matches its date. A test fails if a regenerated dataset misses a boundary.

## Known gaps and open questions
- The Kaggle dataset's licence has not been checked.
- `customers.account_standing` is a plain flag, not a rule from Amazon.

## Done when
The four scripts run clean from scratch and the checks pass. Yes.
