from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date, time
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pandas as pd


class MT5UnavailableError(RuntimeError):
    """Raised when the MetaTrader5 Python package or terminal is unavailable."""


def import_mt5():
    try:
        import MetaTrader5 as mt5  # type: ignore
        return mt5
    except Exception as exc:  # pragma: no cover - depends on Windows/MT5 installation
        raise MT5UnavailableError(
            "Pacote MetaTrader5 não encontrado ou indisponível. No Windows, com o venv ativo, rode: "
            "pip install -r requirements-mt5.txt. O terminal MetaTrader 5 também precisa estar instalado e logado."
        ) from exc


@dataclass(frozen=True)
class MT5ConnectionConfig:
    symbol: str
    terminal_path: Optional[str] = None
    login: Optional[int] = None
    password: Optional[str] = None
    server: Optional[str] = None
    timeout_ms: int = 60000
    portable: bool = False


@dataclass(frozen=True)
class MT5Status:
    ok: bool
    version: str | None
    terminal_company: str | None
    terminal_name: str | None
    account_login: int | None
    account_server: str | None
    symbol: str
    symbol_visible: bool
    bid: float | None
    ask: float | None
    spread_points: float | None
    last_error: Any | None = None


def _timeframe_value(mt5: Any, timeframe: str) -> Any:
    tf = timeframe.upper().strip()
    mapping = {
        "M1": mt5.TIMEFRAME_M1,
        "M2": getattr(mt5, "TIMEFRAME_M2", mt5.TIMEFRAME_M1),
        "M3": getattr(mt5, "TIMEFRAME_M3", mt5.TIMEFRAME_M1),
        "M5": mt5.TIMEFRAME_M5,
        "M10": getattr(mt5, "TIMEFRAME_M10", mt5.TIMEFRAME_M5),
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
    }
    if tf not in mapping:
        raise ValueError(f"Timeframe não suportado: {timeframe}. Use M1, M5, M15, M30, H1, H4 ou D1.")
    return mapping[tf]


def local_dt(day: date, hhmm: str, tz_name: str) -> datetime:
    hh, mm = [int(x) for x in hhmm.split(":", 1)]
    return datetime.combine(day, time(hh, mm), tzinfo=ZoneInfo(tz_name))


