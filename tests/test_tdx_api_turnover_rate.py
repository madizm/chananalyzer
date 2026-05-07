import pandas as pd

from ChanAnalyzer.database import KLineData
from Common.CEnum import DATA_FIELD, KL_TYPE
from Common.CTime import CTime
from DataAPI.TdxAPI import CTdxAPI
from KLine.KLine_Unit import CKLine_Unit
from TdxLib.tqcenter import tq


def test_tdx_api_calculates_turnover_rate_from_active_capital(monkeypatch):
    def fake_get_market_data(**kwargs):
        idx = pd.to_datetime(["2026-01-01", "2026-01-02"])
        col = "000001.SZ"
        return {
            "Open": pd.DataFrame({col: [10.0, 11.0]}, index=idx),
            "High": pd.DataFrame({col: [10.5, 11.5]}, index=idx),
            "Low": pd.DataFrame({col: [9.5, 10.5]}, index=idx),
            "Close": pd.DataFrame({col: [10.2, 11.2]}, index=idx),
            "Volume": pd.DataFrame({col: [1000.0, 2500.0]}, index=idx),
            "Amount": pd.DataFrame({col: [10000.0, 25000.0]}, index=idx),
        }

    monkeypatch.setattr(tq, "get_market_data", fake_get_market_data)
    monkeypatch.setattr(
        tq,
        "get_stock_info",
        lambda stock_code, field_list: {"ActiveCapital": "5000"},
    )

    klu_list = list(CTdxAPI("000001", KL_TYPE.K_DAY).get_kl_data())

    assert len(klu_list) == 2
    assert klu_list[0].trade_info.metric[DATA_FIELD.FIELD_TURNRATE] == 0.002
    assert klu_list[1].trade_info.metric[DATA_FIELD.FIELD_TURNRATE] == 0.005


def test_kline_data_from_klu_preserves_zero_turnover_rate():
    klu = CKLine_Unit(
        {
            DATA_FIELD.FIELD_TIME: CTime(2026, 1, 1, 0, 0),
            DATA_FIELD.FIELD_OPEN: 10.0,
            DATA_FIELD.FIELD_HIGH: 10.0,
            DATA_FIELD.FIELD_LOW: 10.0,
            DATA_FIELD.FIELD_CLOSE: 10.0,
            DATA_FIELD.FIELD_VOLUME: 0.0,
            DATA_FIELD.FIELD_TURNOVER: 0.0,
            DATA_FIELD.FIELD_TURNRATE: 0.0,
        }
    )

    row = KLineData.from_klu(klu, "000001", KL_TYPE.K_DAY)

    assert row.amount == 0.0
    assert row.turnover_rate == 0.0


def test_tdx_api_normalizes_baostock_style_code():
    assert CTdxAPI._normalize_code("sh.600000") == "600000.SH"
    assert CTdxAPI._normalize_code("sz.000001") == "000001.SZ"
