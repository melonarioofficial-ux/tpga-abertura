from __future__ import annotations

import argparse
from pathlib import Path
from time import sleep
import json
import yaml

from .data_schema import load_gap_csv, validate_input_frame
from .synthetic_data import make_synthetic_gap_data
from .backtest import WalkForwardConfig, walk_forward_validate
from .report import save_report, save_predictions
from .mt5_client import MT5Client, MT5ConnectionConfig
from .mt5_gap_builder import GapSessionConfig, parse_date, build_gap_dataset_from_mt5, build_gap_dataset_online_from_mt5, save_dataframe
from .live_signal import build_current_feature_row, train_and_score_current


def load_yaml_config(path: str | None) -> dict:
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def config_from_dict(d: dict) -> WalkForwardConfig:
    label = d.get("label", {})
    bt = d.get("backtest", {})
    val = d.get("validation", {})
    return WalkForwardConfig(
        min_train_size=int(val.get("min_train_size", 120)),
        test_size=int(val.get("test_size", 30)),
        step_size=int(val.get("step_size", 30)),
        random_state=int(val.get("random_state", 42)),
        flat_threshold_points=float(label.get("flat_threshold_points", 5.0)),
        edge_threshold=float(bt.get("edge_threshold", 0.12)),
        confidence_threshold=float(bt.get("confidence_threshold", 0.48)),
        fakeout_max=float(bt.get("fakeout_max", 0.70)),
        cost_points=float(bt.get("cost_points", 2.0)),
    )


def apply_runtime_overrides(cfg: WalkForwardConfig, args) -> WalkForwardConfig:
    """Allow online commands to run safely while the MT5 terminal is still warming history.

    Scientific validation should keep the default 120+ sessions. For live online
    debugging, the user can pass --min-train-size 30 so the robot produces a
    low-history paper signal instead of failing.
    """
    min_train_size = getattr(args, "min_train_size", None)
    if min_train_size is None:
        return cfg
    return WalkForwardConfig(
        min_train_size=int(min_train_size),
        test_size=cfg.test_size,
        step_size=cfg.step_size,
        random_state=cfg.random_state,
        flat_threshold_points=cfg.flat_threshold_points,
        edge_threshold=cfg.edge_threshold,
        confidence_threshold=cfg.confidence_threshold,
        fakeout_max=cfg.fakeout_max,
        cost_points=cfg.cost_points,
    )


def history_quality_label(sessions_valid: int) -> str:
    if sessions_valid >= 300:
        return "ROBUST"
    if sessions_valid >= 120:
        return "OK"
    if sessions_valid >= 60:
        return "CURTO"
    if sessions_valid >= 30:
        return "BOOTSTRAP_TESTE"
    return "INSUFICIENTE"


def run_validate_demo(args) -> int:
    cfg = config_from_dict(load_yaml_config(args.config))
    df = make_synthetic_gap_data(n=args.rows, seed=args.seed)
    predictions, metrics = walk_forward_validate(df, cfg)
    save_report(args.output, predictions, metrics, title="Relatório TPGA — Demonstração Sintética")
    if args.predictions:
        save_predictions(args.predictions, predictions)
    print(json.dumps(metrics, indent=2, ensure_ascii=False))
    print(f"Relatório salvo em: {args.output}")
    return 0


def run_make_sample(args) -> int:
    df = make_synthetic_gap_data(n=args.rows, seed=args.seed)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.output, index=False)
    print(f"Dataset sintético salvo em: {args.output}")
    return 0


def run_validate_csv(args) -> int:
    cfg = config_from_dict(load_yaml_config(args.config))
    df = load_gap_csv(args.csv)
    report = validate_input_frame(df)
    if report.missing_optional:
        print("Aviso: CSV sem várias colunas opcionais. O modelo roda, mas a teoria fica menos poderosa.")
        print("Opcionais ausentes:", ", ".join(report.missing_optional[:30]))
    predictions, metrics = walk_forward_validate(df, cfg)
    save_report(args.output, predictions, metrics, title="Relatório TPGA — CSV Real")
    if args.predictions:
        save_predictions(args.predictions, predictions)
    print(json.dumps(metrics, indent=2, ensure_ascii=False))
    print(f"Relatório salvo em: {args.output}")
    return 0


