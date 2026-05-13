from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from Debug.bsp_probability_scan_common import BspProbabilityScanConfig, ROOT_DIR, run_cli


KEY_FEATURES = (
    "candidate_divergence_rate",
    "candidate_break_prev_extreme",
    "entry_close_pos",
    "child_close_pos",
    "parent_range",
    "ma_dist_10",
    "prev_bsp_divergence_rate",
)


CONFIG = BspProbabilityScanConfig(
    model_name="demo8",
    target_group="first",
    target_bsp_types=("1", "1p"),
    dependency_bsp_types=(),
    main_bs_type="1,1p",
    default_buy_model_dir=ROOT_DIR / "Debug" / "model_output" / "strategy_demo8_buy",
    default_sell_model_dir=ROOT_DIR / "Debug" / "model_output" / "strategy_demo8_sell",
    default_output_dir=ROOT_DIR / "Debug" / "model_output" / "strategy_demo8_scan",
    feature_names=KEY_FEATURES,
    description="使用 demo8 训练模型扫描30M确认笔的一类买卖点概率。",
)


if __name__ == "__main__":
    run_cli(CONFIG)
