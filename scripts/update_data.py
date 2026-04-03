"""
K线数据更新脚本

用于定时更新本地缓存的 K 线数据。

使用方法:
    # 更新指定股票
    python -m scripts.update_data --codes 000001 000002

    # 更新所有已缓存的股票
    python -m scripts.update_data --all --data-source baostock --kl-types DAY

    # 使用 BaoStock 更新
    python -m scripts.update_data --codes 000001 --data-source baostock

    # 更新特定周期
    python -m scripts.update_data --codes 000001 --kl-types DAY WEEK

    # 清除缓存后重新获取
    python -m scripts.update_data --codes 000001 --refresh
"""

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Sequence, Set, Tuple

# ==================== 修复 tushare 权限问题 ====================
# 强制使用 /tmp 目录存储 token，避免云服务器权限问题
os.environ["TUSHARE_PATH"] = "/tmp"

# Monkey patch tushare，在导入时立即生效
import pandas as pd
import tushare as ts

# 保存原始函数
_original_set_token = ts.set_token
_original_pro_api = ts.pro_api


def _patched_set_token(token):
    """修复后的 set_token，使用 /tmp 目录"""
    fp = "/tmp/tk.csv"
    # 先删除旧文件避免权限冲突
    if os.path.exists(fp):
        try:
            os.remove(fp)
        except:
            pass
    df = pd.DataFrame({"token": [token]})
    df.to_csv(fp, index=False)
    ts._Tushare__token = token


def _patched_pro_api(token=None):
    """修复后的 pro_api，从 /tmp 读取 token"""
    if token:
        return _original_pro_api(token=token)
    fp = "/tmp/tk.csv"
    if os.path.exists(fp):
        df = pd.read_csv(fp)
        token = df["token"][0]
        return _original_pro_api(token=token)
    return _original_pro_api()


# 应用 patch
ts.set_token = _patched_set_token
ts.pro_api = _patched_pro_api
# ==================== 修复结束 ====================

try:
    from tqdm import tqdm

    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
    tqdm = lambda x, **kwargs: x

import time

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Common.CEnum import AUTYPE, KL_TYPE
from ChanAnalyzer.database import get_db, init_db, KLineData, get_kl_type_str
from ChanAnalyzer.data_manager import DataManager
from DataAPI.BaoStockAPI import CBaoStock
from DataAPI.TushareAPI import CTushareAPI
from scripts.baostock_utils import get_effective_baostock_trade_date

# 配置日志
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def _log(msg):
    """日志输出（兼容 tqdm）"""
    if HAS_TQDM:
        tqdm.write(msg)
    else:
        logger.info(msg)


def normalize_baostock_code(code: str) -> str:
    """将裸股票代码转换为 BaoStock 所需格式。"""
    code = code.strip().lower()
    if "." in code:
        return code
    if code.startswith(("sh", "sz")) and len(code) == 8:
        return f"{code[:2]}.{code[2:]}"
    if code.startswith(("6", "9")):
        return f"sh.{code}"
    return f"sz.{code}"


def get_api_class(data_source: str):
    if data_source == "baostock":
        return CBaoStock
    return CTushareAPI


def normalize_date_str(date_str: str) -> str:
    """将数据库/API中的日期字符串标准化为 YYYY-MM-DD。"""
    value = str(date_str).strip()
    if not value:
        raise ValueError("日期不能为空")

    if " " in value:
        value = value.split(" ", 1)[0]

    value = value.replace("/", "-")
    if len(value) == 8 and value.isdigit():
        value = f"{value[:4]}-{value[4:6]}-{value[6:8]}"

    return value


def parse_date_str(date_str: str) -> date:
    """解析日期字符串。"""
    return datetime.strptime(normalize_date_str(date_str), "%Y-%m-%d").date()


def format_date(dt: date) -> str:
    return dt.strftime("%Y-%m-%d")


def compress_missing_dates(missing_dates: Sequence[date]) -> List[Tuple[str, str]]:
    """将离散缺失交易日压缩成连续区间。"""
    if not missing_dates:
        return []

    sorted_dates = sorted(missing_dates)
    ranges: List[Tuple[str, str]] = []
    range_start = sorted_dates[0]
    prev = sorted_dates[0]

    for current in sorted_dates[1:]:
        if (current - prev).days == 1:
            prev = current
            continue
        ranges.append((format_date(range_start), format_date(prev)))
        range_start = prev = current

    ranges.append((format_date(range_start), format_date(prev)))
    return ranges


