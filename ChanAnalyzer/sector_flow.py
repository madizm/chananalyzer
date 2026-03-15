"""
板块资金流向分析模块

通过申万行业指数涨跌幅统计板块资金流向
"""
import os
from typing import Dict, List, Tuple
from datetime import datetime, timedelta
import pandas as pd


# 缓存
_flow_cache = None
_flow_cache_time = None


def get_sector_flow(days: int = 5) -> Dict[str, float]:
    """
    获取板块资金流向

    通过申万一级行业指数的涨跌幅来估算资金流向。

    Args:
        days: 统计天数，默认 5 天

    Returns:
        {板块名称: 累计涨跌幅百分比}
        例如: {'电子': 5.2, '计算机': 3.8, ...}

    Examples:
        >>> flows = get_sector_flow(days=5)
        >>> for ind, flow in sorted(flows.items(), key=lambda x: x[1], reverse=True)[:5]:
        ...     print(f"{ind}: {flow:+.2f}%")
    """
    global _flow_cache, _flow_cache_time

    # 检查缓存（1小时内有效）
    if _flow_cache and _flow_cache_time:
        if datetime.now() - _flow_cache_time < timedelta(hours=1):
            return _flow_cache

    import tushare as ts

    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        print("警告: 未设置 TUSHARE_TOKEN，无法获取板块资金流向")
        return {}

    ts.set_token(token)
    pro = ts.pro_api()

    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days*2)).strftime("%Y%m%d")

    sector_flows = {}

    try:
        # 获取申万一级行业指数
        sw_index = pro.index_classify(level='L1', src='SW2021')

        if sw_index is None or sw_index.empty:
            print("获取申万行业指数失败")
            return {}

        for _, row in sw_index.iterrows():
            industry_name = row['industry_name']
            index_code = row['index_code']

            try:
                # 获取行业指数近期涨跌幅
                df_index = pro.index_daily(
                    ts_code=index_code,
                    start_date=start_date,
                    end_date=end_date
                )

                if df_index is not None and len(df_index) >= days:
                    # 计算累计涨跌幅作为资金流向近似
                    total_change = df_index['pct_chg'].head(days).sum()
                    sector_flows[industry_name] = round(total_change, 2)
            except Exception:
                continue

        # 缓存结果
        _flow_cache = sector_flows
        _flow_cache_time = datetime.now()

    except Exception as e:
        print(f"获取板块资金流向失败: {e}")

    return sector_flows


def get_hot_sectors(days: int = 5, top_n: int = 10) -> List[Tuple[str, float]]:
    """
    获取热门板块（资金流入最多）

    Args:
        days: 统计天数
        top_n: 返回前 N 个

    Returns:
        [(板块名称, 涨跌幅), ...] 按涨跌幅降序排列

    Examples:
        >>> hot = get_hot_sectors(days=5, top_n=5)
        >>> for ind, flow in hot:
        ...     print(f"{ind}: {flow:+.2f}%")
    """
    flows = get_sector_flow(days)
    sorted_flows = sorted(flows.items(), key=lambda x: x[1], reverse=True)
    return sorted_flows[:top_n]


def get_cold_sectors(days: int = 5, top_n: int = 10) -> List[Tuple[str, float]]:
    """
    获取冷门板块（资金流出最多）

    Args:
        days: 统计天数
        top_n: 返回前 N 个

    Returns:
        [(板块名称, 涨跌幅), ...] 按涨跌幅升序排列
    """
    flows = get_sector_flow(days)
    sorted_flows = sorted(flows.items(), key=lambda x: x[1])
    return sorted_flows[:top_n]


def filter_stocks_by_flow(
    stock_codes: List[str],
    stock_info_getter,
    min_flow: float = 0,
    days: int = 5
) -> List[Tuple[str, float]]:
    """
    筛选资金流入达到要求的板块股票

    Args:
        stock_codes: 股票代码列表
        stock_info_getter: 获取股票信息的函数，如 get_stock_industry
        min_flow: 最小资金流入要求（百分比）
        days: 统计天数

    Returns:
        [(股票代码, 所属板块资金流向), ...]
    """
    sector_flows = get_sector_flow(days)

    result = []
    for code in stock_codes:
        info = stock_info_getter(code)
        if info:
            industry = info.get('industry', '')
            flow = sector_flows.get(industry, -999)
            if flow >= min_flow:
                result.append((code, flow))

    return result


