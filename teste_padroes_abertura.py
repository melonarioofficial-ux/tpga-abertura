"""
TESTE HONESTO DE PADRÕES DE ABERTURA DE MERCADO
=================================================
O que este script faz:
  1. Baixa dados históricos reais de até 100 ativos (S&P 500 por padrão)
  2. Testa algumas hipóteses ESPECÍFICAS e ECONOMICAMENTE PLAUSÍVEIS sobre
     o comportamento da abertura do mercado (não "minera tudo que existe")
  3. Separa os dados em TREINO (descoberta) e TESTE (confirmação) ANTES de
     olhar qualquer resultado — a parte de TESTE só é usada UMA VEZ, no final
  4. Aplica correção estatística para múltiplas comparações (Bonferroni)
  5. Inclui custos de transação realistas
  6. Reporta o resultado HONESTO: a maioria das hipóteses provavelmente
     vai morrer no teste fora da amostra. Isso é o esperado, não um bug.

Requisitos:
  pip install yfinance pandas numpy scipy

Como rodar:
  python teste_padroes_abertura.py

Tempo estimado: 5-15 minutos para 100 ativos (depende da sua internet)
"""

import yfinance as yf
import pandas as pd
import numpy as np
from scipy import stats
import warnings
import time
warnings.filterwarnings("ignore")

# =====================================================================
# CONFIGURAÇÃO
# =====================================================================

# Lista de ativos: top ~100 do S&P 500 por peso (lista fixa, não dinâmica,
# para evitar survivorship bias na escolha - são os atuais, mas o ideal
# em um estudo sério seria usar a composição histórica do índice)
TICKERS_SP100 = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "AMZN", "META", "BRK-B", "AVGO",
    "TSLA", "LLY", "JPM", "V", "XOM", "UNH", "MA", "COST", "HD", "PG",
    "JNJ", "NFLX", "ABBV", "BAC", "CRM", "WMT", "KO", "MRK", "CVX", "AMD",
    "PEP", "TMO", "ADBE", "LIN", "ACN", "MCD", "CSCO", "ABT", "WFC", "DIS",
    "GE", "DHR", "TXN", "VZ", "PM", "INTU", "AMGN", "IBM", "CAT", "NOW",
    "QCOM", "AXP", "SPGI", "ISRG", "NEE", "PFE", "RTX", "UNP", "LOW",
    "HON", "AMAT", "BKNG", "T", "GS", "BLK", "SYK", "ELV", "C", "DE",
    "VRTX", "MS", "SCHW", "TJX", "MDT", "LRCX", "PGR", "ADP", "BSX",
    "PLD", "MU", "GILD", "REGN", "ADI", "ETN", "CB", "MMC", "SBUX",
    "LMT", "FI", "BX", "UBER", "INTC", "PANW", "KLAC", "SO", "ZTS",
    "DUK", "BDX", "EOG", "CME", "MO"
]

PERIODO_ANOS_TOTAL = 6          # quanto histórico baixar
SPLIT_TREINO_TESTE = 0.65       # 65% treino (descoberta), 35% teste (confirmação) - últimos dados
CUSTO_TRANSACAO_BPS = 5         # 5 basis points por lado (compra+venda = 10bps), realista p/ ativo líquido
NIVEL_SIGNIFICANCIA = 0.05      # alfa antes da correção


# =====================================================================
# DOWNLOAD DOS DADOS
# =====================================================================

def baixar_dados(tickers, anos=PERIODO_ANOS_TOTAL):
    print(f"Baixando dados de {len(tickers)} ativos ({anos} anos de histórico)...")
    dados = {}
    falhas = []
    for i, t in enumerate(tickers):
        try:
            df = yf.download(t, period=f"{anos}y", progress=False, auto_adjust=False)
            if df.empty or len(df) < 500:
                falhas.append(t)
                continue
            # achatando MultiIndex de colunas se existir
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0] for c in df.columns]
            dados[t] = df
        except Exception as e:
            falhas.append(t)
        if (i + 1) % 20 == 0:
            print(f"  {i+1}/{len(tickers)} processados...")
        time.sleep(0.1)  # gentileza com a API gratuita
    print(f"\nSucesso: {len(dados)} ativos | Falhas: {len(falhas)}")
    if falhas:
        print(f"Ativos que falharam (ignorados): {falhas}")
    return dados


