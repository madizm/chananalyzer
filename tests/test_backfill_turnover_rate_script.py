from scripts.backfill_turnover_rate import calc_turnover_rate, normalize_kl_type


def test_normalize_kl_type_accepts_common_aliases():
    assert normalize_kl_type("day") == "DAY"
    assert normalize_kl_type("K_DAY") == "DAY"
    assert normalize_kl_type("30m") == "30M"
    assert normalize_kl_type("K_60M") == "60M"


def test_calc_turnover_rate_uses_tdx_units():
    assert calc_turnover_rate(2500.0, 5000.0) == 0.005
    assert calc_turnover_rate(0.0, 5000.0) == 0.0
    assert calc_turnover_rate(2500.0, None) is None
