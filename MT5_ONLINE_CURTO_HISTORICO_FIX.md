# TPGA v14 — Correção para histórico curto no MT5 online

## O que significa o erro

Se aparecer:

```text
Histórico online insuficiente para treinar: 33 sessões válidas. Mínimo configurado: 120.
```

isso significa que o MetaTrader 5 conectou, o símbolo funcionou e os candles reais foram puxados, mas o terminal só entregou sessões completas suficientes para montar 33 gaps válidos entre `close-time` e `open-time`.

## Por que `recent-bars` não resolve

`--recent-bars` controla apenas quantos candles recentes entram no snapshot atual.

O histórico de treino vem de:

```powershell
--history-bars
```

## Modo teste com pouco histórico

Para testar o robô online agora, use:

```powershell
python -m tpga.cli mt5-online-once --symbol NDX100 --history-bars 50000 --recent-bars 1600 --close-time 17:59 --open-time 19:00 --signal-time 17:49 --min-train-size 30
```

Em loop:

```powershell
python -m tpga.cli mt5-online-loop --symbol NDX100 --history-bars 50000 --recent-bars 1600 --interval-seconds 30 --close-time 17:59 --open-time 19:00 --signal-time 17:49 --min-train-size 30
```

A saída ficará marcada como `LOW_HISTORY_*` quando houver menos de 120 sessões. Isso é intencional: serve para testar execução online, não para validação séria.

## Modo sério

Para validação estatística, mantenha mínimo 120+ sessões:

```powershell
python -m tpga.cli mt5-online-validate --symbol NDX100 --history-bars 200000 --close-time 17:59 --open-time 19:00 --signal-time 17:49 --min-train-size 120 --output reports\mt5_online_report.md
```

## Aumentar histórico no MT5

No MetaTrader 5:

1. Abra o gráfico do `NDX100` em M1.
2. Role o gráfico para trás para forçar carregamento.
3. Vá em `Tools > Options > Charts`.
4. Aumente `Max bars in chart`.
5. Reinicie o MT5 se necessário.
6. Rode novamente com `--history-bars 200000` ou `--history-bars 500000`.

