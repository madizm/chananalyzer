import sqlite3

from Common.CEnum import KL_TYPE
from strategies.amount_flow_filter import (
    filter_codes_by_up_amount,
    load_amount_flow_stats,
    normalize_level,
    passes_up_amount_filter,
)


def create_db(tmp_path):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE kline_data (
            code TEXT NOT NULL,
            kl_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            open REAL NOT NULL,
            close REAL NOT NULL,
            amount REAL
        )
        """)
    conn.commit()
    conn.close()
    return db_path


def insert_kline(
    db_path, code, timestamp, open_price, close_price, amount, level="30M"
):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO kline_data (code, kl_type, timestamp, open, close, amount)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (code, level, timestamp, open_price, close_price, amount),
    )
    conn.commit()
    conn.close()


def test_load_amount_flow_stats_uses_single_bar_close_open(tmp_path):
    db_path = create_db(tmp_path)
    insert_kline(db_path, "000001", "2026-04-01 10:00:00.000000", 10, 11, 100)
    insert_kline(db_path, "000001", "2026-04-01 10:30:00.000000", 11, 10, 60)
    insert_kline(db_path, "000001", "2026-04-01 11:00:00.000000", 10, 10, 1000)

    stats = load_amount_flow_stats(
        "000001",
        "2026-04-01",
        "2026-04-01",
        "30M",
        db_path=db_path,
    )

    assert stats.passed is True
    assert stats.bar_count == 3
    assert stats.amount_bar_count == 3
    assert stats.up_amount == 100
    assert stats.down_amount == 60
    assert stats.flat_amount == 1000
    assert stats.net_amount == 40


def test_filter_codes_by_up_amount_only_returns_passed_codes(tmp_path):
    db_path = create_db(tmp_path)
    insert_kline(db_path, "000001", "2026-04-01 10:00:00.000000", 10, 11, 100)
    insert_kline(db_path, "000001", "2026-04-01 10:30:00.000000", 11, 10, 60)
    insert_kline(db_path, "000002", "2026-04-01 10:00:00.000000", 10, 11, 50)
    insert_kline(db_path, "000002", "2026-04-01 10:30:00.000000", 11, 10, 70)
    insert_kline(db_path, "000003", "2026-04-01 10:00:00.000000", 10, 11, None)

    results = filter_codes_by_up_amount(
        ["000001", "000002", "000003"],
        "2026-04-01",
        "2026-04-01",
        KL_TYPE.K_30M,
        db_path=db_path,
    )

    assert [stats.code for stats in results] == ["000001"]
    assert (
        passes_up_amount_filter(
            "000002", "2026-04-01", "2026-04-01", "30M", db_path=db_path
        )
        is False
    )
    assert (
        passes_up_amount_filter(
            "000003", "2026-04-01", "2026-04-01", "30M", db_path=db_path
        )
        is False
    )


def test_normalize_level_accepts_aliases():
    assert normalize_level("day") == "DAY"
    assert normalize_level("K_30M") == "30M"
    assert normalize_level(KL_TYPE.K_15M) == "15M"
