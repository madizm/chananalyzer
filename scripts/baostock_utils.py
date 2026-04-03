from datetime import date, datetime, timedelta
from typing import Callable, Dict, List, Optional, Set

from DataAPI.BaoStockAPI import CBaoStock


def _query_trade_days(start_day: date, end_day: date) -> List[str]:
    import baostock as bs

    rs = bs.query_trade_dates(
        start_date=start_day.strftime("%Y-%m-%d"),
        end_date=end_day.strftime("%Y-%m-%d"),
    )
    if rs.error_code != "0":
        raise ValueError(f"BaoStock 获取交易日失败: {rs.error_msg}")

    trading_days: List[str] = []
    while rs.error_code == "0" and rs.next():
        trade_date, is_trading_day = rs.get_row_data()
        if is_trading_day == "1":
            trading_days.append(trade_date)
    return trading_days


def query_all_stock_rows(day: str) -> List[List[str]]:
    import baostock as bs

    rs = bs.query_all_stock(day=day)
    if rs.error_code != "0":
        raise ValueError(f"BaoStock 获取股票列表失败: {rs.error_msg}")

    rows: List[List[str]] = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    return rows


def query_stock_industry_rows() -> List[List[str]]:
    import baostock as bs

    rs = bs.query_stock_industry()
    if rs.error_code != "0":
        raise ValueError(f"BaoStock 获取行业列表失败: {rs.error_msg}")

    rows: List[List[str]] = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    return rows


def query_stock_basic_row(code: str) -> List[str]:
    import baostock as bs

    rs = bs.query_stock_basic(code=code)
    if rs.error_code != "0":
        raise ValueError(f"BaoStock 获取股票基本信息失败: {code} {rs.error_msg}")
    if not rs.next():
        return []
    return rs.get_row_data()


def _is_a_share_candidate(code: str) -> bool:
    if not code or "." not in code:
        return False
    market, symbol = code.split(".", 1)
    if market not in {"sh", "sz"}:
        return False
    if not symbol.isdigit():
        return False
    if symbol.startswith(("688", "8", "4", "5", "9")):
        return False
    return True


def get_a_share_stock_rows(day: str) -> List[List[str]]:
    """获取指定交易日的 A 股股票列表，过滤指数和其他非股票代码。"""
    industry_codes: Set[str] = set()
    for row in query_stock_industry_rows():
        code = row[1] if len(row) > 1 else ""
        if _is_a_share_candidate(code):
            industry_codes.add(code)

    basic_cache: Dict[str, bool] = {}
    filtered_rows: List[List[str]] = []
    for row in query_all_stock_rows(day):
        code = row[0] if len(row) > 0 else ""
        if not _is_a_share_candidate(code):
            continue
        if code in industry_codes:
            filtered_rows.append(row)
            continue

        if code not in basic_cache:
            basic_row = query_stock_basic_row(code)
            basic_cache[code] = len(basic_row) >= 6 and basic_row[4] == "1"
        if basic_cache[code]:
            filtered_rows.append(row)

    return filtered_rows


def get_effective_baostock_trade_date(
    lookback_days: int = 90,
    fallback_window_days: int = 180,
    max_years_back: int = 5,
    log_fn: Optional[Callable[[str], None]] = None,
    reference_date: Optional[date] = None,
) -> str:
    """返回 BaoStock 实际可用的最近交易日，必要时向过去回退。"""
    CBaoStock.do_init()

    system_day = reference_date or datetime.now().date()
    earliest_allowed = system_day - timedelta(days=max_years_back * 365)
    window_end = system_day
    window_start = max(earliest_allowed, system_day - timedelta(days=lookback_days))
    first_window = (window_start, window_end)
    fallback_used = False

    while window_end >= earliest_allowed:
        trading_days = _query_trade_days(window_start, window_end)
        latest_trade_date = trading_days[-1] if trading_days else None
        for trade_date in reversed(trading_days):
            if query_all_stock_rows(trade_date):
                used_fallback_trade_date = fallback_used or (
                    latest_trade_date is not None and trade_date != latest_trade_date
                )
                if log_fn:
                    if (
                        used_fallback_trade_date
                        or (window_start, window_end) != first_window
                    ):
                        log_fn(
                            "System date "
                            f"{system_day:%Y-%m-%d} unavailable, fallback to BaoStock trade date {trade_date}"
                        )
                    else:
                        log_fn(f"BaoStock effective trade date: {trade_date}")
                return trade_date

        fallback_used = True
        next_end = window_start - timedelta(days=1)
        if next_end < earliest_allowed:
            break
        window_end = next_end
        window_start = max(
            earliest_allowed, window_end - timedelta(days=fallback_window_days - 1)
        )

    raise ValueError(
        "BaoStock 未找到可用交易日: "
        f"system_date={system_day:%Y-%m-%d}, "
        f"initial_window={first_window[0]:%Y-%m-%d}~{first_window[1]:%Y-%m-%d}, "
        f"searched_back_to={earliest_allowed:%Y-%m-%d}"
    )
