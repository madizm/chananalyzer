# feedback-service

Standalone Go service for public thumbs up / thumbs down feedback.

## Environment

- `PORT`: listen port, default `8081`
- `DB_PATH`: SQLite database path, default `./feedback.db`
- `SITE_DIR`: directory containing `buy_scan_results.json` and `sell_scan_results.json`, default `../dist/publish`
- `TRUST_PROXY_HEADERS`: set to `1` to use `X-Forwarded-For`

## Endpoints

- `GET /api/feedback/summary?codes=000001,600519&device_id=<uuid>`
- `POST /api/feedback/vote`
- `GET /healthz`

## Run

```bash
go run .
```

## Deploy

Run behind `nginx` and keep the service bound to `127.0.0.1`.
