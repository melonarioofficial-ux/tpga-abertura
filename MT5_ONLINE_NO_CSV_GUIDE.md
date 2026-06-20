# Guia MT5 Online Sem CSV — TPGA v13

## O que foi corrigido na v13

Seu MT5 conectava com sucesso no `NDX100`, mas a leitura de histórico falhava com:

```text
MT5 copy_rates_from_pos retornou None: (-2, 'Terminal: Invalid params')
```

A causa mais provável é o terminal/broker recusando uma chamada grande demais, por exemplo `count=200000` de uma vez. A v13 corrige isso com leitura em blocos menores:

```text
MT5 online → blocos pequenos → concatenação em memória → dataset de gaps em memória → sinal probabilístico
```

Não é necessário CSV para rodar o robô online.

## Comando recomendado inicial

```powershell
python -m tpga.cli mt5-online-once --symbol NDX100 --history-bars 50000 --recent-bars 600 --close-time 17:59 --open-time 19:00 --signal-time 17:49
```

Se funcionar e quiser mais histórico:

```powershell
python -m tpga.cli mt5-online-once --symbol NDX100 --history-bars 200000 --recent-bars 600 --close-time 17:59 --open-time 19:00 --signal-time 17:49
```

## Loop online

```powershell
python -m tpga.cli mt5-online-loop --symbol NDX100 --history-bars 50000 --recent-bars 600 --interval-seconds 30 --close-time 17:59 --open-time 19:00 --signal-time 17:49
```

## Se ainda faltar histórico

No MetaTrader 5:

```text
Tools > Options > Charts > Max bars in chart
```

Aumente bastante o valor. Depois abra um gráfico M1 do `NDX100` e pressione Home algumas vezes para o terminal carregar histórico.

## Não use terminal-path por enquanto

Seu terminal conectou automaticamente. Então prefira:

```powershell
python -m tpga.cli mt5-check --symbol NDX100
```

Em vez de passar `--terminal-path`, porque o caminho informado anteriormente não existia ou não era o terminal correto da Eightcap.


## Atualização v14 — histórico curto no modo online

A v14 adiciona `--min-train-size` aos comandos `mt5-online-once`, `mt5-online-loop` e `mt5-online-validate`.

Use `--min-train-size 30` apenas para testar o robô online quando o MT5 ainda só tiver poucas sessões carregadas. Quando houver menos de 120 sessões, a saída fica marcada como `LOW_HISTORY_*`, indicando que o sinal é somente teste técnico. Para validação séria, use 120+ sessões.
