import pandas as pd

from TdxLib.tqcenter import tq


def test_get_market_data_returns_filtered_kline_frame(monkeypatch):
    monkeypatch.setattr(tq, "_auto_initialize", classmethod(lambda cls: None))

    def fake_fetch(cls, stock_list, period_bytes, start_bytes, end_bytes, dividend_type_int, count, timeout_ms=60000):
        assert stock_list == ["000001.SZ", "600000.SH"]
        assert period_bytes == b"1d"
        assert dividend_type_int == 10
        return {
            "000001.SZ": {
                "ErrorId": "0",
                "Date": ["20260101", "20260102"],
                "Time": ["0", "0"],
                "Open": ["10.0", "11.0"],
                "Close": ["10.5", "11.5"],
            },
            "600000.SH": {
                "ErrorId": "0",
                "Date": ["20260101", "20260102"],
                "Time": ["0", "0"],
                "Open": ["20.0", "21.0"],
                "Close": ["20.5", "21.5"],
            },
        }

    monkeypatch.setattr(tq, "_fetch_market_data_batch", classmethod(fake_fetch))

    result = tq.get_market_data(
        field_list=["open"],
        stock_list=["000001.SZ", "600000.SH"],
        period="1d",
        start_time="20260101",
        end_time="20260102",
    )

    assert list(result.keys()) == ["Open"]
    open_df = result["Open"]

    assert isinstance(open_df, pd.DataFrame)
    assert list(open_df.columns) == ["000001.SZ", "600000.SH"]
    assert len(open_df.index) == 2
    assert open_df.loc[pd.Timestamp("2026-01-01"), "000001.SZ"] == 10.0
    assert open_df.loc[pd.Timestamp("2026-01-02"), "600000.SH"] == 21.0


def test_get_market_data_fetches_real_data():
    strategy_path = r"D:\workspace-python\chananalyzer\tests\test_tqcenter_get_market_data.py"
    dll_path = r"D:\tdx_new\PYPlugins\TPythClient.dll"

    tq.initialize(path=strategy_path, dll_path=dll_path)
    try:
        result = tq.get_market_data(
            field_list=["open", "close"],
            stock_list=["000001.SZ"],
            period="1d",
            count=2,
        )

        assert "Open" in result
        assert "Close" in result

        open_df = result["Open"]
        close_df = result["Close"]

        assert isinstance(open_df, pd.DataFrame)
        assert isinstance(close_df, pd.DataFrame)
        assert "000001.SZ" in open_df.columns
        assert "000001.SZ" in close_df.columns
        assert len(open_df.index) >= 1
        assert len(close_df.index) >= 1
        assert pd.notna(open_df.iloc[-1, 0])
        assert pd.notna(close_df.iloc[-1, 0])
    finally:
        tq.close()
