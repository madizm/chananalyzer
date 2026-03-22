# public-web

Standalone static frontend for publishing scan results on the public internet.

## Runtime Contract

The site expects these files to be hosted alongside the built assets:

- `buy_scan_results.json`
- `sell_scan_results.json`
- `manifest.json`

It also expects a feedback API:

- `GET /api/feedback/summary?codes=...&device_id=...`
- `POST /api/feedback/vote`

## Local Preview

Serve the directory with any static file server. Example:

```bash
python -m http.server 8080 -d public-web
```

If your feedback service runs elsewhere, edit [`assets/config.js`](/Users/madizm/tools/chananalyzer/public-web/assets/config.js).
