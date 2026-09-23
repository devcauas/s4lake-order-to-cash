# S4Lake — Order-to-Cash

Arquitetura de referência **SAP + Databricks** para análise e previsão de recebíveis, inspirada no
[SAP Business Data Cloud](https://www.sap.com/products/data-cloud/databricks.html).

> **Transparência:** o SAP Databricks é um produto corporativo licenciado dentro do SAP Business Data Cloud.
> Este projeto reproduz o mesmo padrão de arquitetura com ferramentas gratuitas (SAP BTP trial / HANA Cloud
> e Databricks Free Edition), usando dados sintéticos que seguem o modelo de dados real do SAP (SD + FI-AR).

---

## 1. O problema de negócio

A **Horizonte Embalagens S.A.** (empresa fictícia) é uma indústria B2B que vende embalagens para
clientes de alimentos, varejo, e-commerce, cosméticos, farmacêutico e autopeças em todo o Brasil.

A empresa fatura bem, mas o **caixa não acompanha o faturamento**. Quase metade das faturas é paga com
atraso, e a área de Crédito e Cobrança trabalha de forma reativa: só descobre o problema depois que a
fatura vence. O time de cobrança é pequeno e não consegue ligar para todos os clientes.

## 2. Perguntas que o projeto responde

| Área | Pergunta | Decisão apoiada |
|---|---|---|
| Diretoria financeira | Quanto tempo levamos, em média, para transformar venda em caixa (DSO)? Está piorando? | Planejamento de capital de giro |
| Crédito e Cobrança | Quais faturas **ainda não vencidas** têm maior risco de atraso? | Priorizar a cobrança preventiva |
| Crédito e Cobrança | Quais clientes mudaram de comportamento recentemente? | Revisar limite e condição de pagamento |
| Comercial | Algum ramo, região ou condição de pagamento concentra o atraso? | Política comercial e de prazos |

## 3. Indicadores (KPIs)

- **DSO** (Days Sales Outstanding): prazo médio de recebimento
- **Aging da carteira**: a vencer, vencido 1–30, 31–60, 61–90 e 90+ dias
- **% de faturas pagas com atraso** e **atraso médio ponderado pelo valor**
- **Valor em risco (R$)**: soma das faturas em aberto com alta probabilidade de atraso

## 4. Arquitetura

```
SAP (tabelas SD + FI-AR)          Databricks (Unity Catalog)
KNA1 KNB1 VBAK VBAP       ──▶  Bronze  ──▶  Silver  ──▶  Gold  ──▶  Dashboard + Genie
VBRK VBRP BSID BSAD             (bruto)     (limpo)     (KPIs)      Modelo de ML (MLflow)
```

- **Bronze**: dados como vieram do SAP (datas `YYYYMMDD`, chaves com zeros à esquerda)
- **Silver**: tipagem, deduplicação, regras de qualidade de dados, nomes de negócio
- **Gold**: fato de faturas com vencimento, pagamento e atraso; KPIs agregados
- **ML**: classificação do risco de atraso de faturas em aberto

## 5. Estrutura do repositório

```
data_generator/   Gerador de dados sintéticos no modelo SAP
pipelines/        Pipelines Bronze → Silver → Gold
ml/               Modelo de previsão de atraso
dashboards/       Dashboards e espaço Genie
docs/             Dicionário de dados e decisões de arquitetura
```

## 6. Como gerar os dados

```bash
pip install -r requirements.txt
python data_generator/generate_sap_o2c.py --saida data/raw
```

Opções: `--clientes`, `--inicio`, `--corte`, `--seed`, `--formato csv|parquet` e `--limpo`
(desativa os problemas de qualidade injetados de propósito).

Ao ler os CSVs, trate todas as colunas-chave como **texto**, senão os zeros à esquerda somem
(ex.: `pd.read_csv(..., dtype=str)` ou `inferSchema=false` no Spark).

A pasta `data/_gabarito/` contém o perfil real de pagamento de cada cliente. Ela serve **somente para
validar** o modelo no final e nunca deve ser usada como variável de entrada.

## 7. Roadmap

- [x] Definição do problema de negócio
- [x] Gerador de dados SAP (SD + FI-AR)
- [ ] Carga no SAP HANA Cloud
- [ ] Ingestão Bronze no Databricks
- [ ] Camada Silver com regras de qualidade
- [ ] Camada Gold e KPIs
- [ ] Modelo de risco de atraso (MLflow)
- [ ] Dashboard e espaço Genie
- [ ] CI/CD com GitHub Actions + Databricks Asset Bundles
- [ ] Artigo
