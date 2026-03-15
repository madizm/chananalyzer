"""
股票基本信息获取模块

提供股票行业、地区等分类信息获取功能
"""
import os
from typing import Dict, Optional, List
from collections import defaultdict

# 缓存股票基本信息
_stock_info_cache = None
_stock_industry_cache = {}  # {code: {'industry': 'xxx', 'area': 'xxx', 'name': 'xxx'}}


def get_stock_industry(code: str) -> Optional[Dict[str, str]]:
    """
    获取股票所属行业信息

    Args:
        code: 股票代码，如 '000001'

    Returns:
        包含行业信息的字典: {'industry': 'xxx', 'area': 'xxx', 'name': 'xxx'}
        如果获取失败返回 None
    """
    # 检查缓存
    if _stock_industry_cache and code in _stock_industry_cache:
        return _stock_industry_cache[code]

    # 首次调用，加载所有股票信息
    if not _stock_industry_cache:
        _load_stock_info()

    return _stock_industry_cache.get(code)


def _load_stock_info():
    """加载所有股票基本信息到缓存"""
    global _stock_industry_cache

    import tushare as ts
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        return

    ts.set_token(token)
    pro = ts.pro_api()

    try:
        df = pro.stock_basic(
            exchange='',
            list_status='L',
            fields='ts_code,symbol,name,area,industry'
        )
        if df is not None and not df.empty:
            # 建立缓存
            for _, row in df.iterrows():
                symbol = row['symbol']
                _stock_industry_cache[symbol] = {
                    'industry': row.get('industry', '未分类'),
                    'area': row.get('area', '未知'),
                    'name': row.get('name', ''),
                }
    except Exception as e:
        print(f"获取行业信息失败: {e}")


def get_industry_stats(stock_codes: List[str]) -> Dict[str, List[str]]:
    """
    统计股票列表的行业分布

    Args:
        stock_codes: 股票代码列表

    Returns:
        按行业分组的股票字典: {'行业名': ['code1', 'code2', ...]}
    """
    industry_stocks = defaultdict(list)

    for code in stock_codes:
        info = get_stock_industry(code)
        if info:
            industry = info.get('industry', '未分类')
            industry_stocks[industry].append(code)

    return dict(industry_stocks)


def get_area_stats(stock_codes: List[str]) -> Dict[str, List[str]]:
    """
    统计股票列表的地区分布

    Args:
        stock_codes: 股票代码列表

    Returns:
        按地区分组的股票字典: {'地区名': ['code1', 'code2', ...]}
    """
    area_stocks = defaultdict(list)

    for code in stock_codes:
        info = get_stock_industry(code)
        if info:
            area = info.get('area', '未知')
            area_stocks[area].append(code)

    return dict(area_stocks)


def group_by_field(results: List[Dict], field: str) -> Dict[str, List[Dict]]:
    """
    将扫描结果按指定字段分组

    Args:
        results: 扫描结果列表
        field: 分组字段 ('industry' 或 'area')

    Returns:
        分组后的字典: {'字段值': [结果列表]}
    """
    grouped = defaultdict(list)

    for stock in results:
        code = stock['code']
        info = get_stock_industry(code)
        if info:
            key = info.get(field, '未分类')
        else:
            key = '未分类'
        grouped[key].append(stock)

    return dict(grouped)
