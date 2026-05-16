from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Set, Tuple

from Debug.strategy_demo7 import (
    CHILD_LV_IDX,
    MODEL_LV_IDX,
    SignalSample,
    build_parent_level_context,
    ctime_to_str,
    pick_parent_context,
)


FeatureBuilder = Callable[[List, int, object, bool, List, Optional[Dict[str, float]], object], Dict[str, float]]


@dataclass
class PendingStabilitySample:
    sample: SignalSample
    sample_key: Tuple[str, str, str, str, str]
    signal_identity: Tuple[str, str, str, str]
    first_seen_klu_idx: int
    first_seen_bi_idx: int
    first_seen_bsp_types: Set[str]
    last_match_time: str
    last_match_bi_begin_time: str
    last_match_bi_end_time: str
    last_match_bsp_types: str
    match_level: str = "exact"
    unstable_reason: Optional[str] = None


def bsp_type_set(bsp) -> Set[str]:
    if bsp is None:
        return set()
    return {item.strip() for item in str(bsp.type2str()).split(",") if item.strip()}


def bi_direction_text(bi) -> str:
    if bi.is_down():
        return "down"
    if bi.is_up():
        return "up"
    return str(bi.dir)


def sample_key(code: str, signal_side: str, bi) -> Tuple[str, str, str, str, str]:
    return (
        code,
        signal_side,
        ctime_to_str(bi.get_begin_klu().time),
        ctime_to_str(bi.get_end_klu().time),
        bi_direction_text(bi),
    )


def signal_identity(code: str, signal_side: str, bi) -> Tuple[str, str, str, str]:
    return (
        code,
        signal_side,
        ctime_to_str(bi.get_end_klu().time),
        bi_direction_text(bi),
    )


def target_bsp_by_key(
    *,
    code: str,
    signal_side: str,
    sorted_bsp_list: List,
    target_is_buy: bool,
    target_bsp_types: Set[str],
) -> Dict[Tuple[str, str, str, str, str], object]:
    result = {}
    for bsp in sorted_bsp_list:
        if bool(bsp.is_buy) != target_is_buy:
            continue
        if not bool(bsp.bi.is_sure):
            continue
        if not (bsp_type_set(bsp) & target_bsp_types):
            continue
        result[sample_key(code, signal_side, bsp.bi)] = bsp
    return result


def bsp_by_key(
    *,
    code: str,
    signal_side: str,
    sorted_bsp_list: List,
    target_is_buy: bool,
) -> Dict[Tuple[str, str, str, str, str], object]:
    result = {}
    for bsp in sorted_bsp_list:
        if bool(bsp.is_buy) != target_is_buy:
            continue
        if not bool(bsp.bi.is_sure):
            continue
        result[sample_key(code, signal_side, bsp.bi)] = bsp
    return result


def bsp_by_signal_identity(
    *,
    code: str,
    signal_side: str,
    sorted_bsp_list: List,
    target_is_buy: bool,
) -> Dict[Tuple[str, str, str, str], object]:
    result = {}
    for bsp in sorted_bsp_list:
        if bool(bsp.is_buy) != target_is_buy:
            continue
        if not bool(bsp.bi.is_sure):
            continue
        result[signal_identity(code, signal_side, bsp.bi)] = bsp
    return result


def parse_time_text(value: str) -> datetime:
    normalized = value.strip().replace("/", "-")
    if len(normalized) == 10:
        normalized = f"{normalized} 00:00"
    return datetime.strptime(normalized, "%Y-%m-%d %H:%M")


def type_text(types: Set[str]) -> str:
    return ",".join(sorted(types))


def latest_confirmed_bi_idx(level_chan) -> int:
    latest_idx = -1
    for bi in level_chan.bi_list:
        if bi.is_sure:
            latest_idx = max(latest_idx, int(bi.idx))
    return latest_idx


def bi_parent_seg(bi):
    return getattr(bi, "parent_seg", None)


