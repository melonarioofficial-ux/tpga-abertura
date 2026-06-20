# Guia MT5 Real Data — TPGA NDX100 v11

## Objetivo

A v11 conecta ao MetaTrader 5 para puxar dados reais do símbolo da sua corretora e construir o dataset de gap automaticamente.

## Fluxo correto

```text
MT5 aberto e logado
→ mt5-check
→ mt5-export-rates
→ mt5-build-gap-csv
→ validate-mt5
→ mt5-live-once em modo paper
```

## Comando mais importante

```powershell
python -m tpga.cli validate-mt5 --symbol NDX100 --start 2025-01-01 --end 2026-06-18 --close-time 17:59 --open-time 19:00 --dataset-output data\mt5_gap_dataset.csv --output reports\mt5_report.md --predictions reports\mt5_predictions.csv
```

## Símbolo correto

Cada corretora usa um nome diferente. Exemplos comuns:

```text
NDX100
NAS100
US100
USTEC
NAS100.cash
US100.cash
```

Use exatamente o nome que aparece no Market Watch do MT5.

## Horários

A configuração padrão deste pacote usa Brasil/São Paulo:

```text
timezone: America/Sao_Paulo
close-time: 17:59
open-time: 19:00
```

Se sua corretora tiver outro horário de pausa/reabertura, ajuste os parâmetros. O motor mede o gap como:

```text
gap_points = open_price_at_open_time - close_price_at_close_time
```

## Entrada antes do fechamento

Se o robô precisa estudar sinal às 17:49, rode:

```powershell
python -m tpga.cli validate-mt5 --symbol NDX100 --start 2025-01-01 --end 2026-06-18 --close-time 17:59 --open-time 19:00 --signal-time 17:49 --dataset-output data\mt5_gap_dataset_signal_1749.csv --output reports\mt5_report_signal_1749.md
```

Nesse modo, as features são calculadas até 17:49, evitando vazamento de informação posterior ao momento em que o sinal seria tomado.

## Arquivos gerados

```text
data/mt5_raw_bars.csv       candles reais M1 do MT5
data/mt5_gap_dataset.csv    dataset histórico de gaps
reports/mt5_report.md       relatório estatístico
reports/mt5_predictions.csv predições walk-forward
reports/mt5_live_once.json  snapshot paper atual
```

## O que é prova real

O relatório só fica forte se mostrar, fora da amostra:

```text
Brier Score melhor que baseline
Log Loss melhor que baseline
MCC positivo
EV líquido positivo depois de custo
Drawdown controlado
Resultado estável em vários folds
```

Se não vencer baselines, a teoria deve ser ajustada. O objetivo da v11 é justamente impedir autoengano.
