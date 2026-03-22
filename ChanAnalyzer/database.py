"""
K线数据缓存 - 数据库模型

使用 SQLite 存储历史 K 线数据，实现增量更新和本地缓存。
"""

import os
from datetime import datetime

from sqlalchemy import (
    create_engine,
    Column,
    String,
    Float,
    Integer,
    DateTime,
    Index,
    Text,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager

from Common.CEnum import KL_TYPE, DATA_FIELD

# 数据库配置
DEFAULT_DB_URL = "sqlite:///./chan.db"
DB_URL = os.environ.get("DATABASE_URL", DEFAULT_DB_URL)

# 创建引擎
engine = create_engine(
    DB_URL,
    echo=False,  # 设置为 True 可查看 SQL 语句
    connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {},
)

# 创建基类
Base = declarative_base()

# 创建 Session 工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@contextmanager
def get_db() -> Session:
    """获取数据库会话（上下文管理器）"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """初始化数据库（创建所有表）"""
    Base.metadata.create_all(bind=engine)


class KLineData(Base):
    """K线数据表"""

    __tablename__ = "kline_data"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 股票信息
    code = Column(String(10), nullable=False, index=True)  # 股票代码，如 000001
    kl_type = Column(
        String(10), nullable=False, index=True
    )  # 周期类型: DAY, WEEK, MON 等

    # 时间
    date = Column(String(20), nullable=False)  # 日期 YYYY-MM-DD HH:MM:SS
    timestamp = Column(DateTime, nullable=False)  # 时间戳（用于排序和比较）

    # OHLCV 数据
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)  # 成交量
    amount = Column(Float, nullable=True)  # 成交额
    turnover_rate = Column(Float, nullable=True)  # 换手率

    # 元数据
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 复合唯一索引和普通索引
    __table_args__ = (
        UniqueConstraint("code", "kl_type", "date", name="uix_code_kltype_date"),
        Index("idx_code_kltype_timestamp", "code", "kl_type", "timestamp"),
    )

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "code": self.code,
            "kl_type": self.kl_type,
            "date": self.date,
            "timestamp": self.timestamp,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "amount": self.amount or 0,
            "turnover_rate": self.turnover_rate,
        }

    @classmethod
    def from_klu(cls, klu, code: str, kl_type: KL_TYPE):
        """从 CKLine_Unit 创建实例"""
        kl_type_str = KL_TYPE_NAME.get(kl_type, str(kl_type))

        # 交易数据存储在 trade_info.metric 中
        volume = 0
        amount = None
        turnover_rate = None

        if hasattr(klu, "trade_info") and klu.trade_info:
            volume = klu.trade_info.metric.get(DATA_FIELD.FIELD_VOLUME, 0) or 0
            amount = klu.trade_info.metric.get(DATA_FIELD.FIELD_TURNOVER)
            turnover_rate = klu.trade_info.metric.get(DATA_FIELD.FIELD_TURNRATE)

        return cls(
            code=code,
            kl_type=kl_type_str,
            date=klu.time.to_str(),
            timestamp=datetime(
                klu.time.year,
                klu.time.month,
                klu.time.day,
                klu.time.hour,
                klu.time.minute,
            ),
            open=float(klu.open),
            high=float(klu.high),
            low=float(klu.low),
            close=float(klu.close),
            volume=float(volume) if volume else 0,
            amount=float(amount) if amount else None,
            turnover_rate=float(turnover_rate) if turnover_rate else None,
        )


# 周期类型名称映射
KL_TYPE_NAME = {
    KL_TYPE.K_1M: "1M",
    KL_TYPE.K_5M: "5M",
    KL_TYPE.K_15M: "15M",
    KL_TYPE.K_30M: "30M",
    KL_TYPE.K_DAY: "DAY",
    KL_TYPE.K_WEEK: "WEEK",
    KL_TYPE.K_MON: "MON",
    KL_TYPE.K_YEAR: "YEAR",
}


def get_kl_type_str(kl_type: KL_TYPE) -> str:
    """获取周期类型字符串"""
    return KL_TYPE_NAME.get(kl_type, str(kl_type))


def parse_kl_type_str(kl_type_str: str) -> KL_TYPE:
    """从字符串解析周期类型"""
    for k, v in KL_TYPE_NAME.items():
        if v == kl_type_str:
            return k
    raise ValueError(f"Unknown kl_type: {kl_type_str}")


class ScanRun(Base):
    """扫描任务运行记录"""

    __tablename__ = "scan_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(50), nullable=False, index=True)
    started_at = Column(DateTime, nullable=False)
    finished_at = Column(DateTime, nullable=False)
    scanned_count = Column(Integer, nullable=False, default=0)
    result_count = Column(Integer, nullable=False, default=0)

    buy_types = Column(Text, nullable=False, default="[]")
    sell_types = Column(Text, nullable=False, default="[]")
    begin_date = Column(String(20), nullable=True)
    end_date = Column(String(20), nullable=True)
    use_weekly = Column(Integer, nullable=False, default=0)
    bi_strict = Column(Integer, nullable=False, default=1)

    industry_filters = Column(Text, nullable=False, default="[]")
    area_filters = Column(Text, nullable=False, default="[]")
    exclude_st = Column(Integer, nullable=False, default=0)
    group_by = Column(String(20), nullable=False, default="none")

    min_amount = Column(Float, nullable=True)
    max_amount = Column(Float, nullable=True)
    min_turnover_rate = Column(Float, nullable=True)
    max_turnover_rate = Column(Float, nullable=True)

    show_money_flow = Column(Integer, nullable=False, default=0)
    sort_by_money_flow = Column(Integer, nullable=False, default=0)
    min_money_flow = Column(Float, nullable=False, default=0)

    created_at = Column(DateTime, default=datetime.now, nullable=False)

    __table_args__ = (Index("idx_scan_runs_created_at", "created_at"),)


class ScanResult(Base):
    """扫描结果明细"""

    __tablename__ = "scan_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("scan_runs.id"), nullable=False, index=True)

    code = Column(String(10), nullable=False, index=True)
    name = Column(String(50), nullable=True)
    industry = Column(String(100), nullable=True)
    area = Column(String(100), nullable=True)

    latest_price = Column(Float, nullable=True)
    change_pct = Column(Float, nullable=True)
    money_flow_net_amount = Column(Float, nullable=True)
    money_flow_net_main_amount = Column(Float, nullable=True)
    money_flow_error = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.now, nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "code", name="uix_scan_results_run_code"),
        Index("idx_scan_results_run_id", "run_id"),
        Index("idx_scan_results_code", "code"),
    )


class ScanSignal(Base):
    """扫描结果中的买卖点信号明细"""

    __tablename__ = "scan_signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    result_id = Column(
        Integer, ForeignKey("scan_results.id"), nullable=False, index=True
    )
    run_id = Column(Integer, ForeignKey("scan_runs.id"), nullable=False, index=True)
    code = Column(String(10), nullable=False, index=True)

    signal_type = Column(String(20), nullable=False)
    direction = Column(String(20), nullable=False)
    signal_date = Column(String(30), nullable=False)
    signal_price = Column(Float, nullable=False)
    period = Column(String(20), nullable=False)

    created_at = Column(DateTime, default=datetime.now, nullable=False)

    __table_args__ = (
        Index("idx_scan_signals_result_id", "result_id"),
        Index("idx_scan_signals_run_id", "run_id"),
        Index("idx_scan_signals_code", "code"),
    )
