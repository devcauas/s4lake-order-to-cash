#!/usr/bin/env python3
"""
Gerador de dados sintéticos SAP (SD + FI-AR) para o caso Order-to-Cash.

Empresa fictícia: Horizonte Embalagens S.A. (indústria B2B de embalagens).

Tabelas geradas, com nomes e campos do modelo de dados SAP ECC / S/4HANA:
    KNA1  - Mestre de clientes (dados gerais)
    KNB1  - Mestre de clientes (dados da empresa: condição de pagamento)
    VBAK  - Ordem de venda (cabeçalho)
    VBAP  - Ordem de venda (itens)
    VBRK  - Documento de faturamento (cabeçalho)
    VBRP  - Documento de faturamento (itens)
    BSID  - Contas a receber: partidas em aberto
    BSAD  - Contas a receber: partidas compensadas (pagas)

Convenções SAP mantidas de propósito, para que a camada Silver tenha trabalho real:
    - Datas no formato YYYYMMDD como texto ('00000000' = data vazia)
    - Chaves com zeros à esquerda (KUNNR com 10 dígitos, MATNR com 18)
    - Mandante (MANDT) presente em todas as tabelas

Por padrão, o gerador injeta problemas de qualidade de dados (duplicidades,
CNPJ vazio, quantidade zerada, referências órfãs). Use --limpo para desativar.

Uso:
    python generate_sap_o2c.py --saida ../data/raw
    python generate_sap_o2c.py --clientes 1500 --formato parquet --seed 7
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Parâmetros organizacionais (estrutura SAP da empresa fictícia)
# ---------------------------------------------------------------------------
MANDT = "100"   # mandante
BUKRS = "1000"  # empresa
VKORG = "1000"  # organização de vendas
VTWEG = "10"    # canal de distribuição (venda direta)
SPART = "00"    # setor de atividade
WAERS = "BRL"
ALIQUOTA_IMPOSTO = 0.18  # simplificação: um único imposto sobre o valor líquido

# Condições de pagamento (ZTERM -> dias)
CONDICOES_PAGAMENTO = {"D028": 28, "D030": 30, "D045": 45, "D060": 60, "D090": 90}

# UF -> (cidades, peso na base de clientes, efeito regional no atraso em dias)
REGIOES = {
    "SP": (["São Paulo", "Campinas", "São José dos Campos", "Ribeirão Preto", "Sorocaba", "Santos"], 0.34, 0.0),
    "MG": (["Belo Horizonte", "Uberlândia", "Contagem", "Juiz de Fora"], 0.12, 1.0),
    "RJ": (["Rio de Janeiro", "Niterói", "Duque de Caxias", "Petrópolis"], 0.10, 2.0),
    "PR": (["Curitiba", "Londrina", "Maringá", "Ponta Grossa"], 0.09, 0.0),
    "SC": (["Joinville", "Blumenau", "Florianópolis", "Chapecó"], 0.07, -0.5),
    "RS": (["Porto Alegre", "Caxias do Sul", "Novo Hamburgo", "Pelotas"], 0.08, 0.5),
    "GO": (["Goiânia", "Anápolis", "Aparecida de Goiânia"], 0.05, 1.5),
    "BA": (["Salvador", "Feira de Santana", "Camaçari"], 0.06, 3.0),
    "PE": (["Recife", "Jaboatão dos Guararapes", "Caruaru"], 0.05, 3.0),
    "CE": (["Fortaleza", "Maracanaú", "Juazeiro do Norte"], 0.04, 3.5),
}

# Ramo de atividade (BRSCH) -> (peso, efeito no atraso em dias)
RAMOS = {
    "ALIM": (0.30, 0.0),   # alimentos e bebidas
    "VARE": (0.22, 2.0),   # varejo
    "ECOM": (0.18, 3.0),   # e-commerce
    "COSM": (0.12, 0.5),   # cosméticos
    "FARM": (0.10, -1.0),  # farmacêutico
    "AUTO": (0.08, 1.0),   # autopeças
}

# Catálogo de materiais: (código, descrição, unidade, preço base R$, faixa de quantidade)
MATERIAIS = [
    ("EMB-CX-P01", "Caixa papelão ondulado P", "UN", 1.85, (500, 5000)),
    ("EMB-CX-M01", "Caixa papelão ondulado M", "UN", 3.10, (300, 4000)),
    ("EMB-CX-G01", "Caixa papelão ondulado G", "UN", 5.40, (200, 3000)),
    ("EMB-CX-E01", "Caixa e-commerce personalizada", "UN", 2.95, (1000, 10000)),
    ("EMB-FS-500", "Filme stretch 500mm", "RL", 48.00, (20, 400)),
    ("EMB-FS-M01", "Filme stretch manual", "RL", 32.50, (20, 300)),
    ("EMB-FT-001", "Fita adesiva transparente 48mm", "RL", 4.20, (100, 3000)),
    ("EMB-FT-002", "Fita adesiva personalizada 48mm", "RL", 7.80, (100, 2000)),
    ("EMB-SC-K01", "Saco kraft 2kg", "MI", 210.00, (5, 120)),
    ("EMB-SC-P01", "Saco plástico zip", "MI", 145.00, (5, 150)),
    ("EMB-BD-001", "Bandeja PET alimentos", "MI", 380.00, (2, 60)),
    ("EMB-PT-001", "Pote PP 500ml", "MI", 520.00, (2, 50)),
    ("EMB-PL-001", "Palete PBR madeira", "UN", 62.00, (10, 300)),
    ("EMB-CT-001", "Cantoneira de papelão", "UN", 0.95, (500, 8000)),
    ("EMB-EP-001", "Envelope de segurança", "MI", 290.00, (2, 80)),
]

# Perfil de pagamento (variável latente, não exportada como dado SAP)
SEGMENTOS = ["pontual", "toleravel", "atrasador", "critico"]
PESOS_SEGMENTO = [0.55, 0.30, 0.12, 0.03]
PROB_INADIMPLENCIA = {"pontual": 0.001, "toleravel": 0.01, "atrasador": 0.05, "critico": 0.25}

# Sazonalidade mensal de pedidos (pico pré-Black Friday e Natal)
SAZONALIDADE = {1: 0.75, 2: 0.80, 3: 0.95, 4: 0.95, 5: 1.00, 6: 0.95,
                7: 1.00, 8: 1.05, 9: 1.15, 10: 1.30, 11: 1.35, 12: 0.90}


@dataclass
class Config:
    clientes: int
    inicio: pd.Timestamp
    corte: pd.Timestamp
    seed: int
    saida: Path
    formato: str
    sujo: bool


# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------
def data_sap(serie: pd.Series) -> pd.Series:
    """Converte datas para o formato SAP (YYYYMMDD); nulos viram '00000000'."""
    return pd.to_datetime(serie).dt.strftime("%Y%m%d").fillna("00000000")


def gerar_cnpj(rng: np.random.Generator) -> str:
    """Gera um CNPJ fictício com dígitos verificadores válidos (sem máscara)."""
    base = list(rng.integers(0, 10, size=8)) + [0, 0, 0, 1]

    def digito(nums: list[int], pesos: list[int]) -> int:
        resto = sum(n * p for n, p in zip(nums, pesos)) % 11
        return 0 if resto < 2 else 11 - resto

    d1 = digito(base, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    d2 = digito(base + [d1], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return "".join(map(str, base + [d1, d2]))


def nome_empresa(rng: np.random.Generator, ramo: str) -> str:
    prefixos = {
        "ALIM": ["Alimentos", "Laticínios", "Bebidas", "Frigorífico", "Doces"],
        "VARE": ["Comercial", "Atacadão", "Supermercados", "Mercantil", "Magazine"],
        "ECOM": ["Loja Virtual", "Shop", "Store", "Marketplace", "Delivery"],
        "COSM": ["Cosméticos", "Beleza", "Perfumaria", "Dermo"],
        "FARM": ["Farmacêutica", "Drogaria", "Laboratório", "Distribuidora Farma"],
        "AUTO": ["Autopeças", "Distribuidora Automotiva", "Peças"],
    }
    nomes = ["Aurora", "Bandeirante", "Horizonte Sul", "Ipê", "Jequitibá", "Litoral", "Mantiqueira",
             "Nova Era", "Paineira", "Planalto", "Primavera", "Rio Claro", "Serra Azul", "Sol Nascente",
             "Três Rios", "Vale Verde", "Vitória", "Estrela", "Cruzeiro", "Pioneira", "Boa Vista",
             "Cerrado", "Atlântico", "Guarani", "Tropical", "Araucária", "Capixaba", "Pampa"]
    sufixos = ["Ltda", "Ltda", "Ltda", "S.A.", "ME"]
    return f"{rng.choice(prefixos[ramo])} {rng.choice(nomes)} {rng.choice(sufixos)}"


def dias_uteis(inicio: pd.Timestamp, fim: pd.Timestamp) -> pd.DatetimeIndex:
    return pd.bdate_range(inicio, fim)


# ---------------------------------------------------------------------------
# Mestre de clientes: KNA1 + KNB1
# ---------------------------------------------------------------------------
def gerar_clientes(cfg: Config, rng: np.random.Generator):
    ufs = list(REGIOES)
    pesos_uf = np.array([REGIOES[u][1] for u in ufs])
    ramos = list(RAMOS)
    pesos_ramo = np.array([RAMOS[r][0] for r in ramos])

    linhas_kna1, linhas_knb1, latente = [], [], []
    for i in range(cfg.clientes):
        kunnr = f"{100000 + i:010d}"
        uf = rng.choice(ufs, p=pesos_uf / pesos_uf.sum())
        ramo = rng.choice(ramos, p=pesos_ramo / pesos_ramo.sum())
        segmento = rng.choice(SEGMENTOS, p=PESOS_SEGMENTO)

        # Data de cadastro: maioria antiga, parte relevante de clientes novos
        if rng.random() < 0.25:
            erdat = cfg.corte - pd.Timedelta(days=int(rng.integers(30, 540)))
        else:
            erdat = pd.Timestamp("2014-01-01") + pd.Timedelta(days=int(rng.integers(0, 3650)))

        # Porte do cliente (define volume de pedidos) e condição de pagamento
        porte = float(rng.lognormal(mean=0.0, sigma=0.9))
        if porte > 2.5:
            zterm = rng.choice(["D060", "D090"], p=[0.6, 0.4])
        elif porte > 1.0:
            zterm = rng.choice(["D030", "D045", "D060"], p=[0.4, 0.4, 0.2])
        else:
            zterm = rng.choice(["D028", "D030", "D045"], p=[0.3, 0.5, 0.2])

        # Parte dos clientes piora o comportamento de pagamento em algum momento
        deteriora_em = pd.NaT
        if segmento != "critico" and rng.random() < 0.06:
            inicio_possivel = max(erdat, cfg.inicio)
            janela = (cfg.corte - inicio_possivel).days
            if janela > 120:
                deteriora_em = inicio_possivel + pd.Timedelta(days=int(rng.integers(60, janela - 30)))

        linhas_kna1.append({
            "MANDT": MANDT, "KUNNR": kunnr, "LAND1": "BR",
            "NAME1": nome_empresa(rng, ramo), "ORT01": rng.choice(REGIOES[uf][0]),
            "REGIO": uf, "STCD1": gerar_cnpj(rng), "KTOKD": "0001",
            "BRSCH": ramo, "ERDAT": erdat,
        })
        linhas_knb1.append({
            "MANDT": MANDT, "KUNNR": kunnr, "BUKRS": BUKRS,
            "AKONT": "0011200000", "ZTERM": zterm, "ERDAT": erdat,
        })
        latente.append({
            "KUNNR": kunnr, "segmento_pagamento": segmento, "porte": round(porte, 3),
            "deteriora_em": deteriora_em,
        })

    kna1 = pd.DataFrame(linhas_kna1)
    knb1 = pd.DataFrame(linhas_knb1)
    lat = pd.DataFrame(latente)
    return kna1, knb1, lat


# ---------------------------------------------------------------------------
# Vendas: VBAK + VBAP
# ---------------------------------------------------------------------------
def gerar_ordens(cfg: Config, rng: np.random.Generator, kna1: pd.DataFrame,
                 knb1: pd.DataFrame, lat: pd.DataFrame):
    dias = dias_uteis(cfg.inicio, cfg.corte)
    peso_dia = np.array([SAZONALIDADE[d.month] for d in dias])
    zterm_por_cliente = knb1.set_index("KUNNR")["ZTERM"]

    vbak, vbap = [], []
    seq_ordem = 1
    for cli, lat_cli in zip(kna1.itertuples(), lat.itertuples()):
        primeiro_dia = max(cli.ERDAT, cfg.inicio)
        mascara = dias >= primeiro_dia
        if mascara.sum() == 0:
            continue
        meses_ativo = mascara.sum() / 21
        n_ordens = rng.poisson(1.1 * lat_cli.porte * meses_ativo)
        if n_ordens == 0:
            continue

        p = peso_dia[mascara] / peso_dia[mascara].sum()
        datas = np.sort(rng.choice(dias[mascara], size=n_ordens, p=p))
        desconto = min(0.12, 0.03 * lat_cli.porte)  # clientes grandes negociam preço

        for data in datas:
            vbeln = f"{seq_ordem:010d}"
            seq_ordem += 1
            n_itens = int(rng.integers(1, 6))
            idx_mats = rng.choice(len(MATERIAIS), size=n_itens, replace=False)
            total = 0.0
            for pos, idx in enumerate(idx_mats, start=1):
                matnr, descr, unid, preco, (qmin, qmax) = MATERIAIS[idx]
                fator_porte = min(3.0, max(0.3, lat_cli.porte))
                qtd = max(1, int(rng.integers(qmin, qmax) * fator_porte * 0.4))
                preco_unit = preco * (1 - desconto) * rng.normal(1.0, 0.03)
                netwr = round(qtd * preco_unit, 2)
                total += netwr
                vbap.append({
                    "MANDT": MANDT, "VBELN": vbeln, "POSNR": f"{pos * 10:06d}",
                    "MATNR": matnr,
                    "ARKTX": descr, "KWMENG": qtd, "VRKME": unid,
                    "NETWR": netwr, "WAERK": WAERS, "ERDAT": pd.Timestamp(data),
                })
            vbak.append({
                "MANDT": MANDT, "VBELN": vbeln, "ERDAT": pd.Timestamp(data),
                "AUART": "TA", "VKORG": VKORG, "VTWEG": VTWEG, "SPART": SPART,
                "KUNNR": cli.KUNNR, "NETWR": round(total, 2), "WAERK": WAERS,
                "BUKRS_VF": BUKRS, "ZTERM": zterm_por_cliente[cli.KUNNR],
            })

    return pd.DataFrame(vbak), pd.DataFrame(vbap)


# ---------------------------------------------------------------------------
# Faturamento: VBRK + VBRP
# ---------------------------------------------------------------------------
def gerar_faturas(cfg: Config, rng: np.random.Generator, vbak: pd.DataFrame, vbap: pd.DataFrame):
    vbrk, vbrp = [], []
    seq_fat = 90000001
    itens_por_ordem = {k: g for k, g in vbap.groupby("VBELN")}

    for ordem in vbak.itertuples():
        if rng.random() < 0.03:  # ordens canceladas/nunca faturadas
            continue
        fkdat = ordem.ERDAT + pd.offsets.BDay(int(rng.integers(1, 8)))
        if fkdat > cfg.corte:  # ainda em carteira na data de corte
            continue
        vbeln_fat = f"{seq_fat:010d}"
        seq_fat += 1
        netwr = ordem.NETWR
        vbrk.append({
            "MANDT": MANDT, "VBELN": vbeln_fat, "FKART": "F2", "FKDAT": fkdat,
            "KUNAG": ordem.KUNNR, "BUKRS": BUKRS, "NETWR": netwr,
            "MWSBK": round(netwr * ALIQUOTA_IMPOSTO, 2), "WAERK": WAERS,
            "ZTERM": ordem.ZTERM,
        })
        for item in itens_por_ordem[ordem.VBELN].itertuples():
            vbrp.append({
                "MANDT": MANDT, "VBELN": vbeln_fat, "POSNR": item.POSNR,
                "AUBEL": ordem.VBELN, "AUPOS": item.POSNR, "MATNR": item.MATNR,
                "FKIMG": item.KWMENG, "VRKME": item.VRKME, "NETWR": item.NETWR,
            })

    return pd.DataFrame(vbrk), pd.DataFrame(vbrp)


# ---------------------------------------------------------------------------
# Contas a receber: BSID (aberto) + BSAD (compensado)
# ---------------------------------------------------------------------------
def atraso_dias(rng, segmento: str) -> float:
    if segmento == "pontual":
        return rng.normal(-5, 3)
    if segmento == "toleravel":
        return rng.gamma(2.0, 3.0) - 4
    if segmento == "atrasador":
        return rng.gamma(3.0, 7.0)
    return rng.gamma(3.0, 15.0)  # critico


def piorar(segmento: str) -> str:
    return SEGMENTOS[min(SEGMENTOS.index(segmento) + 1, len(SEGMENTOS) - 1)]


def gerar_contas_receber(cfg: Config, rng: np.random.Generator, vbrk: pd.DataFrame,
                         kna1: pd.DataFrame, lat: pd.DataFrame):
    info_cli = kna1.set_index("KUNNR")[["REGIO", "BRSCH", "ERDAT"]].join(lat.set_index("KUNNR"))
    p90_por_cliente = vbrk.groupby("KUNAG")["NETWR"].quantile(0.9)

    bsid, bsad = [], []
    seq_belnr, seq_augbl = 1400000001, 1500000001
    for fat in vbrk.itertuples():
        cli = info_cli.loc[fat.KUNAG]
        prazo = CONDICOES_PAGAMENTO[fat.ZTERM]
        vencimento = fat.FKDAT + pd.Timedelta(days=prazo)

        segmento = cli.segmento_pagamento
        if pd.notna(cli.deteriora_em) and fat.FKDAT >= cli.deteriora_em:
            segmento = piorar(segmento)

        atraso = atraso_dias(rng, segmento)
        atraso += REGIOES[cli.REGIO][2] + RAMOS[cli.BRSCH][1]
        if fat.NETWR > p90_por_cliente[fat.KUNAG]:
            atraso += 4  # faturas grandes pesam mais no caixa do cliente
        if vencimento.month in (12, 1):
            atraso += 3  # fim de ano: 13º, férias, caixa apertado
        if (fat.FKDAT - cli.ERDAT).days < 365:
            atraso += 5  # relacionamento novo, pouco histórico
        if prazo >= 60:
            atraso -= 2  # prazo longo já absorve parte do ciclo do cliente
        atraso = int(round(atraso))

        valor_bruto = round(fat.NETWR + fat.MWSBK, 2)
        belnr = f"{seq_belnr:010d}"
        seq_belnr += 1
        linha = {
            "MANDT": MANDT, "BUKRS": BUKRS, "KUNNR": fat.KUNAG,
            "GJAHR": str(fat.FKDAT.year), "BELNR": belnr, "BUZEI": "001",
            "BUDAT": fat.FKDAT, "BLDAT": fat.FKDAT, "BLART": "RV",
            "SHKZG": "S", "WAERS": WAERS, "DMBTR": valor_bruto, "WRBTR": valor_bruto,
            "ZFBDT": fat.FKDAT, "ZTERM": fat.ZTERM, "ZBD1T": prazo,
            "VBELN": fat.VBELN, "AUGDT": pd.NaT, "AUGBL": "",
        }

        inadimplente = rng.random() < PROB_INADIMPLENCIA[segmento]
        pagamento = vencimento + pd.Timedelta(days=atraso)
        pagamento = max(pagamento, fat.FKDAT + pd.Timedelta(days=1))

        if not inadimplente and pagamento <= cfg.corte:
            linha["AUGDT"] = pagamento
            linha["AUGBL"] = f"{seq_augbl:010d}"
            seq_augbl += 1
            bsad.append(linha)
        else:
            bsid.append(linha)

    return pd.DataFrame(bsid), pd.DataFrame(bsad)


# ---------------------------------------------------------------------------
# Problemas de qualidade de dados (para justificar a camada Silver)
# ---------------------------------------------------------------------------
def sujar_dados(rng, tabelas: dict[str, pd.DataFrame]) -> dict[str, list[str]]:
    log: dict[str, list[str]] = {}

    kna1 = tabelas["KNA1"]
    idx_vazio = rng.choice(kna1.index, size=max(1, int(len(kna1) * 0.02)), replace=False)
    kna1.loc[idx_vazio, "STCD1"] = ""
    dup = kna1.sample(n=max(1, int(len(kna1) * 0.01)), random_state=int(rng.integers(1e9))).copy()
    dup["NAME1"] = dup["NAME1"].str.upper() + "  "
    tabelas["KNA1"] = pd.concat([kna1, dup], ignore_index=True)
    log["KNA1"] = [f"{len(idx_vazio)} clientes com CNPJ (STCD1) vazio",
                   f"{len(dup)} clientes duplicados (mesmo KUNNR, NAME1 em maiúsculas com espaços)"]

    vbap = tabelas["VBAP"]
    idx_zero = rng.choice(vbap.index, size=max(1, int(len(vbap) * 0.005)), replace=False)
    vbap.loc[idx_zero, "KWMENG"] = 0
    log["VBAP"] = [f"{len(idx_zero)} itens com quantidade (KWMENG) zerada"]

    vbrp = tabelas["VBRP"]
    idx_orf = rng.choice(vbrp.index, size=max(1, int(len(vbrp) * 0.003)), replace=False)
    vbrp.loc[idx_orf, "AUBEL"] = "9999999999"
    log["VBRP"] = [f"{len(idx_orf)} itens faturados apontando para ordem inexistente (AUBEL órfão)"]
    return log


# ---------------------------------------------------------------------------
# Exportação
# ---------------------------------------------------------------------------
COLUNAS_DATA = {"ERDAT", "FKDAT", "BUDAT", "BLDAT", "ZFBDT", "AUGDT"}


def exportar(tabelas: dict[str, pd.DataFrame], lat: pd.DataFrame, cfg: Config) -> None:
    cfg.saida.mkdir(parents=True, exist_ok=True)
    for nome, df in tabelas.items():
        df = df.copy()
        for col in COLUNAS_DATA & set(df.columns):
            df[col] = data_sap(df[col])
        caminho = cfg.saida / f"{nome}.{cfg.formato}"
        if cfg.formato == "csv":
            df.to_csv(caminho, index=False, encoding="utf-8")
        else:
            df.astype({c: "string" for c in df.columns if df[c].dtype == object}).to_parquet(caminho, index=False)

    # Gabarito: perfil real de cada cliente. NÃO é dado SAP e NÃO deve virar feature.
    gabarito = cfg.saida.parent / "_gabarito"
    gabarito.mkdir(parents=True, exist_ok=True)
    lat.assign(deteriora_em=data_sap(lat["deteriora_em"])).to_csv(
        gabarito / "perfil_clientes.csv", index=False, encoding="utf-8")


def resumo(tabelas: dict[str, pd.DataFrame], cfg: Config) -> None:
    print(f"\nDados gerados em: {cfg.saida.resolve()}  (corte: {cfg.corte.date()})\n")
    for nome, df in tabelas.items():
        print(f"  {nome:<5} {len(df):>8,} linhas")

    bsid, bsad = tabelas["BSID"], tabelas["BSAD"]
    venc_bsad = bsad["ZFBDT"] + pd.to_timedelta(bsad["ZBD1T"], unit="D")
    pagas_atraso = (bsad["AUGDT"] > venc_bsad).mean()
    venc_bsid = bsid["ZFBDT"] + pd.to_timedelta(bsid["ZBD1T"], unit="D")
    vencido = bsid.loc[venc_bsid < cfg.corte, "DMBTR"].sum()

    print(f"\n  Faturas pagas com atraso:     {pagas_atraso:.1%}")
    print(f"  Carteira em aberto (BSID):    R$ {bsid['DMBTR'].sum():>16,.2f}")
    print(f"  ...dos quais já vencidos:     R$ {vencido:>16,.2f}")

    print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--clientes", type=int, default=800)
    parser.add_argument("--inicio", default="2024-09-01", help="Início do histórico de ordens (YYYY-MM-DD)")
    parser.add_argument("--corte", default="2026-09-22", help="Data de corte da extração (YYYY-MM-DD)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--saida", default="data/raw")
    parser.add_argument("--formato", choices=["csv", "parquet"], default="csv")
    parser.add_argument("--limpo", action="store_true", help="Não injetar problemas de qualidade")
    args = parser.parse_args()

    cfg = Config(
        clientes=args.clientes, inicio=pd.Timestamp(args.inicio), corte=pd.Timestamp(args.corte),
        seed=args.seed, saida=Path(args.saida), formato=args.formato, sujo=not args.limpo,
    )
    rng = np.random.default_rng(cfg.seed)

    kna1, knb1, lat = gerar_clientes(cfg, rng)
    vbak, vbap = gerar_ordens(cfg, rng, kna1, knb1, lat)
    vbrk, vbrp = gerar_faturas(cfg, rng, vbak, vbap)
    bsid, bsad = gerar_contas_receber(cfg, rng, vbrk, kna1, lat)

    tabelas = {"KNA1": kna1, "KNB1": knb1, "VBAK": vbak, "VBAP": vbap,
               "VBRK": vbrk, "VBRP": vbrp, "BSID": bsid, "BSAD": bsad}
    resumo(tabelas, cfg)  # métricas calculadas antes da sujeira
    log_sujeira = sujar_dados(rng, tabelas) if cfg.sujo else {}
    if log_sujeira:
        print("  Problemas de qualidade injetados:")
        for tabela, itens in log_sujeira.items():
            for item in itens:
                print(f"    [{tabela}] {item}")
        print()
    exportar(tabelas, lat, cfg)


if __name__ == "__main__":
    main()
