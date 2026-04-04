import os
import re
from pathlib import Path
from typing import Iterable, Optional

from Common.CEnum import AUTYPE, DATA_FIELD, KL_TYPE
from Common.CTime import CTime
from KLine.KLine_Unit import CKLine_Unit
from TdxLib.tqcenter import tq

from .CommonStockAPI import CCommonStockApi


class CTdxAPI(CCommonStockApi):
    _initialized = False
    _dll_path = os.getenv("TPYTHCLIENT_DLL", r"D:\tdx_new\PYPlugins\TPythClient.dll")

    def __init__(self, code, k_type=KL_TYPE.K_DAY, begin_date=None, end_date=None, autype=AUTYPE.QFQ):
        super(CTdxAPI, self).__init__(code, k_type, begin_date, end_date, autype)

    def get_kl_data(self) -> Iterable[CKLine_Unit]:
        period = self._convert_kl_type()
        stock_code = self._normalize_code(self.code)

        # 通达信get market data 方法没有换手率
        field_list = ["open", "high", "low", "close", "volume", "amount"]
        data = tq.get_market_data(
            field_list=field_list,
            stock_list=[stock_code],
            period=period,
            start_time=self._format_date(self.begin_date),
            end_time=self._format_date(self.end_date),
            dividend_type=self._convert_autype(),
            fill_data=False,
        )

        if not data:
            return

        close_df = self._get_field_df(data, "close")
        if close_df is None or close_df.empty:
            return

        open_df = self._get_field_df(data, "open")
        high_df = self._get_field_df(data, "high")
        low_df = self._get_field_df(data, "low")
        volume_df = self._get_field_df(data, "volume")
        amount_df = self._get_field_df(data, "amount")
        turnover_rate_df = self._get_field_df(data, "turnover_rate")

        col = close_df.columns[0]
        for ts in close_df.index:
            close_v = self._safe_number(close_df.at[ts, col])
            if close_v is None:
                continue

            open_v = self._safe_number(open_df.at[ts, col]) if open_df is not None and col in open_df.columns else close_v
            high_v = self._safe_number(high_df.at[ts, col]) if high_df is not None and col in high_df.columns else close_v
            low_v = self._safe_number(low_df.at[ts, col]) if low_df is not None and col in low_df.columns else close_v
            volume_v = self._safe_number(volume_df.at[ts, col]) if volume_df is not None and col in volume_df.columns else 0.0
            amount_v = self._safe_number(amount_df.at[ts, col]) if amount_df is not None and col in amount_df.columns else 0.0

            item = {
                DATA_FIELD.FIELD_TIME: CTime(ts.year, ts.month, ts.day, ts.hour, ts.minute),
                DATA_FIELD.FIELD_OPEN: open_v if open_v is not None else close_v,
                DATA_FIELD.FIELD_HIGH: high_v if high_v is not None else close_v,
                DATA_FIELD.FIELD_LOW: low_v if low_v is not None else close_v,
                DATA_FIELD.FIELD_CLOSE: close_v,
                DATA_FIELD.FIELD_VOLUME: volume_v if volume_v is not None else 0.0,
                DATA_FIELD.FIELD_TURNOVER: amount_v if amount_v is not None else 0.0,
            }

            if turnover_rate_df is not None and col in turnover_rate_df.columns:
                turnrate_v = self._safe_number(turnover_rate_df.at[ts, col])
                if turnrate_v is not None:
                    item[DATA_FIELD.FIELD_TURNRATE] = turnrate_v

            yield CKLine_Unit(item)

    def SetBasciInfo(self):
        self.name = self.code
        self.is_stock = True

    @classmethod
    def do_init(cls):
        if cls._initialized:
            return
        strategy_path = str(Path(__file__).resolve())
        tq.initialize(path=strategy_path, dll_path=cls._dll_path)
        cls._initialized = True

    @classmethod
    def do_close(cls):
        if cls._initialized:
            tq.close()
            cls._initialized = False

    @staticmethod
    def _safe_number(value) -> Optional[float]:
        if value is None:
            return None
        try:
            num = float(value)
        except (TypeError, ValueError):
            return None
        if num != num:
            return None
        return num

    @staticmethod
    def _normalize_code(code: str) -> str:
        if code is None:
            raise ValueError("股票代码不能为空")
        code = str(code).strip()

        if "." in code:
            left, right = code.split(".", 1)
            return f"{left.upper()}.{right.upper()}"

        lower = code.lower()
        if lower.startswith("sh") or lower.startswith("sz") or lower.startswith("bj"):
            market = lower[:2].upper() if lower[:2] in ("sh", "sz") else "BJ"
            return f"{lower[2:].upper()}.{market}"

        if code.isdigit() and len(code) == 6:
            if code.startswith("6"):
                return f"{code}.SH"
            if code.startswith("8") or code.startswith("4"):
                return f"{code}.BJ"
            return f"{code}.SZ"

        raise ValueError(f"不支持的股票代码格式: {code}")

    def _convert_kl_type(self) -> str:
        mapping = {
            KL_TYPE.K_DAY: "1d",
            KL_TYPE.K_WEEK: "1w",
            KL_TYPE.K_MON: "1mon",
            KL_TYPE.K_5M: "5m",
            KL_TYPE.K_15M: "15m",
            KL_TYPE.K_30M: "30m",
            KL_TYPE.K_60M: "1h",
        }
        if self.k_type not in mapping:
            raise ValueError(f"TDX数据源暂不支持K线类型: {self.k_type}")
        return mapping[self.k_type]

    def _convert_autype(self) -> str:
        mapping = {
            AUTYPE.QFQ: "front",
            AUTYPE.HFQ: "back",
            AUTYPE.NONE: "none",
        }
        return mapping.get(self.autype, "front")

    @staticmethod
    def _format_date(date_val: Optional[str]) -> str:
        if not date_val:
            return ""
        digits = re.sub(r"\D", "", str(date_val))
        if len(digits) >= 14:
            return digits[:14]
        if len(digits) >= 8:
            return digits[:8]
        return ""

    @staticmethod
    def _get_field_df(data: dict, field: str):
        for key, value in data.items():
            if key.lower() == field.lower():
                return value
        return None


TdxAPI = CTdxAPI
