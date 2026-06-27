# TdxQuant Official Page Capture

Captured from the official TdxQuant documentation on 2026-06-27.

This file stores the documentation facts used while designing the broader
TDX/QMT datasource coverage matrix. It is intentionally a compact memory of
source pages and conclusions, not a full copy of the official documentation.

Coverage matrix:
`docs/references/tdxquant-interface-coverage.md`.

## Source Pages And Assets

- TdxQuant overview: <https://help.tdx.com.cn/quant/>
- HTTP call mode: <https://help.tdx.com.cn/quant/docs/markdown/mindoc-1hdhbmi50d038.html>
- Official example article: <https://help.tdx.com.cn/quant/docs/markdown/gzh0122inweixinwenz/gzh20260302wzlz.html>
- VuePress route key for the example article: `v-2250a6c4`
- VuePress asset containing the example article content at capture time:
  <https://help.tdx.com.cn/quant/assets/js/36.0fa91836.js>

The VuePress asset hash is not a stable public API. Use the page URL above as
the durable reference and only use the asset path as evidence for this capture.

## HTTP Calling Mode

The official HTTP mode uses local JSON-RPC over:

```text
POST http://127.0.0.1:17709/
```

The `method` field is the TdxQuant function name and `params` contains that
function's parameters. This supports the datasource design where TDX native HTTP
remains inside Python and NestJS consumes normalized `/v1` endpoints.

## `get_real_time_data` Finding

`get_real_time_data` was found in the official example article, but it is not
shown there as a native `tq.get_real_time_data(...)` API.

In the captured example, `get_real_time_data(stock_code)` is a user-defined
Python helper inside `订阅Handlebar.py`. The helper fetches recent close and
volume data by calling `tq.get_market_data(...)`.

Datasource implication:

- Do not list `get_real_time_data` as an official TdxQuant API in the coverage
  matrix.
- If it appears in examples, classify it as `example-helper-not-api`.
- For real-time quote behavior, use official APIs such as
  `get_market_snapshot`, `get_pricevol`, `subscribe_hq`, and
  `get_market_data` depending on the workflow.

## Official API Navigation Facts

The current documentation navigation and pages identify these non-trading data
families as useful datasource coverage targets:

- Market data: `get_market_data`, `get_market_snapshot`, `get_pricevol`,
  `get_benchmark_data`.
- Security metadata and reference data: `get_stock_list`,
  `get_valid_stock_codes`, `get_stock_info`, `get_more_info`,
  `get_match_stkinfo`, `get_relation`, `get_ipo_info`, `get_gb_info`,
  `get_gb_info_by_date`, `get_divid_factors`.
- Sectors and categories: `get_sector_list`, `get_stock_list_in_sector`.
- Trading calendar: `get_trading_dates`.
- ETF, convertible bond, and related instrument data: `get_kzz_info`,
  `get_cb_info`, `get_trackzs_etf_info`.
- Finance and report data: `get_financial_data`,
  `get_financial_data_by_date`, `get_gp_one_data`, `get_gpjy_value`,
  `get_gpjy_value_by_date`, `get_bkjy_value`, `get_bkjy_value_by_date`,
  `get_scjy_value`, `get_scjy_value_by_date`, `get_report_data`.
- Formula data and execution: `formula_format_data`, `formula_set_data`,
  `formula_set_data_info`, `formula_get_data`, `formula_get_all`,
  `formula_get_info`, `formula_zb`, `formula_xg`, `formula_exp`,
  `formula_process_mul_zb`, `formula_process_mul_xg`,
  `formula_process_mul_exp`.
- Subscription runtime: `subscribe_hq`, `unsubscribe_hq`,
  `get_subscribe_hq_stock_list`.

## Boundary Decision

The datasource should aim to cover non-trading data APIs as a complete data
adapter layer. Trading, account, order, cancel, and other execution interfaces
remain outside the market datasource boundary and require a separate trading
service design.

Client-control, file, message, refresh, and mutation-style utility methods are
not ordinary read-data APIs. Treat them as admin-only or do-not-expose unless a
separate operator workflow is designed.

## Phase 2 Normalized Endpoint Capture

Implemented after this capture using the reviewed official pages and coverage
matrix:

| Normalized endpoint | Primary TDX methods |
| --- | --- |
| `/v1/reference/relations/query` | `get_relation` |
| `/v1/reference/ipo/query` | `get_ipo_info` |
| `/v1/reference/share-capital/query` | `get_gb_info`, `get_gb_info_by_date` |
| `/v1/reference/dividend-factors/query` | `get_divid_factors` |
| `/v1/instruments/convertible-bonds/query` | `get_kzz_info`, compatibility `get_cb_info` |
| `/v1/instruments/tracking-etfs/query` | `get_trackzs_etf_info` |

The root-level `TDX.md` and `QMT.md` snapshots were removed as stale. Future
shape changes should be captured here or in the coverage matrix after checking
current official pages. Convertible-bond and ETF live return shapes still need
Windows smoke confirmation before backend product code relies on narrow fields.