def distance_to_parent_seg_end(bi) -> float:
    parent_seg = bi_parent_seg(bi)
    if parent_seg is None:
        return 0.0
    bi_list = list(getattr(parent_seg, "bi_list", []) or [])
    if not bi_list:
        return 0.0
    for pos, item in enumerate(bi_list):
        if item is bi or int(getattr(item, "idx", -1)) == int(bi.idx):
            return float(len(bi_list) - pos - 1)
    return 0.0


def related_zs_is_sure(bi) -> float:
    parent_seg = bi_parent_seg(bi)
    zs_lst = list(getattr(parent_seg, "zs_lst", []) or []) if parent_seg is not None else []
    if not zs_lst:
        return 0.0
    return float(any(bool(getattr(zs, "is_sure", False)) for zs in zs_lst))


def dependency_bsp_before(
    sorted_bsp_list: List,
    bi_idx: int,
    target_is_buy: bool,
    dependency_bsp_types: Set[str],
):
    if not dependency_bsp_types:
        return None
    previous_bsp = None
    for bsp in sorted_bsp_list:
        if bsp.bi.idx >= bi_idx:
            break
        if bool(bsp.is_buy) == target_is_buy and bsp_type_set(bsp) & dependency_bsp_types:
            previous_bsp = bsp
    return previous_bsp


def stability_context_feature(
    *,
    final_klus: List,
    pos: int,
    level_chan,
    bi,
    bsp,
    target_is_buy: bool,
    sorted_bsp_list: List,
    dependency_bsp_types: Set[str],
    decision_klu_idx: int,
    latest_bi_idx: int,
) -> Dict[str, float]:
    entry_klu = bi.get_end_klu()
    parent_seg = bi_parent_seg(bi)
    dependency_bsp = dependency_bsp_before(sorted_bsp_list, int(bi.idx), target_is_buy, dependency_bsp_types)
    seg_list = list(getattr(getattr(level_chan, "seg_list", None), "lst", []) or [])
    latest_seg_idx = max([int(getattr(seg, "idx", -1)) for seg in seg_list], default=-1)
    feature = {
        "stability_tail_distance_bars": float(decision_klu_idx - int(entry_klu.idx)),
        "stability_tail_distance_bis": float(max(0, latest_bi_idx - int(bi.idx))),
        "stability_is_last_bi": float(int(bi.idx) == latest_bi_idx),
        "stability_is_in_last_seg": float(
            parent_seg is not None and int(getattr(parent_seg, "idx", -2)) == latest_seg_idx
        ),
        "stability_bsp_type_count": float(len(bsp_type_set(bsp))),
        "stability_has_dependency_bsp": float(dependency_bsp is not None),
        "stability_dependency_bsp_age_bars": 0.0,
        "stability_seg_is_sure": float(bool(getattr(parent_seg, "is_sure", False))) if parent_seg is not None else 0.0,
        "stability_zs_is_sure": related_zs_is_sure(bi),
        "stability_distance_to_seg_end": distance_to_parent_seg_end(bi),
    }
    if dependency_bsp is not None:
        feature["stability_dependency_bsp_age_bars"] = float(int(entry_klu.idx) - int(dependency_bsp.klu.idx))
    return feature


def window_closed(
    *,
    pending: PendingStabilitySample,
    current_time: str,
    decision_klu_idx: int,
    latest_bi_idx: int,
    stability_bars: int,
    stability_bis: int,
    stability_days: int,
    stability_window_mode: str,
) -> Tuple[bool, Optional[str]]:
    checks: List[Tuple[bool, str]] = []
    if stability_bars > 0:
        checks.append((decision_klu_idx - pending.first_seen_klu_idx >= stability_bars, "bars"))
    if stability_bis > 0:
        checks.append((latest_bi_idx - pending.first_seen_bi_idx >= stability_bis, "bis"))
    if stability_days > 0:
        close_time = parse_time_text(pending.sample.decision_time) + timedelta(days=stability_days)
        checks.append((parse_time_text(current_time) >= close_time, "days"))
    if not checks:
        checks.append((decision_klu_idx > pending.first_seen_klu_idx, "next_bar"))
    if stability_window_mode == "all":
        is_closed = all(item[0] for item in checks)
        reason = "+".join(item[1] for item in checks) if is_closed else None
        return is_closed, reason
    if stability_window_mode != "any":
        raise ValueError("stability_window_mode 只能是 any 或 all")
    for is_closed, reason in checks:
        if is_closed:
            return True, reason
    return False, None