def _mt5_conn_from_args(args) -> MT5ConnectionConfig:
    return MT5ConnectionConfig(
        symbol=args.symbol,
        terminal_path=getattr(args, "terminal_path", None),
        login=getattr(args, "login", None),
        password=getattr(args, "password", None),
        server=getattr(args, "server", None),
        timeout_ms=getattr(args, "timeout_ms", 60000),
    )


def _gap_cfg_from_args(args) -> GapSessionConfig:
    return GapSessionConfig(
        symbol=args.symbol,
        timezone=getattr(args, "timezone", "America/Sao_Paulo"),
        close_time=getattr(args, "close_time", "17:59"),
        open_time=getattr(args, "open_time", "19:00"),
        signal_time=getattr(args, "signal_time", None),
        lookback_minutes=getattr(args, "lookback_minutes", 240),
        bar_tolerance_minutes=getattr(args, "bar_tolerance_minutes", 10),
        timeframe=getattr(args, "timeframe", "M1"),
    )


def run_mt5_check(args) -> int:
    conn = _mt5_conn_from_args(args)
    with MT5Client(conn) as client:
        status = client.status()
    print(json.dumps(status.__dict__, indent=2, ensure_ascii=False))
    return 0


def run_mt5_export_rates(args) -> int:
    conn = _mt5_conn_from_args(args)
    cfg = _gap_cfg_from_args(args)
    start = parse_date(args.start)
    end = parse_date(args.end)
    _, bars = build_gap_dataset_from_mt5(conn, start, end, cfg)
    save_dataframe(args.output, bars)
    print(f"Barras MT5 salvas em: {args.output}")
    print(f"Linhas: {len(bars)}")
    return 0


def run_mt5_build_gap_csv(args) -> int:
    conn = _mt5_conn_from_args(args)
    cfg = _gap_cfg_from_args(args)
    start = parse_date(args.start)
    end = parse_date(args.end)
    dataset, bars = build_gap_dataset_from_mt5(conn, start, end, cfg)
    save_dataframe(args.output, dataset)
    if args.raw_bars_output:
        save_dataframe(args.raw_bars_output, bars)
    print(f"Dataset real de gaps salvo em: {args.output}")
    print(f"Sessões válidas: {len(dataset)} | barras baixadas: {len(bars)}")
    if len(dataset) < 150:
        print("Aviso: histórico curto para uma validação robusta. Para walk-forward sério, tente pelo menos 300 a 600 sessões.")
    return 0


def run_validate_mt5(args) -> int:
    conn = _mt5_conn_from_args(args)
    gap_cfg = _gap_cfg_from_args(args)
    cfg = config_from_dict(load_yaml_config(args.config))
    start = parse_date(args.start)
    end = parse_date(args.end)
    dataset, bars = build_gap_dataset_from_mt5(conn, start, end, gap_cfg)
    save_dataframe(args.dataset_output, dataset)
    if args.raw_bars_output:
        save_dataframe(args.raw_bars_output, bars)
    report = validate_input_frame(dataset)
    if not report.ok:
        raise ValueError(f"Dataset MT5 inválido/insuficiente: {report}")
    if report.missing_optional:
        print("Aviso: campos cross-market/NOII ficaram ausentes ou vazios. Isso evita vazamento de futuro, mas limita a teoria.")
    predictions, metrics = walk_forward_validate(dataset, cfg)
    save_report(args.output, predictions, metrics, title="Relatório TPGA — Dados Reais MT5")
    if args.predictions:
        save_predictions(args.predictions, predictions)
    print(json.dumps(metrics, indent=2, ensure_ascii=False))
    print(f"Dataset MT5 salvo em: {args.dataset_output}")
    print(f"Relatório salvo em: {args.output}")
    return 0


