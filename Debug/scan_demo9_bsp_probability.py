from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from Debug.bsp_probability_scan_common import BspProbabilityScanConfig, ROOT_DIR, run_cli


BASE_KEY_FEATURES = (
    "candidate_divergence_rate",
    "candidate_break_prev_extreme",
    "entry_close_pos",
    "child_close_pos",
    "parent_range",
    "ma_dist_10",
    "prev_bsp_divergence_rate",
)
SECOND_KEY_FEATURES = (
    "prev_first_bsp_exists",
    "prev_first_bsp_type_1",
    "prev_first_bsp_type_1p",
    "prev_first_bsp_bi_gap",
    "prev_first_bsp_klu_gap",
    "entry_vs_prev_first_bsp_price",
    "retracement_from_prev_first",
    "prev_first_bsp_divergence_rate",
)


CONFIG = BspProbabilityScanConfig(
    model_name="demo9",
    target_group="second",
    target_bsp_types=("2", "2s"),
    dependency_bsp_types=("1", "1p"),
    main_bs_type="1,1p,2,2s",
    default_buy_model_dir=ROOT_DIR / "Debug" / "model_output" / "strategy_demo9_buy",
    default_sell_model_dir=ROOT_DIR / "Debug" / "model_output" / "strategy_demo9_sell",
    default_output_dir=ROOT_DIR / "Debug" / "model_output" / "strategy_demo9_scan",
    feature_names=(*BASE_KEY_FEATURES, *SECOND_KEY_FEATURES),
    description="使用 demo9 训练模型扫描30M确认笔的二类买卖点概率。",
)


if __name__ == "__main__":
    run_cli(CONFIG)