def match_pending_bsp(
    pending: PendingStabilitySample,
    current_bsp_by_key: Dict[Tuple[str, str, str, str, str], object],
    current_bsp_by_identity: Dict[Tuple[str, str, str, str], object],
    target_bsp_types: Set[str],
) -> Tuple[Optional[object], str, Optional[str]]:
    exact_bsp = current_bsp_by_key.get(pending.sample_key)
    if exact_bsp is not None:
        current_types = bsp_type_set(exact_bsp)
        if current_types & target_bsp_types:
            return exact_bsp, "exact", None
        return exact_bsp, "exact", "type_changed"

    signal_bsp = current_bsp_by_identity.get(pending.signal_identity)
    if signal_bsp is not None:
        current_types = bsp_type_set(signal_bsp)
        if bool(signal_bsp.is_buy) != (pending.sample.signal_time is not None and pending.signal_identity[1] == "buy"):
            return signal_bsp, "signal_time", "direction_changed"
        if current_types & target_bsp_types:
            return signal_bsp, "signal_time", None
        return signal_bsp, "signal_time", "type_changed"

    return None, "missing", "missing_bsp"


def collect_point_in_time_samples_for_code(
    *,
    code: str,
    begin_time: str,
    end_time: Optional[str],
    target_is_buy: bool,
    target_bsp_types: Set[str],
    build_chan_fn: Callable[[str, str, Optional[str]], object],
    feature_builder: FeatureBuilder,
    exit_reason_positive: str,
    exit_reason_negative: str,
    decision_delay_bars: int = 0,
) -> Tuple[str, List[SignalSample]]:
    if decision_delay_bars < 0:
        raise ValueError("decision_delay_bars 不能小于 0")

    parent_dates, parent_context_by_date = build_parent_level_context(code, begin_time, end_time)
    chan = build_chan_fn(code, begin_time, end_time)
    signal_side = "buy" if target_is_buy else "sell"
    seen_keys = set()
    samples: List[SignalSample] = []

    for snapshot in chan.step_load():
        level_chan = snapshot[MODEL_LV_IDX]
        child_level_chan = snapshot[CHILD_LV_IDX]
        final_klus = list(level_chan.klu_iter())
        if not final_klus:
            continue
        decision_klu = final_klus[-1]
        decision_klu_idx = int(decision_klu.idx)
        decision_time = ctime_to_str(decision_klu.time)
        pos_by_idx = {int(klu.idx): pos for pos, klu in enumerate(final_klus)}
        sorted_bsp_list = level_chan.bs_point_lst.getSortedBspList()
        current_target_bsp_by_key = target_bsp_by_key(
            code=code,
            signal_side=signal_side,
            sorted_bsp_list=sorted_bsp_list,
            target_is_buy=target_is_buy,
            target_bsp_types=target_bsp_types,
        )

        for bi in level_chan.bi_list:
            if not bi.is_sure:
                continue
            if target_is_buy and not bi.is_down():
                continue
            if not target_is_buy and not bi.is_up():
                continue

            entry_klu = bi.get_end_klu()
            entry_klu_idx = int(entry_klu.idx)
            if decision_klu_idx - entry_klu_idx < decision_delay_bars:
                continue

            key = sample_key(code, signal_side, bi)
            if key in seen_keys:
                continue

            pos = pos_by_idx.get(entry_klu_idx)
            if pos is None:
                continue

            bsp = current_target_bsp_by_key.get(key)
            feature = feature_builder(
                final_klus,
                pos,
                bi,
                target_is_buy,
                sorted_bsp_list,
                pick_parent_context(parent_dates, parent_context_by_date, entry_klu),
                child_level_chan,
            )
            sample = SignalSample(
                code=code,
                bsp_klu_idx=int(bsp.klu.idx) if bsp is not None else entry_klu_idx,
                open_klu_idx=entry_klu_idx,
                open_time=decision_time,
                entry_price=float(entry_klu.close),
                feature=feature,
                label=1 if bsp is not None else 0,
                signal_time=ctime_to_str(entry_klu.time),
                decision_time=decision_time,
                bi_begin_time=ctime_to_str(bi.get_begin_klu().time),
                bi_end_time=ctime_to_str(entry_klu.time),
                bi_direction=bi_direction_text(bi),
                label_mode="point_in_time",
                label_source="as_of_replay",
            )
            sample.exit_reason = exit_reason_positive if sample.label == 1 else exit_reason_negative
            samples.append(sample)
            seen_keys.add(key)

    return code, samples