def run_mt5_live_once(args) -> int:
    conn = _mt5_conn_from_args(args)
    gap_cfg = _gap_cfg_from_args(args)
    cfg = config_from_dict(load_yaml_config(args.config))
    start = parse_date(args.start)
    end = parse_date(args.end)
    dataset, _ = build_gap_dataset_from_mt5(conn, start, end, gap_cfg)
    if len(dataset) < cfg.min_train_size:
        raise ValueError(f"Histórico insuficiente para treinar: {len(dataset)} sessões. Mínimo configurado: {cfg.min_train_size}.")
    with MT5Client(conn) as client:
        recent = client.copy_recent_rates(args.symbol, timeframe=args.timeframe, count=args.recent_bars, tz_name=args.timezone)
    current_row = build_current_feature_row(recent, gap_cfg)
    signal = train_and_score_current(dataset, current_row, gap_cfg, random_state=cfg.random_state)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(signal.__dict__, f, indent=2, ensure_ascii=False)
    print(json.dumps(signal.__dict__, indent=2, ensure_ascii=False))
    print(f"Snapshot salvo em: {args.output}")
    return 0


def _validate_online_history(dataset, cfg):
    report = validate_input_frame(dataset)
    if not report.ok:
        raise ValueError(f"Histórico online MT5 inválido/insuficiente: {report}")
    if len(dataset) < cfg.min_train_size:
        raise ValueError(
            f"Histórico online insuficiente para treinar: {len(dataset)} sessões válidas. "
            f"Mínimo configurado: {cfg.min_train_size}. Aumente --history-bars e confira Max. bars in chart no MT5."
        )
    return report


def run_mt5_online_validate(args) -> int:
    """Walk-forward entirely from live MT5 bars, in memory, no CSV."""
    conn = _mt5_conn_from_args(args)
    gap_cfg = _gap_cfg_from_args(args)
    cfg = apply_runtime_overrides(config_from_dict(load_yaml_config(args.config)), args)
    dataset, bars = build_gap_dataset_online_from_mt5(conn, gap_cfg, history_bars=args.history_bars)
    _validate_online_history(dataset, cfg)
    predictions, metrics = walk_forward_validate(dataset, cfg)
    metrics["source"] = {
        "mode": "mt5_online_in_memory_no_csv",
        "symbol": args.symbol,
        "history_bars_requested": int(args.history_bars),
        "bars_received": int(len(bars)),
        "sessions_valid": int(len(dataset)),
        "history_quality": history_quality_label(len(dataset)),
        "min_train_size_used": int(cfg.min_train_size),
        "first_bar_local": str(bars["time_local"].iloc[0]) if len(bars) else None,
        "last_bar_local": str(bars["time_local"].iloc[-1]) if len(bars) else None,
    }
    if args.output:
        save_report(args.output, predictions, metrics, title="Relatório TPGA — MT5 Online/In-Memory")
        print(f"Relatório salvo em: {args.output}")
    print(json.dumps(metrics, indent=2, ensure_ascii=False))
    return 0


def run_mt5_online_once(args) -> int:
    """One real online probabilistic snapshot from MT5, no CSV."""
    conn = _mt5_conn_from_args(args)
    gap_cfg = _gap_cfg_from_args(args)
    cfg = apply_runtime_overrides(config_from_dict(load_yaml_config(args.config)), args)
    dataset, bars = build_gap_dataset_online_from_mt5(conn, gap_cfg, history_bars=args.history_bars)
    _validate_online_history(dataset, cfg)
    recent = bars.tail(max(args.recent_bars, gap_cfg.lookback_minutes + 60)).copy()
    current_row = build_current_feature_row(recent, gap_cfg)
    signal = train_and_score_current(dataset, current_row, gap_cfg, random_state=cfg.random_state)
    payload = signal.__dict__.copy()
    if len(dataset) < 120:
        payload["side"] = "LOW_HISTORY_" + str(payload.get("side", "STUDY"))
        payload["note"] = (
            payload.get("note", "")
            + " Histórico abaixo de 120 sessões; use apenas para testar execução online, não para decisão operacional."
        ).strip()
    payload["source"] = {
        "mode": "mt5_online_in_memory_no_csv",
        "symbol": args.symbol,
        "history_bars_requested": int(args.history_bars),
        "bars_received": int(len(bars)),
        "sessions_valid": int(len(dataset)),
        "history_quality": history_quality_label(len(dataset)),
        "min_train_size_used": int(cfg.min_train_size),
        "recent_bars_used": int(len(recent)),
        "first_bar_local": str(bars["time_local"].iloc[0]) if len(bars) else None,
        "last_bar_local": str(bars["time_local"].iloc[-1]) if len(bars) else None,
        "last_close": float(recent["close"].iloc[-1]) if len(recent) else None,
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    print(text)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"Snapshot salvo em: {args.output}")
    return 0


