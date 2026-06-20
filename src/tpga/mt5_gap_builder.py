from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .mt5_client import MT5Client, MT5ConnectionConfig, local_dt


@dataclass(frozen=True)
class GapSessionConfig:
    symbol: str = "NDX100"
    timezone: str = "America/Sao_Paulo"
    close_time: str = "17:59"
    open_time: str = "19:00"
    signal_time: str | None = None
    lookback_minutes: int = 240
    bar_tolerance_minutes: int = 10
    timeframe: str = "M1"


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _prepare_m1(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    out = df.copy().sort_values("time_local").reset_index(drop=True)
    for col in ["open", "high", "low", "close", "tick_volume", "spread", "real_volume"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    out["ret_1m"] = np.log(out["close"] / out["close"].shift(1))
    return out


def _previous_bar_at_or_before(df: pd.DataFrame, dt_local: datetime, tolerance_minutes: int) -> pd.Series | None:
    if df.empty:
        return None
    mask = df["time_local"] <= pd.Timestamp(dt_local)
    sub = df.loc[mask]
    if sub.empty:
        return None
    row = sub.iloc[-1]
    delta = pd.Timestamp(dt_local) - row["time_local"]
    if delta > pd.Timedelta(minutes=tolerance_minutes):
        return None
    return row


def _first_bar_at_or_after(df: pd.DataFrame, dt_local: datetime, tolerance_minutes: int) -> pd.Series | None:
    if df.empty:
        return None
    mask = df["time_local"] >= pd.Timestamp(dt_local)
    sub = df.loc[mask]
    if sub.empty:
        return None
    row = sub.iloc[0]
    delta = row["time_local"] - pd.Timestamp(dt_local)
    if delta > pd.Timedelta(minutes=tolerance_minutes):
        return None
    return row


def _window_before(df: pd.DataFrame, end_dt: datetime, minutes: int) -> pd.DataFrame:
    start = pd.Timestamp(end_dt) - pd.Timedelta(minutes=minutes)
    end = pd.Timestamp(end_dt)
    return df[(df["time_local"] <= end) & (df["time_local"] > start)].copy()


def _safe_log(a: float, b: float) -> float:
    if not np.isfinite(a) or not np.isfinite(b) or a <= 0 or b <= 0:
        return np.nan
    return float(np.log(a / b))


def _ret_lookback(win: pd.DataFrame, minutes: int) -> float:
    if len(win) < minutes + 1:
        return np.nan
    close_now = float(win["close"].iloc[-1])
    close_then = float(win["close"].iloc[-minutes - 1])
    return _safe_log(close_now, close_then)


def _vwap_distance(win: pd.DataFrame) -> float:
    if win.empty:
        return np.nan
    vol = win["tick_volume"].replace(0, np.nan).fillna(0)
    if vol.sum() <= 0:
        return np.nan
    vwap = float((win["close"] * vol).sum() / vol.sum())
    last = float(win["close"].iloc[-1])
    if not np.isfinite(vwap) or vwap == 0:
        return np.nan
    return float((last - vwap) / vwap)


def _range_position(win: pd.DataFrame) -> float:
    if win.empty:
        return np.nan
    low = float(win["low"].min())
    high = float(win["high"].max())
    last = float(win["close"].iloc[-1])
    if not np.isfinite(high - low) or high == low:
        return np.nan
    return float((last - low) / (high - low))


def _volume_z(win: pd.DataFrame, baseline_minutes: int = 60) -> float:
    if len(win) < 10:
        return np.nan
    vols = win["tick_volume"].tail(baseline_minutes + 1).astype(float)
    last = float(vols.iloc[-1])
    base = vols.iloc[:-1]
    std = float(base.std(ddof=0))
    if not np.isfinite(std) or std == 0:
        return 0.0
    return float((last - float(base.mean())) / std)


def _realized_vol(win: pd.DataFrame, minutes: int = 30) -> float:
    if len(win) < minutes + 1 or "ret_1m" not in win:
        return np.nan
    ret = win["ret_1m"].tail(minutes).dropna()
    if len(ret) < 5:
        return np.nan
    return float(ret.std(ddof=0) * np.sqrt(minutes))


def build_gap_dataset_from_bars(m1_bars: pd.DataFrame, start_date: date, end_date: date, cfg: GapSessionConfig) -> pd.DataFrame:
    bars = _prepare_m1(m1_bars)
    rows: list[dict] = []
    day = start_date
    while day <= end_date:
        close_dt = local_dt(day, cfg.close_time, cfg.timezone)
        open_dt = local_dt(day, cfg.open_time, cfg.timezone)
        if open_dt <= close_dt:
            open_dt = open_dt + timedelta(days=1)
        signal_dt = local_dt(day, cfg.signal_time, cfg.timezone) if cfg.signal_time else close_dt

        close_bar = _previous_bar_at_or_before(bars, close_dt, cfg.bar_tolerance_minutes)
        open_bar = _first_bar_at_or_after(bars, open_dt, cfg.bar_tolerance_minutes)
        feature_bar = _previous_bar_at_or_before(bars, signal_dt, cfg.bar_tolerance_minutes)
        feature_win = _window_before(bars, signal_dt, max(cfg.lookback_minutes, 260))

        if close_bar is not None and open_bar is not None and feature_bar is not None and len(feature_win) >= 20:
            prev_close = float(close_bar["close"])
            open_price = float(open_bar["open"])
            spread_points = float(feature_bar.get("spread", np.nan)) if "spread" in feature_bar else np.nan
            rows.append({
                "session_date": day.isoformat(),
                "symbol": cfg.symbol,
                "timezone": cfg.timezone,
                "close_time_local": pd.Timestamp(close_bar["time_local"]).isoformat(),
                "open_time_local": pd.Timestamp(open_bar["time_local"]).isoformat(),
                "feature_time_local": pd.Timestamp(feature_bar["time_local"]).isoformat(),
                "prev_close": prev_close,
                "open": open_price,
                "last_1m_ret": _ret_lookback(feature_win, 1),
                "last_5m_ret": _ret_lookback(feature_win, 5),
                "last_15m_ret": _ret_lookback(feature_win, 15),
                "close_volume_z": _volume_z(feature_win, 60),
                "vwap_distance": _vwap_distance(feature_win.tail(cfg.lookback_minutes)),
                "range_position": _range_position(feature_win.tail(cfg.lookback_minutes)),
                "realized_vol_30m": _realized_vol(feature_win, 30),
                "mt5_spread_points_at_signal": spread_points,
                # Real MT5 broker-session build intentionally leaves cross-market fields empty.
                # Fill these later only if they were available before the signal, otherwise it is leakage.
                "futures_overnight_ret": np.nan,
                "qqq_premarket_ret": np.nan,
                "spy_premarket_ret": np.nan,
                "weighted_bigtech_premarket_ret": np.nan,
                "vix_ret": np.nan,
                "dxy_ret": np.nan,
                "us10y_ret": np.nan,
                "macro_event_flag": 0,
                "earnings_risk_flag": 0,
                "noii_imbalance_side": "",
                "noii_imbalance_shares": np.nan,
                "noii_paired_shares": np.nan,
                "noii_near_price": np.nan,
                "noii_far_price": np.nan,
                "noii_reference_price": np.nan,
            })
        day += timedelta(days=1)
    return pd.DataFrame(rows)


def fetch_m1_bars_from_mt5(conn: MT5ConnectionConfig, start_date: date, end_date: date, cfg: GapSessionConfig) -> pd.DataFrame:
    tz = ZoneInfo(cfg.timezone)
    start_local = datetime.combine(start_date - timedelta(days=2), datetime.min.time(), tzinfo=tz)
    end_local = datetime.combine(end_date + timedelta(days=2), datetime.max.time(), tzinfo=tz)
    with MT5Client(conn) as client:
        return client.copy_rates_range(cfg.symbol, cfg.timeframe, start_local, end_local, cfg.timezone)


def build_gap_dataset_from_mt5(conn: MT5ConnectionConfig, start_date: date, end_date: date, cfg: GapSessionConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    bars = fetch_m1_bars_from_mt5(conn, start_date, end_date, cfg)
    dataset = build_gap_dataset_from_bars(bars, start_date, end_date, cfg)
    return dataset, bars


def fetch_online_bars_from_mt5(conn: MT5ConnectionConfig, cfg: GapSessionConfig, history_bars: int = 200000) -> pd.DataFrame:
    """Pull real online bars from the active MT5 terminal without using CSV.

    This uses copy_rates_from_pos instead of copy_rates_range, because several
    broker terminals reject range datetimes with `Terminal: Invalid params`.
    The returned bars are still real MT5 market data; they are simply filtered
    and modeled in memory.
    """
    with MT5Client(conn) as client:
        return client.copy_rates_from_pos(cfg.symbol, cfg.timeframe, 0, int(history_bars), cfg.timezone)


def infer_date_span_from_bars(bars: pd.DataFrame, warmup_days: int = 3) -> tuple[date, date]:
    if bars.empty or "time_local" not in bars.columns:
        raise ValueError("MT5 não retornou barras suficientes para inferir período histórico.")
    local_dates = pd.to_datetime(bars["time_local"]).dt.date
    start = min(local_dates) + timedelta(days=warmup_days)
    end = max(local_dates)
    if start > end:
        raise ValueError("Histórico MT5 curto demais para montar sessões de gap.")
    return start, end


def build_gap_dataset_online_from_mt5(
    conn: MT5ConnectionConfig,
    cfg: GapSessionConfig,
    history_bars: int = 200000,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    bars = fetch_online_bars_from_mt5(conn, cfg, history_bars=history_bars)
    start_date, end_date = infer_date_span_from_bars(bars)
    dataset = build_gap_dataset_from_bars(bars, start_date, end_date, cfg)
    return dataset, bars


def save_dataframe(path: str | Path, df: pd.DataFrame) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
