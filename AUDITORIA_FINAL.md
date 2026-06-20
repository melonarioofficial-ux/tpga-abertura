# Auditoria Final — TPGA v13 MT5 Online Sem CSV

## Veredito

A v13 corrige a falha operacional da v12/v11: o terminal MetaTrader 5 conectava corretamente, mas recusava solicitações grandes de candles com `Terminal: Invalid params`.

## Correção aplicada

Arquivo principal alterado:

```text
src/tpga/mt5_client.py
```

Correção:

- `copy_rates_from_pos` agora faz batching seguro.
- Solicitações grandes são divididas em blocos menores.
- Se o terminal recusar um bloco, o tamanho é reduzido automaticamente.
- Os candles são concatenados em memória.
- Duplicidades por timestamp UTC são removidas.
- O robô online continua sem CSV operacional.

## Validação local

```text
PYTHONPATH=src pytest -q
4 passed
```

Demo sintética executada:

```text
python -m tpga.cli validate-demo --rows 180 --output reports/demo_report_v13.md
OK
```

## Limite honesto

A conexão real MT5/Eightcap só pode ser testada na máquina do usuário, porque depende do terminal aberto, conta logada, símbolo visível, histórico disponível e configuração Max bars in chart.


## Atualização v14 — histórico curto no modo online

A v14 adiciona `--min-train-size` aos comandos `mt5-online-once`, `mt5-online-loop` e `mt5-online-validate`.

Use `--min-train-size 30` apenas para testar o robô online quando o MT5 ainda só tiver poucas sessões carregadas. Quando houver menos de 120 sessões, a saída fica marcada como `LOW_HISTORY_*`, indicando que o sinal é somente teste técnico. Para validação séria, use 120+ sessões.