def run_mt5_online_loop(args) -> int:
    """Continuous real online reading loop. It does not send orders."""
    if args.interval_seconds < 5:
        raise ValueError("Use --interval-seconds >= 5 para não sobrecarregar o terminal MT5.")
    while True:
        try:
            run_mt5_online_once(args)
        except KeyboardInterrupt:
            print("Loop encerrado pelo usuário.")
            return 0
        except Exception as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        sleep(args.interval_seconds)


def _add_mt5_common_args(p):
    p.add_argument("--symbol", default="NDX100", help="Símbolo exatamente como aparece no Market Watch do MT5: NDX100, NAS100, US100 etc.")
    p.add_argument("--terminal-path", default=None, help="Caminho opcional do terminal64.exe")
    p.add_argument("--login", type=int, default=None, help="Login opcional. Se omitido, usa a conta já logada no terminal.")
    p.add_argument("--password", default=None, help="Senha opcional. Prefira deixar o terminal já logado.")
    p.add_argument("--server", default=None, help="Servidor opcional da corretora.")
    p.add_argument("--timeout-ms", type=int, default=60000)


def _add_gap_session_args(p):
    p.add_argument("--timezone", default="America/Sao_Paulo")
    p.add_argument("--close-time", default="17:59", help="Horário local da barra de fechamento/base do gap, ex.: 17:59")
    p.add_argument("--open-time", default="19:00", help="Horário local da barra de abertura/alvo do gap, ex.: 19:00")
    p.add_argument("--signal-time", default=None, help="Horário local usado para calcular features. Se omitido, usa close-time.")
    p.add_argument("--lookback-minutes", type=int, default=240)
    p.add_argument("--bar-tolerance-minutes", type=int, default=10)
    p.add_argument("--timeframe", default="M1")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TPGA NDX100 — estudo probabilístico de gap de abertura")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate-demo", help="Roda validação com dataset sintético")
    p.add_argument("--rows", type=int, default=420)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--config", default="config/tpga_config.yaml")
    p.add_argument("--output", default="reports/demo_report.md")
    p.add_argument("--predictions", default="reports/demo_predictions.csv")
    p.set_defaults(func=run_validate_demo)

    p = sub.add_parser("make-sample", help="Cria CSV sintético de exemplo")
    p.add_argument("--rows", type=int, default=420)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--output", default="examples/sample_gap_data.csv")
    p.set_defaults(func=run_make_sample)

    p = sub.add_parser("validate-csv", help="Valida CSV real do usuário")
    p.add_argument("--csv", required=True)
    p.add_argument("--config", default="config/tpga_config.yaml")
    p.add_argument("--output", default="reports/csv_report.md")
    p.add_argument("--predictions", default="reports/csv_predictions.csv")
    p.set_defaults(func=run_validate_csv)

    p = sub.add_parser("mt5-check", help="Testa conexão com MetaTrader 5 e símbolo")
    _add_mt5_common_args(p)
    p.set_defaults(func=run_mt5_check)

    p = sub.add_parser("mt5-export-rates", help="Baixa barras reais do MT5 para CSV")
    _add_mt5_common_args(p)
    _add_gap_session_args(p)
    p.add_argument("--start", required=True, help="YYYY-MM-DD")
    p.add_argument("--end", required=True, help="YYYY-MM-DD")
    p.add_argument("--output", default="data/mt5_raw_bars.csv")
    p.set_defaults(func=run_mt5_export_rates)

    p = sub.add_parser("mt5-build-gap-csv", help="Constrói dataset real de gaps a partir de barras M1 do MT5")
    _add_mt5_common_args(p)
    _add_gap_session_args(p)
    p.add_argument("--start", required=True, help="YYYY-MM-DD")
    p.add_argument("--end", required=True, help="YYYY-MM-DD")
    p.add_argument("--output", default="data/mt5_gap_dataset.csv")
    p.add_argument("--raw-bars-output", default=None)
    p.set_defaults(func=run_mt5_build_gap_csv)

    p = sub.add_parser("validate-mt5", help="Baixa dados reais do MT5, monta dataset e roda walk-forward")
    _add_mt5_common_args(p)
    _add_gap_session_args(p)
    p.add_argument("--start", required=True, help="YYYY-MM-DD")
    p.add_argument("--end", required=True, help="YYYY-MM-DD")
    p.add_argument("--config", default="config/tpga_config.yaml")
    p.add_argument("--dataset-output", default="data/mt5_gap_dataset.csv")
    p.add_argument("--raw-bars-output", default=None)
    p.add_argument("--output", default="reports/mt5_report.md")
    p.add_argument("--predictions", default="reports/mt5_predictions.csv")
    p.set_defaults(func=run_validate_mt5)

    p = sub.add_parser("mt5-live-once", help="Gera um snapshot probabilístico educacional com dados reais recentes do MT5; não envia ordens")
    _add_mt5_common_args(p)
    _add_gap_session_args(p)
    p.add_argument("--start", required=True, help="Início do histórico para treino, YYYY-MM-DD")
    p.add_argument("--end", required=True, help="Fim do histórico para treino, YYYY-MM-DD")
    p.add_argument("--config", default="config/tpga_config.yaml")
    p.add_argument("--recent-bars", type=int, default=600)
    p.add_argument("--output", default="reports/mt5_live_once.json")
    p.set_defaults(func=run_mt5_live_once)

    p = sub.add_parser("mt5-online-validate", help="Valida teoria com dados reais online do MT5 em memória; não gera CSV")
    _add_mt5_common_args(p)
    _add_gap_session_args(p)
    p.add_argument("--history-bars", type=int, default=200000, help="Quantidade de barras online puxadas do MT5 via copy_rates_from_pos")
    p.add_argument("--min-train-size", type=int, default=None, help="Override do mínimo de sessões para treino. Use 30 apenas para teste online com pouco histórico; 120+ para validação séria.")
    p.add_argument("--config", default="config/tpga_config.yaml")
    p.add_argument("--output", default="reports/mt5_online_report.md", help="Relatório Markdown. Use vazio para apenas imprimir JSON")
    p.set_defaults(func=run_mt5_online_validate)

    p = sub.add_parser("mt5-online-once", help="Snapshot probabilístico online do MT5 em memória; não usa CSV e não envia ordens")
    _add_mt5_common_args(p)
    _add_gap_session_args(p)
    p.add_argument("--history-bars", type=int, default=200000)
    p.add_argument("--recent-bars", type=int, default=600)
    p.add_argument("--min-train-size", type=int, default=None, help="Override do mínimo de sessões para treino. Use 30 apenas para teste online com pouco histórico; 120+ para validação séria.")
    p.add_argument("--config", default="config/tpga_config.yaml")
    p.add_argument("--output", default=None, help="Opcional: salva JSON do snapshot. Por padrão, só imprime na tela")
    p.set_defaults(func=run_mt5_online_once)

    p = sub.add_parser("mt5-online-loop", help="Loop online lendo MT5 em tempo real; não usa CSV e não envia ordens")
    _add_mt5_common_args(p)
    _add_gap_session_args(p)
    p.add_argument("--history-bars", type=int, default=200000)
    p.add_argument("--recent-bars", type=int, default=600)
    p.add_argument("--interval-seconds", type=int, default=30)
    p.add_argument("--min-train-size", type=int, default=None, help="Override do mínimo de sessões para treino. Use 30 apenas para teste online com pouco histórico; 120+ para validação séria.")
    p.add_argument("--config", default="config/tpga_config.yaml")
    p.add_argument("--output", default=None, help="Opcional: sobrescreve JSON do último snapshot")
    p.set_defaults(func=run_mt5_online_loop)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
