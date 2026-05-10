"""
TdxLib.tqcenter 调用示例。

运行前提：
1. 已启动并登录通达信客户端。
2. 能加载 TPythClient.dll。默认会依次尝试：
   - tq.initialize(..., dll_path=...) 显式传入路径
   - 环境变量 TPYTHCLIENT_DLL
   - D:\\tdx_new\\PYPlugins\\TPythClient.dll
   - 项目根目录下的 TPythClient.dll
3. 代码格式使用 6 位代码 + 市场后缀，例如 688318.SH、000001.SZ。

示例：
    python docs/tdx_api/tdxdata_test.py kline --code 688318.SH --count 5
    python docs/tdx_api/tdxdata_test.py more --code 880544.SH --fields ZTGPNum
    python docs/tdx_api/tdxdata_test.py stock-info --code 688318.SH
    python docs/tdx_api/tdxdata_test.py stock-list --market 31 --list-type 1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from TdxLib.tqcenter import tq  # noqa: E402


DEFAULT_CODE = "688318.SH"
DEFAULT_BLOCK_CODE = "880544.SH"


def _split_fields(raw_fields: str) -> list[str]:
    if not raw_fields:
        return []
    return [field.strip() for field in raw_fields.split(",") if field.strip()]


def _print_result(data: Any) -> None:
    """友好打印 TDX 接口返回值。"""
    if isinstance(data, dict):
        for key, value in data.items():
            print(f"\n[{key}]")
            if isinstance(value, pd.DataFrame):
                print(value.tail())
            else:
                print(json.dumps(value, ensure_ascii=False, indent=2))
        return

    if isinstance(data, list):
        print(json.dumps(data[:20], ensure_ascii=False, indent=2))
        print(f"\nTotal: {len(data)}")
        return

    print(data)


def get_kline(args: argparse.Namespace) -> dict:
    """获取 K 线数据，返回 {字段名: DataFrame}。"""
    return tq.get_market_data(
        field_list=_split_fields(args.fields),
        stock_list=args.codes,
        period=args.period,
        start_time=args.start,
        end_time=args.end,
        count=args.count,
        dividend_type=args.dividend,
        fill_data=not args.no_fill,
    )


def get_more(args: argparse.Namespace) -> dict:
    """获取更多行情扩展字段。"""
    return tq.get_more_info(
        stock_code=args.code,
        field_list=_split_fields(args.fields),
    )


def get_stock_info(args: argparse.Namespace) -> dict:
    """获取基础信息和基础财务字段。"""
    return tq.get_stock_info(
        stock_code=args.code,
        field_list=_split_fields(args.fields),
    )


def get_stock_list(args: argparse.Namespace) -> list:
    """获取股票、ETF、板块等列表。"""
    return tq.get_stock_list(
        market=args.market,
        list_type=args.list_type,
    )


def get_sector_stocks(args: argparse.Namespace) -> list:
    """获取板块成分股，支持板块代码/名称或自定义板块简称。"""
    return tq.get_stock_list_in_sector(
        block_code=args.block,
        block_type=args.block_type,
        list_type=args.list_type,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TDX 数据接口调用示例")
    parser.add_argument(
        "--dll-path",
        default="",
        help="TPythClient.dll 路径；为空时使用 TdxLib.tqcenter 的默认查找顺序",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    kline = subparsers.add_parser("kline", help="调用 tq.get_market_data")
    kline.add_argument("--code", dest="codes", action="append", default=None)
    kline.add_argument("--period", default="1d")
    kline.add_argument("--start", default="")
    kline.add_argument("--end", default="")
    kline.add_argument("--count", type=int, default=5)
    kline.add_argument("--dividend", choices=["none", "front", "back"], default="none")
    kline.add_argument("--fields", default="Open,High,Low,Close,Volume")
    kline.add_argument("--no-fill", action="store_true")
    kline.set_defaults(func=get_kline)

    more = subparsers.add_parser("more", help="调用 tq.get_more_info")
    more.add_argument("--code", default=DEFAULT_BLOCK_CODE)
    more.add_argument("--fields", default="ZTGPNum")
    more.set_defaults(func=get_more)

    stock_info = subparsers.add_parser("stock-info", help="调用 tq.get_stock_info")
    stock_info.add_argument("--code", default=DEFAULT_CODE)
    stock_info.add_argument("--fields", default="")
    stock_info.set_defaults(func=get_stock_info)

    stock_list = subparsers.add_parser("stock-list", help="调用 tq.get_stock_list")
    stock_list.add_argument("--market", default="5")
    stock_list.add_argument("--list-type", type=int, default=1)
    stock_list.set_defaults(func=get_stock_list)

    sector = subparsers.add_parser("sector-stocks", help="调用 tq.get_stock_list_in_sector")
    sector.add_argument("--block", default="880081.SH")
    sector.add_argument("--block-type", type=int, choices=[0, 1], default=0)
    sector.add_argument("--list-type", type=int, default=1)
    sector.set_defaults(func=get_sector_stocks)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "kline" and args.codes is None:
        args.codes = [DEFAULT_CODE]

    try:
        tq.initialize(str(Path(__file__).resolve()), dll_path=args.dll_path)
        result = args.func(args)
        _print_result(result)
        return 0
    finally:
        tq.close()


if __name__ == "__main__":
    raise SystemExit(main())
