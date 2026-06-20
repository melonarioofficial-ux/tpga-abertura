# TPGA-NDX100 v13 — Robô Online/In-Memory para Gap de Abertura via MetaTrader 5

Este pacote é um robô de **estudo probabilístico online** para abertura/gap do NDX100/NAS100/US100 usando dados reais lidos diretamente do terminal MetaTrader 5.

A versão v13 corrige o problema visto no MT5/Eightcap em que o terminal conectava corretamente, mas retornava `(-2, 'Terminal: Invalid params')` ao solicitar histórico grande. A correção principal foi implementar leitura online com **batching seguro**: em vez de pedir 200.000 candles de uma vez, o robô divide a solicitação em blocos menores, reduz o bloco automaticamente se o terminal recusar, junta tudo em memória e calcula o sinal sem CSV operacional.

## Status operacional

- Lê dados reais do MT5 online.
- Usa `NDX100` exatamente como aparece no Market Watch.
- Monta histórico de gaps em memória.
- Treina o motor probabilístico em memória.
- Gera `p_up`, `p_down`, `p_flat`, `edge`, `confidence` e direção de estudo.
- Não precisa de CSV para rodar o robô online.
- Não envia ordens reais.

## Instalação na pasta atual

No PowerShell:

```powershell
cd C:\50-Robo_abertura_Python
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
pip install -r requirements-mt5.txt
pip install -e .
```

Não rode `python -m venv .venv` enquanto o ambiente já estiver ativo. Isso causa erro de permissão porque o próprio `python.exe` do venv está em uso.

## Teste de conexão

Deixe o MetaTrader 5 aberto e logado na Eightcap. Depois rode:

```powershell
python -m tpga.cli mt5-check --symbol NDX100
```

Se isso voltar `ok: true`, a conexão está boa.

## Rodar o robô online uma vez

Comece com menos barras para confirmar que tudo roda:

```powershell
python -m tpga.cli mt5-online-once --symbol NDX100 --history-bars 50000 --recent-bars 600 --close-time 17:59 --open-time 19:00 --signal-time 17:49
```

Depois aumente:

```powershell
python -m tpga.cli mt5-online-once --symbol NDX100 --history-bars 200000 --recent-bars 600 --close-time 17:59 --open-time 19:00 --signal-time 17:49
```

## Rodar em loop online

```powershell
python -m tpga.cli mt5-online-loop --symbol NDX100 --history-bars 50000 --recent-bars 600 --interval-seconds 30 --close-time 17:59 --open-time 19:00 --signal-time 17:49
```

Para parar:

```text
CTRL + C
```

## Validação online sem CSV operacional

```powershell
python -m tpga.cli mt5-online-validate --symbol NDX100 --history-bars 50000 --close-time 17:59 --open-time 19:00 --signal-time 17:49 --output reports\mt5_online_report.md
```

Essa validação usa barras online do MT5 em memória. O relatório Markdown é apenas saída de relatório, não dataset operacional.

## Interpretação da saída

- `p_up`: probabilidade estimada de gap de alta.
- `p_down`: probabilidade estimada de gap de baixa.
- `p_flat`: probabilidade estimada de gap lateral/pequeno.
- `edge`: `p_up - p_down`.
- `confidence`: maior probabilidade entre alta, baixa e lateral.
- `side`: direção de estudo. Não é ordem real.
- `sessions_valid`: sessões históricas de gap montadas em memória.
- `bars_received`: candles reais recebidos do MT5.

## Observação importante

Este projeto é educacional/paper. Ele não promete lucro, não é recomendação financeira e não envia ordens. Para operar real, ainda seria necessário um módulo separado de execução com gestão de risco, trava de spread, stop, take, limite diário, horário e confirmação explícita.


## Atualização v14 — histórico curto no modo online

A v14 adiciona `--min-train-size` aos comandos `mt5-online-once`, `mt5-online-loop` e `mt5-online-validate`.

Use `--min-train-size 30` apenas para testar o robô online quando o MT5 ainda só tiver poucas sessões carregadas. Quando houver menos de 120 sessões, a saída fica marcada como `LOW_HISTORY_*`, indicando que o sinal é somente teste técnico. Para validação séria, use 120+ sessões.