# =====================================================================
# DEFINIÇÃO DAS HIPÓTESES (poucas, específicas, com lógica econômica)
# =====================================================================
# Cada hipótese testa uma ideia plausível sobre comportamento de abertura.
# Propositalmente são POUCAS hipóteses - testar centenas é o que causa
# o problema de múltiplas comparações que discutimos.

def hipotese_1_reversao_gap(df):
    """
    H1: REVERSÃO DE GAP — se o ativo abre com gap (diferença entre
    abertura de hoje e fechamento de ontem) muito grande, ele tende a
    reverter parte do gap durante o dia (fechar mais perto do fechamento
    anterior do que abriu).
    Lógica econômica: gaps grandes geralmente refletem reação
    excessiva a notícia overnight com pouca liquidez; mean reversion
    intraday é um efeito de microestrutura documentado.
    Sinal: se gap > limiar, aposta contra o gap (fade).
    """
    close_ant = df['Close'].shift(1)
    gap = (df['Open'] - close_ant) / close_ant
    ret_intraday = (df['Close'] - df['Open']) / df['Open']  # retorno do dia (abertura->fechamento)

    limiar = gap.rolling(60).std() * 1.5  # gap "grande" = 1.5x o desvio padrão móvel
    sinal = pd.Series(0.0, index=df.index)
    sinal[gap > limiar] = -1   # gap pra cima grande -> aposta que cai (fade)
    sinal[gap < -limiar] = 1   # gap pra baixo grande -> aposta que sobe (fade)

    retorno_estrategia = sinal.shift(0) * ret_intraday  # decisão na abertura, resultado no fechamento do mesmo dia
    n_trades = (sinal != 0).sum()
    return retorno_estrategia, n_trades


def hipotese_2_continuacao_gap_com_volume(df):
    """
    H2: CONTINUAÇÃO DE GAP COM VOLUME — se o ativo abre com gap E volume
    acima da média, o gap tende a CONTINUAR (não reverter), porque
    volume alto sugere informação real (não ruído de liquidez).
    Lógica econômica: oposto da H1, mas condicionado a volume -
    gap + alto volume = informação genuína sendo precificada.
    """
    close_ant = df['Close'].shift(1)
    gap = (df['Open'] - close_ant) / close_ant
    ret_intraday = (df['Close'] - df['Open']) / df['Open']

    vol_medio = df['Volume'].rolling(20).mean()
    volume_alto = df['Volume'] > (vol_medio * 1.3)

    limiar = gap.rolling(60).std() * 1.0
    sinal = pd.Series(0.0, index=df.index)
    cond_alta = (gap > limiar) & volume_alto
    cond_baixa = (gap < -limiar) & volume_alto
    sinal[cond_alta] = 1     # gap pra cima + volume -> aposta que continua subindo
    sinal[cond_baixa] = -1   # gap pra baixo + volume -> aposta que continua caindo

    retorno_estrategia = sinal * ret_intraday
    n_trades = (sinal != 0).sum()
    return retorno_estrategia, n_trades


def hipotese_3_primeira_meia_hora_prediz_dia(df):
    """
    H3: Como não tenho dados intraday gratuitos confiáveis de 100 ativos,
    esta é uma proxy: testa se o retorno overnight (fechamento ontem ->
    abertura hoje) prediz o retorno do resto do dia (abertura -> fechamento).
    Lógica econômica: informação overnight (notícias, mercados asiáticos/
    europeus) pode ainda não estar totalmente precificada na abertura.
    """
    close_ant = df['Close'].shift(1)
    ret_overnight = (df['Open'] - close_ant) / close_ant
    ret_dia = (df['Close'] - df['Open']) / df['Open']

    sinal = np.sign(ret_overnight)  # segue a direção do movimento overnight
    retorno_estrategia = sinal * ret_dia
    n_trades = (sinal != 0).sum()
    return retorno_estrategia, n_trades


