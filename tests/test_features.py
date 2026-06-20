import pandas as pd
from tpga.synthetic_data import make_synthetic_gap_data
from tpga.features import build_features


def test_build_features_has_labels():
    df = make_synthetic_gap_data(n=180, seed=1)
    out, features = build_features(df)
    assert "gap_points" in out.columns
    assert "direction" in out.columns
    assert "fakeout_risk" in out.columns
    assert len(features) > 10
    assert set(out["direction"].unique()).issubset({"up", "down", "flat"})
