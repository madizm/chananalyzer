from __future__ import annotations

from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE


LV_ALIASES: dict[str, KL_TYPE] = {
    "1": KL_TYPE.K_1M,
    "1m": KL_TYPE.K_1M,
    "k_1m": KL_TYPE.K_1M,
    "3": KL_TYPE.K_3M,
    "3m": KL_TYPE.K_3M,
    "k_3m": KL_TYPE.K_3M,
    "5": KL_TYPE.K_5M,
    "5m": KL_TYPE.K_5M,
    "k_5m": KL_TYPE.K_5M,
    "15": KL_TYPE.K_15M,
    "15m": KL_TYPE.K_15M,
    "k_15m": KL_TYPE.K_15M,
    "30": KL_TYPE.K_30M,
    "30m": KL_TYPE.K_30M,
    "k_30m": KL_TYPE.K_30M,
    "60": KL_TYPE.K_60M,
    "60m": KL_TYPE.K_60M,
    "1h": KL_TYPE.K_60M,
    "k_60m": KL_TYPE.K_60M,
    "d": KL_TYPE.K_DAY,
    "day": KL_TYPE.K_DAY,
    "1d": KL_TYPE.K_DAY,
    "daily": KL_TYPE.K_DAY,
    "k_day": KL_TYPE.K_DAY,
    "w": KL_TYPE.K_WEEK,
    "week": KL_TYPE.K_WEEK,
    "1w": KL_TYPE.K_WEEK,
    "weekly": KL_TYPE.K_WEEK,
    "k_week": KL_TYPE.K_WEEK,
    "mon": KL_TYPE.K_MON,
    "month": KL_TYPE.K_MON,
    "monthly": KL_TYPE.K_MON,
    "k_mon": KL_TYPE.K_MON,
    "quarter": KL_TYPE.K_QUARTER,
    "season": KL_TYPE.K_QUARTER,
    "k_quarter": KL_TYPE.K_QUARTER,
    "year": KL_TYPE.K_YEAR,
    "y": KL_TYPE.K_YEAR,
    "k_year": KL_TYPE.K_YEAR,
}


def parse_lv(value: str | None) -> KL_TYPE:
    if not value:
        return KL_TYPE.K_DAY
    key = value.strip().lower().replace("-", "_")
    if key in LV_ALIASES:
        return LV_ALIASES[key]
    raise ValueError(f"invalid lv: {value}")


def parse_data_src(value: str | None) -> DATA_SRC | str:
    if not value:
        return DATA_SRC.TDX
    src = value.strip()
    if src.lower().startswith("custom:"):
        return src
    key = src.upper().replace("-", "_")
    try:
        return DATA_SRC[key]
    except KeyError as exc:
        raise ValueError(f"invalid data_src: {value}") from exc


def parse_autype(value: str | None) -> AUTYPE:
    if not value:
        return AUTYPE.QFQ
    key = value.strip().upper().replace("-", "_")
    if key in {"NO", "NONE", "NULL"}:
        return AUTYPE.NONE
    try:
        return AUTYPE[key]
    except KeyError as exc:
        raise ValueError(f"invalid autype: {value}") from exc
