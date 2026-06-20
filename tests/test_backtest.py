from tpga.synthetic_data import make_synthetic_gap_data
from tpga.backtest import WalkForwardConfig, walk_forward_validate


def test_walk_forward_validate_runs():
    df = make_synthetic_gap_data(n=220, seed=2)
    cfg = WalkForwardConfig(min_train_size=120, test_size=30, step_size=30, random_state=7)
    pred, metrics = walk_forward_validate(df, cfg)
    assert len(pred) > 0
    assert "p_up" in pred.columns
    assert "edge" in pred.columns
    assert "probabilistic" in metrics
    assert metrics["folds"] >= 1
