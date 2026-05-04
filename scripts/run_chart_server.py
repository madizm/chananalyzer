from __future__ import annotations

import argparse
from pathlib import Path
import sys

import uvicorn

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def main() -> None:
    parser = argparse.ArgumentParser(description="启动 ChanAnalyzer 在线画图服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    uvicorn.run("web.chart_server:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