def get_trading_days(start_date: str, end_date: str, data_source: str) -> List[date]:
    """获取指定区间内的交易日列表。"""
    start = normalize_date_str(start_date)
    end = normalize_date_str(end_date)

    if data_source == "baostock":
        import baostock as bs

        rs = bs.query_trade_dates(start_date=start, end_date=end)
        if rs.error_code != "0":
            raise ValueError(f"BaoStock 获取交易日失败: {rs.error_msg}")

        trade_days: List[date] = []
        while rs.error_code == "0" and rs.next():
            trade_date, is_trading_day = rs.get_row_data()
            if is_trading_day == "1":
                trade_days.append(parse_date_str(trade_date))
        return trade_days

    pro = ts.pro_api()
    df = pro.trade_cal(
        exchange="",
        start_date=start.replace("-", ""),
        end_date=end.replace("-", ""),
        is_open="1",
    )
    if df is None or df.empty:
        return []

    df = df.sort_values("cal_date")
    return [parse_date_str(cal_date) for cal_date in df["cal_date"].tolist()]


def get_latest_trade_date(data_source: str, lookback_days: int = 30) -> str:
    """获取最近一个交易日。"""
    if data_source == "baostock":
        return get_effective_baostock_trade_date(
            lookback_days=max(lookback_days, 90),
            log_fn=_log,
        )

    end_day = datetime.now().date()
    start_day = end_day - timedelta(days=lookback_days)
    trading_days = get_trading_days(
        format_date(start_day), format_date(end_day), data_source
    )
    if not trading_days:
        raise ValueError("未获取到最近交易日")
    return format_date(trading_days[-1])


def get_cached_day_dates(code: str) -> List[date]:
    """获取单只股票已缓存的日线交易日。"""
    with get_db() as db:
        rows = (
            db.query(KLineData.date)
            .filter(
                KLineData.code == code,
                KLineData.kl_type == get_kl_type_str(KL_TYPE.K_DAY),
            )
            .order_by(KLineData.timestamp)
            .all()
        )
    return [parse_date_str(row[0]) for row in rows]


def get_cached_stock_codes(kl_type: Optional[KL_TYPE] = None) -> List[str]:
    """获取已缓存的股票代码，可按周期过滤。"""
    with get_db() as db:
        query = db.query(KLineData.code).distinct()
        if kl_type is not None:
            query = query.filter(KLineData.kl_type == get_kl_type_str(kl_type))
        codes = query.all()
        return [c[0] for c in codes]


def find_missing_day_ranges(
    cached_dates: Sequence[date],
    trading_days: Sequence[date],
) -> Tuple[List[Tuple[str, str]], int]:
    """根据缓存日期与交易日历，找出缺失区间。"""
    if not cached_dates:
        return [], 0

    sorted_cached = sorted(set(cached_dates))
    cached_set = set(sorted_cached)
    start_day = sorted_cached[0]
    end_day = sorted_cached[-1]

    missing_dates = [
        trade_day
        for trade_day in trading_days
        if start_day <= trade_day <= end_day and trade_day not in cached_set
    ]
    return compress_missing_dates(missing_dates), len(missing_dates)


def build_fetcher(code: str, data_source: str):
    """构建统一的数据源获取函数。"""
    api_class = get_api_class(data_source)
    api_code = normalize_baostock_code(code) if data_source == "baostock" else code

    def fetcher(_code, kl_type, begin, end):
        api = api_class(
            code=api_code,
            k_type=kl_type,
            begin_date=begin,
            end_date=end,
            autype=AUTYPE.NONE,  # 不复权
        )
        return api.get_kl_data()

    return fetcher


def backfill_missing_ranges(
    code: str,
    kl_type: KL_TYPE,
    missing_ranges: Sequence[Tuple[str, str]],
    data_manager: DataManager,
    fetcher,
) -> int:
    """按缺失区间补齐历史数据。"""
    total_rows = 0
    kl_type_str = get_kl_type_str(kl_type)

    for begin_date, end_date in missing_ranges:
        cached_data = data_manager._get_from_cache(
            code, kl_type_str, begin_date, end_date
        )
        new_data_list = list(fetcher(code, kl_type, begin_date, end_date))
        if not new_data_list:
            logger.warning(
                f"[{code} {kl_type_str}] 缺失区间无返回数据: {begin_date} ~ {end_date}"
            )
            continue
        data_manager._merge_and_save(
            code,
            kl_type_str,
            cached_data,
            new_data_list,
            begin_date,
            end_date,
        )
        total_rows += len(new_data_list)

    return total_rows


