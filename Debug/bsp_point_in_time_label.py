from __future__ import annotations

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
