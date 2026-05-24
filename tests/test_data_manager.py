from contextlib import contextmanager
import importlib

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ChanAnalyzer.data_manager import DataManager
from ChanAnalyzer.database import Base, KLineData
from Common.CEnum import DATA_FIELD, KL_TYPE
from Common.CTime import CTime
from KLine.KLine_Unit import CKLine_Unit


def _klu(year: int, month: int, day: int, close: float = 1.0) -> CKLine_Unit:
    return CKLine_Unit(
        {
            DATA_FIELD.FIELD_TIME: CTime(year, month, day, 0, 0),
            DATA_FIELD.FIELD_OPEN: close,
            DATA_FIELD.FIELD_HIGH: close,
            DATA_FIELD.FIELD_LOW: close,
            DATA_FIELD.FIELD_CLOSE: close,
            DATA_FIELD.FIELD_VOLUME: 100,
        }
    )


def test_merge_and_save_returns_only_requested_range(monkeypatch):
    data_manager_module = importlib.import_module("ChanAnalyzer.data_manager")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine)

    @contextmanager
    def test_db():
        db = session_local()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(data_manager_module, "get_db", test_db)

    with test_db() as db:
        db.add(KLineData.from_klu(_klu(2026, 1, 1), "000001", KL_TYPE.K_15M))
        db.add(KLineData.from_klu(_klu(2026, 1, 2), "000001", KL_TYPE.K_15M))
        db.commit()

    manager = object.__new__(DataManager)
    returned_rows = manager._merge_and_save(
        code="000001",
        kl_type_str="15M",
        cached_data=[],
        new_klu_list=[_klu(2026, 1, 3)],
        begin_date="2026-01-03",
        end_date="2026-01-03",
    )

    assert [row.timestamp.date().isoformat() for row in returned_rows] == ["2026-01-03"]