def get_codes_with_missing_day_data(
    data_source: str,
) -> Tuple[List[str], Dict[str, Dict[str, object]]]:
    """找出已缓存且存在日线缺口的股票。"""
    codes = get_cached_stock_codes(KL_TYPE.K_DAY)
    if not codes:
        return [], {}

    missing_info: Dict[str, Dict[str, object]] = {}
    latest_trade_date = get_latest_trade_date(data_source)

    earliest_dates: List[date] = []
    cached_dates_map: Dict[str, List[date]] = {}
    for code in codes:
        cached_dates = get_cached_day_dates(code)
        if not cached_dates:
            continue
        cached_dates_map[code] = cached_dates
        earliest_dates.append(min(cached_dates))

    if not earliest_dates:
        return [], {}

    trading_days = get_trading_days(
        format_date(min(earliest_dates)), latest_trade_date, data_source
    )
    for code, cached_dates in cached_dates_map.items():
        missing_ranges, missing_days = find_missing_day_ranges(
            cached_dates, trading_days
        )
        if missing_days == 0:
            continue
        missing_info[code] = {
            "missing_ranges": missing_ranges,
            "missing_days": missing_days,
        }

    return list(missing_info.keys()), missing_info


def update_stock(
    code: str,
    kl_types: List[KL_TYPE],
    data_manager: DataManager,
    data_source: str = "tushare",
    refresh: bool = False,
    verbose: bool = False,
    only_missing: bool = False,
    precomputed_missing: Optional[Dict[str, Dict[str, object]]] = None,
) -> dict:
    """
    更新单只股票的数据

    Returns:
        更新结果统计
    """
    result = {
        "code": code,
        "data_source": data_source,
        "success": True,
        "kl_types": {},
        "error": None,
    }
    fetcher = build_fetcher(code, data_source)

    for kl_type in kl_types:
        kl_type_str = get_kl_type_str(kl_type)

        try:
            # 清除缓存（如果需要）
            if refresh and verbose:
                _log(f"[{code} {kl_type_str}] 清除旧缓存...")
                data_manager.clear_cache(code, kl_type)
            elif refresh:
                data_manager.clear_cache(code, kl_type)

            if verbose:
                _log(f"[{code} {kl_type_str}] 开始更新...")

            missing_ranges: List[Tuple[str, str]] = []
            missing_days = 0
            fetched_rows = 0

            if only_missing and not refresh and kl_type == KL_TYPE.K_DAY:
                if precomputed_missing and code in precomputed_missing:
                    missing_ranges = list(
                        precomputed_missing[code].get("missing_ranges", [])
                    )
                    missing_days = int(precomputed_missing[code].get("missing_days", 0))
                else:
                    cached_dates = get_cached_day_dates(code)
                    if cached_dates:
                        latest_trade_date = get_latest_trade_date(data_source)
                        trading_days = get_trading_days(
                            format_date(min(cached_dates)),
                            latest_trade_date,
                            data_source,
                        )
                        missing_ranges, missing_days = find_missing_day_ranges(
                            cached_dates, trading_days
                        )

                if missing_ranges:
                    fetched_rows = backfill_missing_ranges(
                        code=code,
                        kl_type=kl_type,
                        missing_ranges=missing_ranges,
                        data_manager=data_manager,
                        fetcher=fetcher,
                    )
                    logger.info(
                        f"[{code} {kl_type_str}] 补缺完成: {missing_days} 个交易日, {len(missing_ranges)} 个区间"
                    )
                else:
                    logger.info(f"[{code} {kl_type_str}] 无缺失数据，跳过")
            else:
                # 获取昨天到今天的数据（增量更新）
                end_date = datetime.now().strftime("%Y-%m-%d")
                start_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
                data_manager.get_kl_data(
                    code=code,
                    kl_type=kl_type,
                    begin_date=start_date,
                    end_date=end_date,
                    data_src_fetcher=fetcher,
                )

                if only_missing and kl_type != KL_TYPE.K_DAY:
                    logger.info(
                        f"[{code} {kl_type_str}] 当前仅 DAY 支持历史补缺，已回退为普通增量更新"
                    )

            # 获取缓存信息
            info = data_manager.get_cache_info(code, kl_type)
            result["kl_types"][kl_type_str] = {
                "count": info.get("count", 0),
                "first_date": info.get("first_date"),
                "last_date": info.get("last_date"),
                "missing_days": missing_days,
                "missing_ranges": missing_ranges,
                "fetched_rows": fetched_rows,
            }
            logger.info(f"[{code} {kl_type_str}] 更新成功: {info.get('count', 0)} 条")

        except Exception as e:
            logger.error(f"[{code} {kl_type_str}] 更新失败: {e}")
            result["kl_types"][kl_type_str] = {"error": str(e)}
            result["success"] = False

    return result


