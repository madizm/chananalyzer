# public-web

Standalone static frontend for publishing scan results on the public internet.

## Runtime Contract

The site expects these files to be hosted alongside the built assets:

- `buy_scan_results.json`
- `sell_scan_results.json`
- `manifest.json`

Each stock item in the buy/sell payloads includes:

- `current_price`
- `amount`: latest daily turnover amount in yi yuan
- `turnover_rate`: latest daily turnover rate in percent

It also expects a feedback API:

- `POST /api/feedback/summary` with JSON body `{"signals":[{"code":"000001","signal_date":"2026/03/24"}]}`
- `POST /api/feedback/vote`

The page defaults the signal-date filter to the last 3 days including today.

## Local Preview

Serve the directory with any static file server. Example:

```bash
python -m http.server 8080 -d public-web
```

If your feedback service runs elsewhere, edit [`assets/config.js`](/Users/madizm/tools/chananalyzer/public-web/assets/config.js).
