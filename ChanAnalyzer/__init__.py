"""
ChanAnalyzer - 缠论分析模块

基于 Tushare 数据源的缠论分析工具，输出笔、线段、中枢、买卖点等分析结果。

支持多周期分析：60分钟、日线、周线

使用示例:
    >>> from ChanAnalyzer import ChanAnalyzer, MultiChanAnalyzer
    >>>
    >>> # 单周期分析（默认日线）
    >>> analyzer = ChanAnalyzer(code="000001")
    >>> summary = analyzer.get_summary()
    >>> print(summary)
    >>>
    >>> # 多周期分析（60分钟、日线、周线）
    >>> analyzer = MultiChanAnalyzer(code="000001")
    >>> summary = analyzer.get_summary()
    >>> print(summary)
    >>>
    >>> # 自定义周期
    >>> from Common.CEnum import KL_TYPE
    >>> analyzer = ChanAnalyzer(
    ...     code="000001",
    ...     kl_types=[KL_TYPE.K_DAY, KL_TYPE.K_WEEK]
    ... )
"""
from ChanAnalyzer.analyzer import ChanAnalyzer, MultiChanAnalyzer
from ChanAnalyzer.ai_analyzer import AIAnalyzer, analyze_with_ai
from ChanAnalyzer.multi_ai_analyzer import MultiAIAnalyzer, analyze_with_multi_ai, AnalystOpinion, MultiAIResult
from ChanAnalyzer.database import init_db, get_db, KLineData
from ChanAnalyzer.data_manager import DataManager, get_data_manager, data_manager
from ChanAnalyzer.stock_info import get_stock_industry, get_industry_stats, get_area_stats, group_by_field
from ChanAnalyzer.stock_pool import StockPool
from ChanAnalyzer.sector_flow import (
    get_sector_flow,
    get_hot_sectors,
    get_cold_sectors,
    filter_stocks_by_flow,
    print_sector_flow,
    get_stock_money_flow,
    print_stock_money_flow,
    filter_stocks_by_money_flow,
)

__version__ = "2.2.0"
__all__ = [
    "ChanAnalyzer",
    "MultiChanAnalyzer",
    "AIAnalyzer",
    "analyze_with_ai",
    "MultiAIAnalyzer",
    "analyze_with_multi_ai",
    "AnalystOpinion",
    "MultiAIResult",
    "DataManager",
    "get_data_manager",
    "data_manager",
    "init_db",
    "get_db",
    "KLineData",
    "get_stock_industry",
    "get_industry_stats",
    "get_area_stats",
    "group_by_field",
    "StockPool",
    "get_sector_flow",
    "get_hot_sectors",
    "get_cold_sectors",
    "filter_stocks_by_flow",
    "print_sector_flow",
    "get_stock_money_flow",
    "print_stock_money_flow",
    "filter_stocks_by_money_flow",
]