class MT5Client:
    """Small safe wrapper around the official MetaTrader5 Python bridge.

    This class reads market data only. It does not send orders.
    """

    def __init__(self, config: MT5ConnectionConfig):
        self.config = config
        self.mt5 = import_mt5()
        self._initialized = False

    def __enter__(self) -> "MT5Client":
        self.initialize()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.shutdown()

    def initialize(self) -> None:
        kwargs: dict[str, Any] = {"timeout": self.config.timeout_ms, "portable": self.config.portable}
        if self.config.login is not None:
            kwargs["login"] = int(self.config.login)
        if self.config.password:
            kwargs["password"] = self.config.password
        if self.config.server:
            kwargs["server"] = self.config.server

        if self.config.terminal_path:
            ok = self.mt5.initialize(self.config.terminal_path, **kwargs)
        else:
            ok = self.mt5.initialize(**kwargs)
        if not ok:
            raise RuntimeError(f"Falha ao inicializar MT5: {self.mt5.last_error()}")
        self._initialized = True
        self.ensure_symbol(self.config.symbol)

    def shutdown(self) -> None:
        if self._initialized:
            self.mt5.shutdown()
            self._initialized = False

    def ensure_symbol(self, symbol: str) -> None:
        info = self.mt5.symbol_info(symbol)
        if info is None:
            raise ValueError(f"Símbolo não encontrado no MT5: {symbol}. Confira se no Market Watch é NAS100, NDX100, US100 etc.")
        if not info.visible:
            if not self.mt5.symbol_select(symbol, True):
                raise RuntimeError(f"Não consegui selecionar o símbolo {symbol}: {self.mt5.last_error()}")

    def status(self) -> MT5Status:
        terminal = self.mt5.terminal_info()
        account = self.mt5.account_info()
        symbol_info = self.mt5.symbol_info(self.config.symbol)
        tick = self.mt5.symbol_info_tick(self.config.symbol)
        point = getattr(symbol_info, "point", None) if symbol_info else None
        bid = float(tick.bid) if tick and getattr(tick, "bid", None) is not None else None
        ask = float(tick.ask) if tick and getattr(tick, "ask", None) is not None else None
        spread = None
        if bid is not None and ask is not None and point:
            spread = (ask - bid) / point
        version = None
        try:
            version_tuple = self.mt5.version()
            version = ".".join(str(x) for x in version_tuple) if version_tuple else None
        except Exception:
            version = None
        return MT5Status(
            ok=True,
            version=version,
            terminal_company=getattr(terminal, "company", None) if terminal else None,
            terminal_name=getattr(terminal, "name", None) if terminal else None,
            account_login=int(account.login) if account else None,
            account_server=getattr(account, "server", None) if account else None,
            symbol=self.config.symbol,
            symbol_visible=bool(getattr(symbol_info, "visible", False)) if symbol_info else False,
            bid=bid,
            ask=ask,
            spread_points=spread,
            last_error=self.mt5.last_error(),
        )

    @staticmethod
    def _empty_rates_frame() -> pd.DataFrame:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume", "time_local"])

    @staticmethod
    def _rates_to_frame(rates: Any, tz_name: str) -> pd.DataFrame:
        df = pd.DataFrame(rates)
        if df.empty:
            return MT5Client._empty_rates_frame()
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df["time_local"] = df["time"].dt.tz_convert(tz_name)
        return df.sort_values("time").reset_index(drop=True)

    def copy_rates_range(self, symbol: str, timeframe: str, start_local: datetime, end_local: datetime, tz_name: str) -> pd.DataFrame:
        """Read a date range from MT5.

        Some brokers/terminal builds reject timezone-aware datetimes with
        `Terminal: Invalid params`. To avoid breaking the robot, this method
        first tries copy_rates_range and then falls back to online recent bars
        pulled with copy_rates_from_pos, filtering the requested interval in
        memory. This keeps all data real/online and avoids CSV dependency.
        """
        self.ensure_symbol(symbol)
        tf = _timeframe_value(self.mt5, timeframe)
        start_utc = start_local.astimezone(ZoneInfo("UTC"))
        end_utc = end_local.astimezone(ZoneInfo("UTC"))
        attempts = [
            (start_utc, end_utc),
            (start_utc.replace(tzinfo=None), end_utc.replace(tzinfo=None)),
        ]
        last_error = None
        for a, b in attempts:
            rates = self.mt5.copy_rates_range(symbol, tf, a, b)
            if rates is not None:
                return self._rates_to_frame(rates, tz_name)
            last_error = self.mt5.last_error()

        # Robust fallback: ask the terminal for recent online bars by position.
        # For M1, estimate one bar per minute plus a 20% safety buffer. Other
        # timeframes still work because extra bars only increase coverage.
        span_minutes = max(1, int((end_utc - start_utc).total_seconds() // 60))
        fallback_count = min(max(int(span_minutes * 1.25) + 5000, 10000), 500000)
        recent = self.copy_rates_from_pos(symbol, timeframe, 0, fallback_count, tz_name)
        if recent.empty:
            raise RuntimeError(f"MT5 copy_rates_range/copy_rates_from_pos sem dados: {last_error}")
        mask = (recent["time"] >= pd.Timestamp(start_utc)) & (recent["time"] <= pd.Timestamp(end_utc))
        out = recent.loc[mask].copy().reset_index(drop=True)
        if out.empty:
            raise RuntimeError(
                "MT5 retornou barras online, mas nenhuma caiu no intervalo pedido. "
                f"Erro original copy_rates_range={last_error}. "
                "Aumente Max. bars in chart no MT5 ou use mt5-online-once/mt5-online-validate com --history-bars maior."
            )
        return out

    def _copy_rates_from_pos_once(self, symbol: str, tf: Any, start_pos: int, count: int, tz_name: str) -> pd.DataFrame:
        """Single MT5 call. Kept separate so the public method can batch safely."""
        rates = self.mt5.copy_rates_from_pos(symbol, tf, int(start_pos), int(count))
        if rates is None:
            raise RuntimeError(f"MT5 copy_rates_from_pos retornou None: {self.mt5.last_error()}")
        return self._rates_to_frame(rates, tz_name)

    def copy_rates_from_pos(self, symbol: str, timeframe: str = "M1", start_pos: int = 0, count: int = 500, tz_name: str = "America/Sao_Paulo") -> pd.DataFrame:
        """Read real MT5 bars by position with broker-safe batching.

        Some MT5 terminals reject very large `count` values with
        `(-2, 'Terminal: Invalid params')`. The public robot commands request
        large histories, so this method splits the request into smaller chunks
        and automatically reduces chunk size if the terminal is stricter.
        The data still comes directly from the online MT5 terminal; no CSV is
        used for operation.
        """
        self.ensure_symbol(symbol)
        tf = _timeframe_value(self.mt5, timeframe)
        requested = max(1, int(count))
        pos = max(0, int(start_pos))

        # Fast path for small requests. If it fails, the robust path below will
        # retry with smaller chunks and provide a better diagnostic.
        if requested <= 2000:
            try:
                return self._copy_rates_from_pos_once(symbol, tf, pos, requested, tz_name)
            except RuntimeError:
                pass

        frames: list[pd.DataFrame] = []
        remaining = requested
        chunk = min(2000, remaining)
        last_error: Any | None = None
        total_attempts = 0

        while remaining > 0:
            this_count = min(chunk, remaining)
            while this_count >= 1:
                total_attempts += 1
                rates = self.mt5.copy_rates_from_pos(symbol, tf, int(pos), int(this_count))
                if rates is not None:
                    df = self._rates_to_frame(rates, tz_name)
                    if df.empty:
                        remaining = 0
                        break
                    frames.append(df)
                    got = len(df)
                    pos += got
                    remaining -= got
                    # Terminal returned fewer than requested: probably no more
                    # history available in chart. Stop cleanly with what we have.
                    if got < this_count:
                        remaining = 0
                    # After a successful small retry, cautiously grow back up.
                    chunk = min(2000, max(chunk, this_count))
                    break

                last_error = self.mt5.last_error()
                # Reduce aggressively on Invalid params / broker strictness.
                if this_count > 1000:
                    this_count = 1000
                elif this_count > 500:
                    this_count = 500
                elif this_count > 100:
                    this_count = 100
                elif this_count > 10:
                    this_count = 10
                else:
                    this_count = 0

            if this_count < 1:
                if not frames:
                    raise RuntimeError(
                        "MT5 copy_rates_from_pos falhou mesmo com chunk mínimo. "
                        f"symbol={symbol}, timeframe={timeframe}, tf_value={tf}, start_pos={start_pos}, "
                        f"count={count}, last_error={last_error}. "
                        "Confirme se o gráfico M1 do símbolo está carregado no MT5 e se o nome do símbolo é exatamente NDX100."
                    )
                break

        if not frames:
            return self._empty_rates_frame()

        out = pd.concat(frames, ignore_index=True)
        # Adjacent chunks can overlap in some terminal builds; remove duplicates
        # by UTC timestamp and keep chronological order.
        if "time" in out.columns:
            out = out.drop_duplicates(subset=["time"]).sort_values("time").reset_index(drop=True)
        return out

    def copy_recent_rates(self, symbol: str, timeframe: str = "M1", count: int = 500, tz_name: str = "America/Sao_Paulo") -> pd.DataFrame:
        return self.copy_rates_from_pos(symbol, timeframe, 0, int(count), tz_name)


def connection_config_from_env_or_args(
    symbol: str,
    terminal_path: str | None = None,
    login: int | None = None,
    password: str | None = None,
    server: str | None = None,
    timeout_ms: int = 60000,
) -> MT5ConnectionConfig:
    # Intentionally no automatic .env dependency. CLI passes values explicitly.
    return MT5ConnectionConfig(
        symbol=symbol,
        terminal_path=terminal_path,
        login=login,
        password=password,
        server=server,
        timeout_ms=timeout_ms,
    )
