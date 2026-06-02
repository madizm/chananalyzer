from __future__ import annotations

from typing import Any


def normalize_target_types(value: Any) -> str:
    if isinstance(value, (list, tuple, set)):
        return ",".join(sorted(str(item).strip() for item in value if str(item).strip()))
    return str(value or "").replace("/", ",").strip()


def build_signal_key(
    *,
    code: str,
    level: str,
    label_group: str,
    signal_side: str,
    target_types: Any,
    signal_time: str,
    bi_begin_time: str,
    bi_end_time: str,
    bi_direction: str,
) -> str:
    parts = [
        str(code).strip().upper().split(".")[0],
        str(level).strip().upper(),
        str(label_group or "").strip(),
        str(signal_side or "").strip(),
        normalize_target_types(target_types),
        str(signal_time or "").strip(),
        str(bi_begin_time or "").strip(),
        str(bi_end_time or "").strip(),
        str(bi_direction or "").strip(),
    ]
    return "|".join(parts)