def print_sector_flow(days: int = 5, top_n: int = 15):
    """
    打印板块资金流向排行

    Args:
        days: 统计天数
        top_n: 显示前 N 个
    """
    flows = get_sector_flow(days)

    if not flows:
        print("无法获取板块资金流向数据")
        return

    sorted_flows = sorted(flows.items(), key=lambda x: x[1], reverse=True)

    print(f"\n板块资金流向 (近 {days} 日):")
    print("=" * 50)

    print(f"\n{'排名':<4} {'板块':<12} {'涨跌幅':>10}")
    print("-" * 50)

    for i, (ind, flow) in enumerate(sorted_flows[:top_n], 1):
        color = ""
        if flow > 0:
            color = "+" if flow >= 3 else ""
        else:
            color = ""

        print(f"{i:<4} {ind:<12} {flow}{color}%")

    # 统计
    positive = sum(1 for _, f in flows.items() if f > 0)
    negative = sum(1 for _, f in flows.items() if f < 0)
    avg = sum(flows.values()) / len(flows) if flows else 0

    print("-" * 50)
    print(f"统计: 上涨 {positive} 个, 下跌 {negative} 个, 平均 {avg:+.2f}%")


# ============ 个股资金流向 ============

_stock_money_flow_cache = {}  # {code: {data, time}}


def get_stock_money_flow(code: str, days: int = 5) -> Dict[str, any]:
    """
    获取个股资金流向

    通过 Tushare moneyflow 接口获取个股资金流向数据，包含大单、中单、小单的买卖情况。

    Args:
        code: 股票代码（6 位数字，如 '000001'）
        days: 统计天数，默认 5 天

    Returns:
        {
            'code': '000001',
            'name': '平安银行',
            'days': 5,
            'net_amount': 12345.67,  # 净流入额（万元），正数为流入
            'net_vol': 1234,  # 净流入量（手）
            'buy_elg_amount': 12345.67,  # 特大单买入额（万元）
            'sell_elg_amount': 12345.67,  # 特大单卖出额（万元）
            'buy_lg_amount': 12345.67,  # 大单买入额（万元）
            'sell_lg_amount': 12345.67,  # 大单卖出额（万元）
            'buy_md_amount': 12345.67,  # 中单买入额（万元）
            'sell_md_amount': 12345.67,  # 中单卖出额（万元）
            'buy_sm_amount': 12345.67,  # 小单买入额（万元）
            'sell_sm_amount': 12345.67,  # 小单卖出额（万元）
            'net_elg_amount': 12345.67,  # 特大单净流入（万元）
            'net_lg_amount': 12345.67,  # 大单净流入（万元）
            'net_main_amount': 12345.67,  # 主力净流入（特大单+大单，万元）
        }

    Examples:
        >>> flow = get_stock_money_flow('000001', days=5)
        >>> print(f"{flow['name']} 主力净流入: {flow['net_main_amount']:.2f} 万元")
    """
    global _stock_money_flow_cache

    # 检查缓存（10分钟有效）
    cache_key = f"{code}_{days}"
    if cache_key in _stock_money_flow_cache:
        cached = _stock_money_flow_cache[cache_key]
        if datetime.now() - cached['time'] < timedelta(minutes=10):
            return cached['data']

    import tushare as ts

    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        print("警告: 未设置 TUSHARE_TOKEN，无法获取个股资金流向")
        return {}

    ts.set_token(token)
    pro = ts.pro_api()

    # 转换代码格式（000001 -> 000001.SZ）
    def convert_code(c: str) -> str:
        if c.startswith('6'):
            return f"{c}.SH"
        else:
            return f"{c}.SZ"

    ts_code = convert_code(code)
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days*2)).strftime("%Y%m%d")

    try:
        df = pro.moneyflow(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date
        )

        if df is None or df.empty:
            return {
                'code': code,
                'error': '无数据'
            }

        # 取最近的 days 条数据
        df = df.head(days)

        # 获取股票名称
        try:
            stock_basic = pro.stock_basic(ts_code=ts_code, fields='name')
            name = stock_basic['name'].iloc[0] if not stock_basic.empty else ''
        except:
            name = ''

        # 累计统计
        result = {
            'code': code,
            'name': name,
            'days': len(df),
            'net_amount': round(df['net_mf_amount'].sum(), 2),  # 净流入额（万元）
            'net_vol': int(df['net_mf_vol'].sum()),  # 净流入量（手）
            'buy_elg_amount': round(df['buy_elg_vol'].sum() * df.get('close', pd.Series([1])).iloc[-1] / 10000, 2),  # 特大单买入
            'sell_elg_amount': round(df['sell_elg_vol'].sum() * df.get('close', pd.Series([1])).iloc[-1] / 10000, 2),  # 特大单卖出
            'buy_lg_amount': round(df['buy_lg_vol'].sum() * df.get('close', pd.Series([1])).iloc[-1] / 10000, 2),  # 大单买入
            'sell_lg_amount': round(df['sell_lg_vol'].sum() * df.get('close', pd.Series([1])).iloc[-1] / 10000, 2),  # 大单卖出
            'buy_md_amount': round(df['buy_md_vol'].sum() * df.get('close', pd.Series([1])).iloc[-1] / 10000, 2),  # 中单买入
            'sell_md_amount': round(df['sell_md_vol'].sum() * df.get('close', pd.Series([1])).iloc[-1] / 10000, 2),  # 中单卖出
            'buy_sm_amount': round(df['buy_sm_vol'].sum() * df.get('close', pd.Series([1])).iloc[-1] / 10000, 2),  # 小单买入
            'sell_sm_amount': round(df['sell_sm_vol'].sum() * df.get('close', pd.Series([1])).iloc[-1] / 10000, 2),  # 小单卖出
        }

        # 计算净流入
        result['net_elg_amount'] = round(result['buy_elg_amount'] - result['sell_elg_amount'], 2)
        result['net_lg_amount'] = round(result['buy_lg_amount'] - result['sell_lg_amount'], 2)
        result['net_md_amount'] = round(result['buy_md_amount'] - result['sell_md_amount'], 2)
        result['net_sm_amount'] = round(result['buy_sm_amount'] - result['sell_sm_amount'], 2)
        result['net_main_amount'] = round(result['net_elg_amount'] + result['net_lg_amount'], 2)  # 主力净流入

        # 缓存结果
        _stock_money_flow_cache[cache_key] = {
            'data': result,
            'time': datetime.now()
        }

        return result

    except Exception as e:
        error_msg = str(e)
        if "权限" in error_msg or "2000" in error_msg:
            return {
                'code': code,
                'error': '需要 2000 积分权限'
            }
        return {
            'code': code,
            'error': error_msg
        }


