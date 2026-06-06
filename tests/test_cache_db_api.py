import sqlite3
from concurrent.futures import ThreadPoolExecutor

from DataAPI import CacheDBAPI as cache_db_api
from DataAPI.CacheDBAPI import CCacheDBAPI


def test_cache_db_lifecycle_does_not_share_sqlite_connection_across_threads(monkeypatch, tmp_path):
    db_path = tmp_path / "chan.db"
    sqlite3.connect(db_path).close()
    monkeypatch.setattr(cache_db_api, "_get_db_path", lambda: str(db_path))

    CCacheDBAPI.do_init()
    assert CCacheDBAPI._conn is None

    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(CCacheDBAPI.do_close).result()

    assert CCacheDBAPI._conn is None