HIPOTESES = {
    "H1_reversao_gap": hipotese_1_reversao_gap,
    "H2_continuacao_gap_volume": hipotese_2_continuacao_gap_com_volume,
    "H3_overnight_prediz_dia": hipotese_3_primeira_meia_hora_prediz_dia,
}


# =====================================================================
# MÉTRICAS E VALIDAÇÃO ESTATÍSTICA
# =====================================================================

def calcular_sharpe(retornos, custo_bps_por_trade=0, n_trades=None, n_dias_total=None):
    """Sharpe anualizado, líquido de custos de transação."""
    retornos = retornos.dropna()
    if len(retornos) < 30 or retornos.std() == 0:
        return np.nan, np.nan

    retornos_liquidos = retornos.copy()
    if n_trades and custo_bps_por_trade > 0:
        custo_total_frac = (n_trades * 2 * custo_bps_por_trade) / 10000  # 2x = entrada+saída
        custo_por_trade = custo_total_frac / max(n_trades, 1)
        retornos_liquidos[retornos != 0] -= custo_por_trade

    sharpe_bruto = retornos.mean() / retornos.std() * np.sqrt(252)
    sharpe_liquido = retornos_liquidos.mean() / retornos_liquidos.std() * np.sqrt(252) if retornos_liquidos.std() > 0 else np.nan
    return sharpe_bruto, sharpe_liquido


def teste_t_retorno_zero(retornos):
    """Testa H0: retorno médio = 0. Retorna p-valor."""
    retornos = retornos.dropna()
    retornos_nao_zero = retornos[retornos != 0]
    if len(retornos_nao_zero) < 30:
        return np.nan
    t_stat, p_valor = stats.ttest_1samp(retornos_nao_zero, 0)
    return p_valor


# =====================================================================
# EXECUÇÃO PRINCIPAL
# =====================================================================

