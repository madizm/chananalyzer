from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from strategies.zs_gap_buy import detect_zs_gap_buy


class FakeLevel:
    def __init__(self, zs_list, close=12.3):
        self.zs_list = zs_list
        self._last_klc = [SimpleNamespace(close=close)]

    def __len__(self):
        return 1

    def __getitem__(self, index):
        if index == -1 or index == 0:
            return self._last_klc
        raise IndexError(index)


class FakeSnapshot:
    def __init__(self, level):
        self.level = level

    def __getitem__(self, index):
        if index != 0:
            raise IndexError(index)
        return self.level


def _klu(text: str, close: float = 10.0):
    dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    return SimpleNamespace(time=dt, close=close)


def _bi(idx: int, seg_idx: int):
    return SimpleNamespace(idx=idx, seg_idx=seg_idx)


def _zs(
    *,
    begin_idx: int,
    end_idx: int,
    seg_idx: int,
    low: float,
    high: float,
    is_sure: bool = True,
):
    return SimpleNamespace(
        begin=_klu(f"2026-01-{begin_idx + 1:02d} 09:30:00"),
        end=_klu(f"2026-01-{end_idx + 1:02d} 14:45:00", close=low),
        begin_bi=_bi(begin_idx, seg_idx),
        end_bi=_bi(end_idx, seg_idx),
        low=low,
        high=high,
        mid=(low + high) / 2,
        peak_low=low - 1,
        peak_high=high + 1,
        is_sure=is_sure,
    )


def _snapshot(zs_list, close=12.3):
    return FakeSnapshot(FakeLevel(zs_list, close=close))


def test_detects_two_latest_zs_with_positive_gap():
    snapshot = _snapshot(
        [
            _zs(begin_idx=1, end_idx=3, seg_idx=0, low=8.0, high=10.0),
            _zs(begin_idx=4, end_idx=6, seg_idx=1, low=10.5, high=11.5),
        ],
        close=12.8,
    )

    hit = detect_zs_gap_buy(snapshot, 0, datetime(2026, 1, 8, 15, 0))

    assert hit is not None
    assert hit.signal_time == datetime(2026, 1, 7, 14, 45)
    assert hit.signal_price == 12.8
    assert hit.gap_abs == pytest.approx(0.5)
    assert hit.gap_pct == pytest.approx(5.0)


def test_requires_at_least_two_effective_zs():
    snapshot = _snapshot(
        [_zs(begin_idx=1, end_idx=3, seg_idx=0, low=8.0, high=10.0)],
    )

    assert detect_zs_gap_buy(snapshot, 0, datetime(2026, 1, 8)) is None


def test_ignores_zs_direction_when_gap_is_positive():
    snapshot = _snapshot(
        [
            _zs(begin_idx=1, end_idx=3, seg_idx=0, low=8.0, high=10.0),
            _zs(begin_idx=4, end_idx=6, seg_idx=1, low=10.5, high=11.5),
        ],
    )

    assert detect_zs_gap_buy(snapshot, 0, datetime(2026, 1, 8)) is not None


def test_requires_latest_low_above_previous_high():
    snapshot = _snapshot(
        [
            _zs(begin_idx=1, end_idx=3, seg_idx=0, low=8.0, high=10.0),
            _zs(begin_idx=4, end_idx=6, seg_idx=1, low=9.9, high=11.5),
        ],
    )

    assert detect_zs_gap_buy(snapshot, 0, datetime(2026, 1, 8)) is None


def test_skips_unsure_zs_when_required():
    snapshot = _snapshot(
        [
            _zs(begin_idx=1, end_idx=3, seg_idx=0, low=8.0, high=10.0),
            _zs(begin_idx=4, end_idx=6, seg_idx=1, low=10.5, high=11.5, is_sure=False),
        ],
    )

    assert detect_zs_gap_buy(snapshot, 0, datetime(2026, 1, 8)) is None


def test_can_include_unsure_zs():
    snapshot = _snapshot(
        [
            _zs(begin_idx=1, end_idx=3, seg_idx=0, low=8.0, high=10.0),
            _zs(begin_idx=4, end_idx=6, seg_idx=1, low=10.5, high=11.5, is_sure=False),
        ],
    )

    hit = detect_zs_gap_buy(
        snapshot,
        0,
        datetime(2026, 1, 8),
        require_zs_sure=False,
    )

    assert hit is not None
    assert hit.latest_zs["is_sure"] is False


def test_respects_min_gap_pct():
    snapshot = _snapshot(
        [
            _zs(begin_idx=1, end_idx=3, seg_idx=0, low=8.0, high=10.0),
            _zs(begin_idx=4, end_idx=6, seg_idx=1, low=10.5, high=11.5),
        ],
    )

    assert (
        detect_zs_gap_buy(
            snapshot,
            0,
            datetime(2026, 1, 8),
            min_gap_pct=5.1,
        )
        is None
    )
