# feedback-service

Standalone Go service for public thumbs up / thumbs down feedback.

## Environment

- `PORT`: listen port, default `8081`
- `DB_PATH`: SQLite database path, default `./feedback.db`
- `SITE_DIR`: directory containing `buy_scan_results.json` and `sell_scan_results.json`, default `../dist/publish`
- `TRUST_PROXY_HEADERS`: set to `1` to use `X-Forwarded-For`

## Endpoints

- `POST /api/feedback/summary` with JSON body `{"signals":[{"code":"000001","signal_date":"2026/03/24"}]}`
- `POST /api/feedback/vote` with JSON body `{"code":"000001","signal_date":"2026/03/24","action":"up","device_id":"device-12345678"}`
- `GET /healthz`

## Run

```bash
go run .
```

## Deploy

Run behind `nginx` and keep the service bound to `127.0.0.1`.