def main():
    dados = baixar_dados(TICKERS_SP100)

    if len(dados) == 0:
        print("ERRO: nenhum dado foi baixado. Verifique sua conexão.")
        return

    resultados_treino = []
    resultados_teste = []

    print(f"\n{'='*80}")
    print(f"Testando {len(HIPOTESES)} hipóteses em {len(dados)} ativos")
    print(f"Split: {SPLIT_TREINO_TESTE*100:.0f}% treino (descoberta) / "
          f"{(1-SPLIT_TREINO_TESTE)*100:.0f}% teste (confirmação, só usado 1x no final)")
    print(f"{'='*80}\n")

    for ticker, df in dados.items():
        n = len(df)
        corte = int(n * SPLIT_TREINO_TESTE)
        df_treino = df.iloc[:corte].copy()
        df_teste = df.iloc[corte:].copy()

        for nome_h, func_h in HIPOTESES.items():
            # ---- TREINO (fase de descoberta) ----
            try:
                ret_treino, n_trades_treino = func_h(df_treino)
                sharpe_bruto_tr, sharpe_liq_tr = calcular_sharpe(
                    ret_treino, CUSTO_TRANSACAO_BPS, n_trades_treino
                )
                p_valor_tr = teste_t_retorno_zero(ret_treino)
                resultados_treino.append({
                    "ticker": ticker, "hipotese": nome_h,
                    "sharpe_bruto": sharpe_bruto_tr, "sharpe_liquido": sharpe_liq_tr,
                    "n_trades": n_trades_treino, "p_valor": p_valor_tr
                })
            except Exception:
                continue

            # ---- TESTE (fase de confirmação, fora da amostra) ----
            try:
                ret_teste, n_trades_teste = func_h(df_teste)
                sharpe_bruto_te, sharpe_liq_te = calcular_sharpe(
                    ret_teste, CUSTO_TRANSACAO_BPS, n_trades_teste
                )
                p_valor_te = teste_t_retorno_zero(ret_teste)
                resultados_teste.append({
                    "ticker": ticker, "hipotese": nome_h,
                    "sharpe_bruto": sharpe_bruto_te, "sharpe_liquido": sharpe_liq_te,
                    "n_trades": n_trades_teste, "p_valor": p_valor_te
                })
            except Exception:
                continue

    df_treino_res = pd.DataFrame(resultados_treino).dropna()
    df_teste_res = pd.DataFrame(resultados_teste).dropna()

    # =================================================================
    # RELATÓRIO HONESTO
    # =================================================================
    n_testes_totais = len(df_treino_res)
    bonferroni_alfa = NIVEL_SIGNIFICANCIA / max(n_testes_totais, 1)

    print(f"\n{'='*80}")
    print("RESULTADOS — FASE DE TREINO (descoberta)")
    print(f"{'='*80}")
    print(f"Total de combinações ativo x hipótese testadas: {n_testes_totais}")
    print(f"Nível de significância original (alfa): {NIVEL_SIGNIFICANCIA}")
    print(f"Alfa corrigido por Bonferroni (mais rigoroso, correto): {bonferroni_alfa:.6f}")

    print(f"\nResumo por hipótese (média de Sharpe líquido entre todos os ativos):")
    resumo_treino = df_treino_res.groupby("hipotese")["sharpe_liquido"].agg(["mean", "std", "count"])
    print(resumo_treino.to_string())

    # Quantos resultados seriam "significativos" SEM correção
    sig_sem_correcao = (df_treino_res["p_valor"] < NIVEL_SIGNIFICANCIA).sum()
    sig_com_correcao = (df_treino_res["p_valor"] < bonferroni_alfa).sum()
    print(f"\n'Achados significativos' SEM correção estatística: {sig_sem_correcao} de {n_testes_totais}")
    print(f"'Achados significativos' COM correção de Bonferroni:  {sig_com_correcao} de {n_testes_totais}")
    print("(A diferença entre esses dois números é exatamente o tamanho do autoengano")
    print(" que aconteceria se você não corrigisse estatisticamente.)")

    # =================================================================
    # A PARTE QUE REALMENTE IMPORTA: sobrevive no teste fora da amostra?
    # =================================================================
    print(f"\n{'='*80}")
    print("VALIDAÇÃO FINAL — sobrevive nos dados de TESTE (nunca vistos antes)?")
    print(f"{'='*80}")

    # pega as combinações que pareciam boas no treino (top 10% por sharpe líquido)
    limiar_top = df_treino_res["sharpe_liquido"].quantile(0.9)
    candidatos = df_treino_res[df_treino_res["sharpe_liquido"] >= limiar_top]

    print(f"\nCandidatos 'promissores' no treino (top 10%): {len(candidatos)}")
    print(f"Sharpe líquido médio desses candidatos NO TREINO: {candidatos['sharpe_liquido'].mean():.2f}")

    # cruza com o resultado real no teste
    merge = candidatos.merge(
        df_teste_res, on=["ticker", "hipotese"], suffixes=("_treino", "_teste")
    )
    if len(merge) > 0:
        print(f"\nMesmos candidatos, resultado real NO TESTE (dados nunca vistos):")
        print(f"Sharpe líquido médio NO TESTE: {merge['sharpe_liquido_teste'].mean():.2f}")
        sobreviventes = merge[merge["sharpe_liquido_teste"] > 0.3]  # barra mínima razoável
        print(f"\nQuantos candidatos 'sobreviveram' (Sharpe líquido > 0.3 no teste): "
              f"{len(sobreviventes)} de {len(merge)}")
        if len(sobreviventes) > 0:
            print("\nOs que sobreviveram:")
            print(sobreviventes[["ticker", "hipotese", "sharpe_liquido_treino", "sharpe_liquido_teste"]]
                  .sort_values("sharpe_liquido_teste", ascending=False).to_string(index=False))
        else:
            print("\n>>> NENHUM candidato sobreviveu. Isso é uma resposta válida e esperada.")
            print(">>> Significa que o que parecia bom no treino era, com alta probabilidade,")
            print(">>> ruído estatístico (exatamente o fenômeno que simulamos antes).")
    else:
        print("Não houve interseção suficiente para validar.")

    # salva tudo em CSV para você poder auditar manualmente
    df_treino_res.to_csv("resultados_treino.csv", index=False)
    df_teste_res.to_csv("resultados_teste.csv", index=False)
    print(f"\n\nArquivos salvos: resultados_treino.csv, resultados_teste.csv")
    print("Abra esses CSVs e confira os números você mesmo — não confie só no print.")


if __name__ == "__main__":
    main()