def get_all_cached_stocks() -> List[str]:
    """获取所有已缓存的股票代码"""
    return get_cached_stock_codes()


def update_all_stocks(
    kl_types: List[KL_TYPE],
    data_manager: DataManager,
    data_source: str = "tushare",
    refresh: bool = False,
    only_missing: bool = False,
):
    """更新所有已缓存的股票"""
    precomputed_missing: Dict[str, Dict[str, object]] = {}
    if only_missing and not refresh:
        codes, precomputed_missing = get_codes_with_missing_day_data(data_source)
    else:
        codes = get_all_cached_stocks()

    if not codes:
        if only_missing and not refresh:
            logger.warning("没有检测到存在日线缺口的已缓存股票")
        else:
            logger.warning("没有已缓存的股票，请先使用 --codes 指定股票代码")
        return

    if only_missing and not refresh:
        logger.info(f"开始补齐 {len(codes)} 只存在日线缺口的股票...")
    else:
        logger.info(f"开始更新 {len(codes)} 只股票...")

    success_count = 0
    fail_count = 0

    # 使用进度条
    iterator = codes
    if HAS_TQDM:
        iterator = tqdm(codes, desc="更新进度", unit="股")

    for code in iterator:
        result = update_stock(
            code,
            kl_types,
            data_manager,
            data_source,
            refresh,
            only_missing=only_missing,
            precomputed_missing=precomputed_missing,
        )

        if result["success"]:
            success_count += 1
        else:
            fail_count += 1

        # API 频率限制：每只股票之间延迟 0.2 秒
        # 这样每分钟最多约 300 次请求，低于 Tushare 的 500 次限制
        time.sleep(0.2)

    logger.info(f"\n更新完成: 成功 {success_count}, 失败 {fail_count}")


def main():
    parser = argparse.ArgumentParser(description="K线数据更新脚本")

    parser.add_argument("--codes", nargs="+", help="指定股票代码，如: 000001 000002")
    parser.add_argument("--all", action="store_true", help="更新所有已缓存的股票")
    parser.add_argument(
        "--kl-types",
        nargs="+",
        default=["DAY", "WEEK"],
        choices=["DAY", "WEEK", "MON", "30M", "15M", "5M", "1M"],
        help="K线周期类型 (默认: DAY WEEK)",
    )
    parser.add_argument("--refresh", action="store_true", help="清除缓存后重新获取")
    parser.add_argument("--verbose", action="store_true", help="显示详细日志")
    parser.add_argument(
        "--data-source",
        default="tushare",
        choices=["tushare", "baostock"],
        help="数据源 (默认: tushare)",
    )
    parser.add_argument(
        "--only-missing", action="store_true", help="只补齐已缓存日线中的历史缺失区间"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # 初始化数据库
    init_db()

    # 创建 DataManager 实例
    data_manager = DataManager()

    # 解析周期类型
    kl_type_map = {
        "1M": KL_TYPE.K_1M,
        "5M": KL_TYPE.K_5M,
        "15M": KL_TYPE.K_15M,
        "30M": KL_TYPE.K_30M,
        "DAY": KL_TYPE.K_DAY,
        "WEEK": KL_TYPE.K_WEEK,
        "MON": KL_TYPE.K_MON,
    }
    kl_types = [kl_type_map[t] for t in args.kl_types]

    api_class = get_api_class(args.data_source)
    api_class.do_init()
    try:
        # 执行更新
        if args.all:
            update_all_stocks(
                kl_types,
                data_manager,
                args.data_source,
                args.refresh,
                args.only_missing,
            )
        elif args.codes:
            for code in args.codes:
                result = update_stock(
                    code,
                    kl_types,
                    data_manager,
                    args.data_source,
                    args.refresh,
                    only_missing=args.only_missing,
                )
                print(f"\n{code} 更新结果:")
                for kl_type_str, info in result["kl_types"].items():
                    if "error" in info:
                        print(f"  {kl_type_str}: 失败 - {info['error']}")
                    else:
                        extra = ""
                        if args.only_missing:
                            extra = (
                                f", 缺失 {info.get('missing_days', 0)} 天"
                                f", 区间 {len(info.get('missing_ranges', []))} 个"
                            )
                        print(
                            f"  {kl_type_str}: {info['count']} 条 "
                            f"({info['first_date']} ~ {info['last_date']}){extra}"
                        )
        else:
            parser.print_help()
            print("\n提示: 使用 --codes 指定股票，或 --all 更新所有已缓存股票")
    finally:
        api_class.do_close()


if __name__ == "__main__":
    main()