def collect_bsp_stability_samples_for_code(
    *,
    code: str,
    begin_time: str,
    end_time: Optional[str],
    target_is_buy: bool,
    target_bsp_types: Set[str],
    dependency_bsp_types: Set[str],
    build_chan_fn: Callable[[str, str, Optional[str]], object],
    feature_builder: FeatureBuilder,
    decision_delay_bars: int = 0,
    stability_bars: int = 16,
    stability_bis: int = 0,
    stability_days: int = 0,
    stability_window_mode: str = "any",
) -> Tuple[str, List[SignalSample]]:
    if decision_delay_bars < 0:
        raise ValueError("decision_delay_bars 不能小于 0")
    if stability_bars < 0 or stability_bis < 0 or stability_days < 0:
        raise ValueError("stability_bars/stability_bis/stability_days 不能小于 0")
    if stability_window_mode not in {"any", "all"}:
        raise ValueError("stability_window_mode 只能是 any 或 all")

    parent_dates, parent_context_by_date = build_parent_level_context(code, begin_time, end_time)
    chan = build_chan_fn(code, begin_time, end_time)
    signal_side = "buy" if target_is_buy else "sell"
    seen_keys = set()
    pending_by_key: Dict[Tuple[str, str, str, str, str], PendingStabilitySample] = {}
    samples: List[SignalSample] = []

    for snapshot in chan.step_load():
        level_chan = snapshot[MODEL_LV_IDX]
        child_level_chan = snapshot[CHILD_LV_IDX]
        final_klus = list(level_chan.klu_iter())
        if not final_klus:
            continue
        decision_klu = final_klus[-1]
        decision_klu_idx = int(decision_klu.idx)
        decision_time = ctime_to_str(decision_klu.time)
        pos_by_idx = {int(klu.idx): pos for pos, klu in enumerate(final_klus)}
        sorted_bsp_list = level_chan.bs_point_lst.getSortedBspList()
        latest_bi_idx = latest_confirmed_bi_idx(level_chan)
        current_target_bsp_by_key = target_bsp_by_key(
            code=code,
            signal_side=signal_side,
            sorted_bsp_list=sorted_bsp_list,
            target_is_buy=target_is_buy,
            target_bsp_types=target_bsp_types,
        )
        current_bsp_by_key = bsp_by_key(
            code=code,
            signal_side=signal_side,
            sorted_bsp_list=sorted_bsp_list,
            target_is_buy=target_is_buy,
        )
        current_bsp_by_identity = bsp_by_signal_identity(
            code=code,
            signal_side=signal_side,
            sorted_bsp_list=sorted_bsp_list,
            target_is_buy=target_is_buy,
        )

        closed_keys = []
        for pending_key, pending in pending_by_key.items():
            matched_bsp, match_level, unstable_reason = match_pending_bsp(
                pending,
                current_bsp_by_key,
                current_bsp_by_identity,
                target_bsp_types,
            )
            if matched_bsp is not None:
                pending.last_match_time = decision_time
                pending.last_match_bi_begin_time = ctime_to_str(matched_bsp.bi.get_begin_klu().time)
                pending.last_match_bi_end_time = ctime_to_str(matched_bsp.bi.get_end_klu().time)
                pending.last_match_bsp_types = type_text(bsp_type_set(matched_bsp))
            pending.match_level = match_level
            pending.unstable_reason = unstable_reason

            is_closed, close_reason = window_closed(
                pending=pending,
                current_time=decision_time,
                decision_klu_idx=decision_klu_idx,
                latest_bi_idx=latest_bi_idx,
                stability_bars=stability_bars,
                stability_bis=stability_bis,
                stability_days=stability_days,
                stability_window_mode=stability_window_mode,
            )
            if not is_closed:
                continue

            sample = pending.sample
            sample.label = 1 if unstable_reason is None else 0
            sample.exit_reason = "stable_bsp" if sample.label == 1 else f"unstable_{unstable_reason}"
            sample.label_mode = "point_in_time_stability"
            sample.label_source = "as_of_replay_stability"
            setattr(sample, "label_task", "bsp_stability")
            setattr(sample, "stability_label", sample.label)
            setattr(sample, "stability_bars", stability_bars)
            setattr(sample, "stability_bis", stability_bis)
            setattr(sample, "stability_days", stability_days)
            setattr(sample, "stability_window_mode", stability_window_mode)
            setattr(sample, "window_close_time", decision_time)
            setattr(sample, "window_close_reason", close_reason)
            setattr(sample, "last_match_time", pending.last_match_time)
            setattr(sample, "last_match_bi_begin_time", pending.last_match_bi_begin_time)
            setattr(sample, "last_match_bi_end_time", pending.last_match_bi_end_time)
            setattr(sample, "last_match_bsp_types", pending.last_match_bsp_types)
            setattr(sample, "match_level", pending.match_level)
            setattr(sample, "unstable_reason", unstable_reason)
            samples.append(sample)
            closed_keys.append(pending_key)

        for pending_key in closed_keys:
            pending_by_key.pop(pending_key, None)

        for bi in level_chan.bi_list:
            if not bi.is_sure:
                continue
            if target_is_buy and not bi.is_down():
                continue
            if not target_is_buy and not bi.is_up():
                continue

            entry_klu = bi.get_end_klu()
            entry_klu_idx = int(entry_klu.idx)
            if decision_klu_idx - entry_klu_idx < decision_delay_bars:
                continue

            key = sample_key(code, signal_side, bi)
            if key in seen_keys:
                continue
            bsp = current_target_bsp_by_key.get(key)
            if bsp is None:
                continue

            pos = pos_by_idx.get(entry_klu_idx)
            if pos is None:
                continue

            feature = feature_builder(
                final_klus,
                pos,
                bi,
                target_is_buy,
                sorted_bsp_list,
                pick_parent_context(parent_dates, parent_context_by_date, entry_klu),
                child_level_chan,
            )

            sample = SignalSample(
                code=code,
                bsp_klu_idx=int(bsp.klu.idx),
                open_klu_idx=entry_klu_idx,
                open_time=decision_time,
                entry_price=float(entry_klu.close),
                feature=feature,
                label=None,
                signal_time=ctime_to_str(entry_klu.time),
                decision_time=decision_time,
                bi_begin_time=ctime_to_str(bi.get_begin_klu().time),
                bi_end_time=ctime_to_str(entry_klu.time),
                bi_direction=bi_direction_text(bi),
                label_mode="point_in_time_stability",
                label_source="as_of_replay_stability",
            )
            setattr(sample, "first_seen_bsp_types", type_text(bsp_type_set(bsp)))
            setattr(sample, "first_seen_bsp_side", signal_side)
            setattr(sample, "label_task", "bsp_stability")
            pending_by_key[key] = PendingStabilitySample(
                sample=sample,
                sample_key=key,
                signal_identity=signal_identity(code, signal_side, bi),
                first_seen_klu_idx=decision_klu_idx,
                first_seen_bi_idx=int(bi.idx),
                first_seen_bsp_types=bsp_type_set(bsp),
                last_match_time=decision_time,
                last_match_bi_begin_time=ctime_to_str(bi.get_begin_klu().time),
                last_match_bi_end_time=ctime_to_str(entry_klu.time),
                last_match_bsp_types=type_text(bsp_type_set(bsp)),
            )
            seen_keys.add(key)

    return code, samples
