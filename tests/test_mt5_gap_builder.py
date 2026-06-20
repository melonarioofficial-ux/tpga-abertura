from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from tpga.mt5_gap_builder import GapSessionConfig, build_gap_dataset_from_bars, parse_date


def _fake_m1_bars():
    tz = ZoneInfo("America/Sao_Paulo")
    times = pd.date_range(
        datetime(2026, 1, 2, 16, 0, tzinfo=tz),
        datetime(2026, 1, 2, 19, 5, tzinfo=tz),
        freq="min",
    )
    n = len(times)
    close = 1000 + np.linspace(0, 10, n)
    open_ = close - 0.5
    # force target close/open values
    idx_close = list(times).index(pd.Timestamp(datetime(2026, 1, 2, 17, 59, tzinfo=tz)))
    idx_open = list(times).index(pd.Timestamp(datetime(2026, 1, 2, 19, 0, tzinfo=tz)))
    close[idx_close] = 1010.0
    open_[idx_open] = 1025.0
    return pd.DataFrame({
        "time": times.tz_convert("UTC"),
        "time_local": times,
        "open": open_,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "tick_volume": np.arange(n) + 100,
        "spread": np.full(n, 20),
        "real_volume": np.zeros(n),
    })


def test_build_gap_dataset_from_bars_uses_close_and_open():
    cfg = GapSessionConfig(symbol="NDX100", close_time="17:59", open_time="19:00", signal_time="17:49")
    df = build_gap_dataset_from_bars(_fake_m1_bars(), parse_date("2026-01-02"), parse_date("2026-01-02"), cfg)
    assert len(df) == 1
    row = df.iloc[0]
    assert row["prev_close"] == 1010.0
    assert row["open"] == 1025.0
    assert "17:49" in row["feature_time_local"]
    assert row["macro_event_flag"] == 0
