# Protocolo de validação estatística TPGA

## Objetivo

Validar se o conjunto de features TPGA melhora a previsão probabilística do gap de abertura em relação a baselines simples.

## Hipótese nula

```text
H0: As features TPGA não adicionam informação.
```

## Hipótese alternativa

```text
H1: As features TPGA reduzem erro probabilístico e/ou aumentam valor esperado líquido fora da amostra.
```

## Dados mínimos

```text
session_date, prev_close, open
```

## Dados recomendados

```text
OHLCV final do dia anterior
NQ/US100 overnight
QQQ pré-market
pré-market ponderado das big techs
VIX, DXY, US10Y
calendário macro
dados NOII/auction quando disponíveis
spread/custo realista
```

## Walk-forward

Não usar train/test aleatório. Série temporal deve ser testada em blocos:

```text
Treina em janela passada -> testa em janela futura -> avança.
```

## Métricas

### Probabilísticas

- Brier Score
- Log Loss
- calibração por bins

### Direcionais

- hit-rate
- MCC
- AUC
- matriz de confusão

### Operacionais simuladas

- trades filtrados por edge
- EV por trade
- lucro/prejuízo em pontos
- drawdown máximo
- profit factor

## Critérios para chamar o modelo de forte

```text
1. Brier e LogLoss melhores que baseline.
2. MCC positivo fora da amostra.
3. EV líquido positivo após custo.
4. Drawdown não concentrado em poucos eventos.
5. Edge não vem de vazamento de dados.
6. Resultado sobrevive a bootstrap e por regime.
```

## Critérios de reprovação

```text
1. Modelo só ganha em treino.
2. Resultado some ao incluir custo/spread.
3. Acurácia alta, mas Brier ruim.
4. Edge concentrado em poucos dias.
5. Modelo compra/vende sempre no mesmo lado.
6. Features de abertura foram coletadas depois do horário de decisão.
```

