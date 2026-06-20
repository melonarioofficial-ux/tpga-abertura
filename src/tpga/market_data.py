"""Busca dados de mercado pré-abertura via yfinance (import opcional)."""
from __future__ import annotations

import numpy as np
import logging

logger = logging.getLogger(__name__)


def fetch_premarket_features(symbol_futures: str = "NQ=F") -> dict:
    result = {
        "futures_overnight_ret": np.nan,
        "qqq_premarket_ret": np.nan,
        "spy_premarket_ret": np.nan,
        "weighted_bigtech_premarket_ret": np.nan,
        "vix_ret": np.nan,
        "dxy_ret": np.nan,
        "us10y_ret": np.nan,
    }
    try:
        import yfinance as yf
        import pandas as pd

        def safe_ret(ticker, period="2d", interval="1d", prepost=False):
            try:
                df = yf.download(ticker, period=period, interval=interval,
                                 prepost=prepost, progress=False, auto_adjust=True)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [c[0] for c in df.columns]
                if df.empty or len(df) < 2:
                    return np.nan
                closes = df["Close"].dropna()
                if len(closes) < 2:
                    return np.nan
                return float(np.log(closes.iloc[-1] / closes.iloc[-2]))
            except Exception as e:
                logger.warning(f"Falha ao baixar {ticker}: {e}")
                return np.nan

        result["futures_overnight_ret"] = safe_ret(symbol_futures, period="5d", interval="1h")
        result["qqq_premarket_ret"] = safe_ret("QQQ", prepost=True)
        result["spy_premarket_ret"] = safe_ret("SPY", prepost=True)
        result["vix_ret"] = safe_ret("^VIX")
        result["dxy_ret"] = safe_ret("DX-Y.NYB")
        result["us10y_ret"] = safe_ret("^TNX")

        bigtechs = {"AAPL": 0.12, "MSFT": 0.12, "NVDA": 0.08, "AMZN": 0.07, "META": 0.05}
        bigtech_rets = []
        bigtech_weights = []
        for tkr, w in bigtechs.items():
            r = safe_ret(tkr, prepost=True)
            if np.isfinite(r):
                bigtech_rets.append(r)
                bigtech_weights.append(w)
        if bigtech_rets:
            total_w = sum(bigtech_weights)
            result["weighted_bigtech_premarket_ret"] = sum(
                r * w / total_w for r, w in zip(bigtech_rets, bigtech_weights)
            )
    except ImportError:
        logger.warning("yfinance não instalado. Features macro ficarão como NaN.")
    except Exception as e:
        logger.warning(f"Erro ao buscar dados de mercado: {e}")

    return result