def print_stock_money_flow(code: str, days: int = 5):
    """
    打印个股资金流向

    Args:
        code: 股票代码
        days: 统计天数
    """
    flow = get_stock_money_flow(code, days)

    if 'error' in flow:
        print(f"获取 {code} 资金流向失败: {flow['error']}")
        return

    print(f"\n{flow['name']} ({code}) 资金流向 (近 {days} 日):")
    print("=" * 50)

    # 主力资金
    net_main = flow.get('net_main_amount', 0)
    color = "📈" if net_main > 0 else "📉" if net_main < 0 else "➡"
    print(f"\n主力资金 {color} {net_main:+.2f} 万元")
    print(f"  特大单: {flow['net_elg_amount']:+.2f} 万元")
    print(f"  大单:   {flow['net_lg_amount']:+.2f} 万元")

    # 散户资金
    print(f"\n散户资金:")
    print(f"  中单: {flow['net_md_amount']:+.2f} 万元")
    print(f"  小单: {flow['net_sm_amount']:+.2f} 万元")

    # 汇总
    print(f"\n净流入: {flow['net_amount']:+.2f} 万元 ({flow['net_vol']:+,} 手)")


def filter_stocks_by_money_flow(
    codes: List[str],
    min_net_amount: float = 0,
    days: int = 5,
    ascending: bool = False
) -> List[Tuple[str, Dict]]:
    """
    按资金流向筛选股票

    Args:
        codes: 股票代码列表
        min_net_amount: 最小净流入金额（万元）
        days: 统计天数
        ascending: 是否升序排列（默认降序）

    Returns:
        [(code, flow_data), ...] 按净流入金额排序
    """
    results = []

    for code in codes:
        flow = get_stock_money_flow(code, days)
        if 'error' not in flow and flow.get('net_main_amount', 0) >= min_net_amount:
            results.append((code, flow))

    # 排序
    results.sort(key=lambda x: x[1].get('net_main_amount', 0), reverse=not ascending)
    return results
