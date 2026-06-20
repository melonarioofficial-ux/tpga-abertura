# TPGA v10.0 — Teoria Probabilística de Gap de Abertura do NDX-100

## 1. Tese central

A abertura do mercado não deve ser tratada como um candle comum. Ela é um evento de formação de preço em que informação acumulada fora do pregão, ordens de abertura, futuros, pré-market dos componentes do índice, risco macro e microestrutura final do dia anterior são comprimidos em um preço inicial.

A variável central da teoria é:

```text
G_t = log(Open_t / Close_{t-1})
```

O objetivo correto não é prever apenas `BUY` ou `SELL`, mas estimar a distribuição condicional:

```text
P(G_t | F_t)
```

E dela extrair:

```text
P_up   = P(G_t > +theta | F_t)
P_down = P(G_t < -theta | F_t)
P_flat = P(|G_t| <= theta | F_t)
E_gap  = E[G_t | F_t]
TailRisk = P(|G_t| > stress_level | F_t)
```

Onde `F_t` é o conjunto de informações disponíveis antes da abertura.

---

## 2. Por que esta é uma teoria forte

Ela não se baseia em indicador isolado. A TPGA combina cinco fontes de formação de preço:

1. **Leilão/cross de abertura**: abertura oficial é uma descoberta de preço por cruzamento de ordens.
2. **Futuros NQ quase 24h**: futuros carregam preço justo antes da abertura regular.
3. **Composição ponderada do Nasdaq-100**: poucas big techs podem deslocar o índice.
4. **Microestrutura do fechamento anterior**: fechamento pode conter pressão real, hedge, rebalanceamento ou armadilha de liquidez.
5. **Regime e notícia**: CPI, FOMC, payroll, earnings e choques mudam a distribuição.

A equação-mãe da TPGA é:

```text
P(G_t | F_t) = sum_s P(S_t=s | F_t) * P(G_t | F_t, S_t=s)
```

Onde `S_t` é o regime oculto do mercado.

---

## 3. Modelo estrutural

```text
G_t = alpha_s
    + beta_s' X_close_t
    + gamma_s' X_fairvalue_t
    + delta_s' X_components_t
    + eta_s' X_auction_t
    + kappa_s' X_macro_t
    + epsilon_t
```

### Grupos de features

### 3.1 Fechamento anterior

```text
last_1m_ret
last_5m_ret
last_15m_ret
close_volume_z
vwap_distance
range_position
realized_vol_30m
closing_pressure_score
```

### 3.2 Fair value e overnight

```text
futures_overnight_ret
qqq_premarket_ret
spy_premarket_ret
nq_vs_prev_close_distance
```

### 3.3 Componentes ponderados

```text
weighted_bigtech_premarket_ret = sum_i w_i * premkt_ret_i
```

### 3.4 Auction/NOII

```text
noii_imbalance_side
noii_imbalance_shares
noii_paired_shares
noii_near_price
noii_far_price
noii_reference_price
```

### 3.5 Macro/risco

```text
vix_ret
dxy_ret
us10y_ret
macro_event_flag
earnings_risk_flag
```

---

## 4. Anti-fakeout: o erro clássico do robô antigo

O erro mais perigoso é confundir venda no fechamento com probabilidade de gap de baixa.

```text
queda_final != gap_down_garantido
```

A queda final pode ser:

- realização de lucro;
- rebalanceamento;
- varrida de liquidez;
- hedge temporário;
- absorção compradora;
- ajuste técnico antes de fair value positivo.

A TPGA cria uma variável própria:

```text
FakeoutRisk = f(
  queda_final,
  volume_anormal,
  pavio/rejeição,
  distância do VWAP,
  divergência contra futuros,
  bigtech positiva,
  VIX não confirmando medo
)
```

Regra da teoria:

```text
Se fechamento parece sell, mas fair value/BigTech/NOII não confirma, reduzir ou bloquear sinal.
```

---

## 5. Decisão probabilística

A saída final deve ser:

```text
P_up
P_down
P_flat
E_gap_points
Edge = P_up - P_down
Confidence = max(P_up, P_down, P_flat)
FakeoutRisk
TradeAllowed
```

A decisão só existe se:

```text
abs(Edge) >= edge_threshold
Confidence >= confidence_threshold
FakeoutRisk <= fakeout_threshold
ExpectedGapPoints > cost_points
```

Isso impede que o robô opere quando a probabilidade é fraca ou quando o sinal de fechamento é contraditório.

---

## 6. Como provar a teoria

A teoria só pode ser considerada operacionalmente forte se vencer baselines:

1. Baseline majoritário: sempre prever o lado mais frequente.
2. Baseline futuros: prever pelo sinal do NQ overnight.
3. Baseline fechamento: prever pelo último movimento do fechamento.
4. Baseline logística simples.
5. Baseline sem operação.

Métricas mínimas:

```text
Brier Score menor que baseline
Log Loss menor que baseline
AUC acima de 0.5
MCC positivo
Hit-rate estável por regime
Expected value líquido positivo
Drawdown controlado
Calibração probabilística coerente
```

Validação correta:

```text
walk-forward temporal
sem embaralhar datas
custos e spread incluídos
split por regime
split por evento macro
bootstrap de incerteza
análise dos erros grandes
```

---

## 7. Veredicto técnico

Esta é a melhor formulação de estudo porque ela modela a abertura como **distribuição condicional de clearing/fair value**, e não como tendência comum. O ponto mais forte é a decomposição:

```text
gap = leilão + fair value + componentes + microestrutura + regime + notícia + ruído de cauda
```

A teoria é matematicamente defensável. A prova operacional depende dos dados reais.

## Fontes conceituais usadas na formulação

- NasdaqTrader — Opening and Closing Crosses.
- NasdaqTrader — Fact Sheet do Opening/Closing Cross.
- CME Group — E-mini Nasdaq-100 futures.
- Challet & Gourianov — Dynamical regularities of US equities opening and closing auctions.
- Derksen, Kleijn & de Vilder — Clearing price distributions in call auctions.

