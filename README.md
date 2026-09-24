# S4Lake — Order-to-Cash

Arquitetura de referência **SAP + Databricks** para análise e previsão de recebíveis, inspirada no
[SAP Business Data Cloud](https://www.sap.com/products/data-cloud/databricks.html).

> **Transparência:** o SAP Databricks é um produto corporativo licenciado dentro do SAP Business Data Cloud (BDC).
> A SAP oferece um [basic trial do BDC](https://www.sap.com/products/data-cloud/trial.html) de 30 dias, em tenant
> compartilhado com dados pré-configurados e sem persistência entre períodos, o que não permite hospedar um
> pipeline próprio. Por isso, este projeto reproduz o mesmo padrão de arquitetura com o **Databricks Free Edition**
> (SAP HANA Cloud previsto), usando dados sintéticos que seguem o modelo de dados real do SAP (SD + FI-AR).

---

## 1. O problema de negócio

A **Horizonte Embalagens S.A.** (empresa fictícia) é uma indústria B2B que vende embalagens para
clientes de alimentos, varejo, e-commerce, cosméticos, farmacêutico e autopeças em dez estados do Brasil.

A empresa fatura bem, mas o **caixa não acompanha o faturamento**. Quase metade das faturas é paga com
atraso, e a área de Crédito e Cobrança trabalha de forma reativa: só descobre o problema depois que a
fatura vence. O time de cobrança é pequeno e não consegue ligar para todos os clientes.

> **Pergunta central:** quanto tempo leva, e o que faz demorar, para um título sair da **BSID** (em aberto)
> e chegar na **BSAD** (pago)?

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
SAP (tabelas SD + FI-AR)                  Databricks (Unity Catalog)
KNA1 KNB1 VBAK VBAP    ──▶  Landing  ──▶  Bronze  ──▶  Silver  ──▶  Gold  ──▶  Dashboard + Genie
VBRK VBRP BSID BSAD         (Volume)      (bruto)      (limpo)      (KPIs)      Modelo de ML (MLflow)
```

- **Landing**: volume do Unity Catalog onde os arquivos chegam sem transformação
- **Bronze**: cópia fiel da origem (tudo como texto, datas `YYYYMMDD`, chaves com zeros à esquerda) com metadados de auditoria
- **Silver**: tipagem, deduplicação, nomes de negócio, integridade referencial, **quarentena** de registros inválidos e **reconciliação** de contagens
- **Gold**: fato de títulos com vencimento, pagamento e atraso; KPIs agregados
- **ML**: classificação do risco de atraso de faturas em aberto

Tudo fica no catálogo `workspace`, nos schemas `s4lake_bronze`, `s4lake_silver` e `s4lake_gold`.

### O processo Order-to-Cash nas tabelas SAP

O cliente é cadastrado (**KNA1/KNB1**), faz um pedido (**VBAK/VBAP**), recebe a fatura (**VBRK/VBRP**),
e essa fatura vira um título em aberto (**BSID**) até ser paga (**BSAD**).

## 5. Stack

Python (pandas, numpy) · Databricks Free Edition · PySpark · Spark SQL · Delta Lake · Unity Catalog ·
Git + GitHub (Databricks Git folders) · *previstos:* MLflow, Dashboards/Genie, SAP HANA Cloud,
GitHub Actions + Databricks Asset Bundles

## 6. Qualidade de dados e reconciliação

O gerador injeta problemas de qualidade **de propósito**, para que a camada Silver precise tratá-los:

| Tabela | Problema injetado | Tratamento na Silver |
|---|---|---|
| KNA1 | 8 clientes duplicados | Deduplicação determinística por window function |
| KNA1 | 16 clientes sem CNPJ | Sinalizados com a flag `cnpj_ausente` (mantidos) |
| VBAP | 449 itens com quantidade zerada | Quarentena |
| VBRP | 259 itens com ordem de origem inexistente | Quarentena por integridade referencial |

**Regra do projeto: nenhuma linha some.** Válidos + quarentena = origem, em todas as tabelas:

| Origem (Bronze) | Linhas | Silver (válidos) | Quarentena | Situação |
|---|---:|---:|---:|---|
| KNA1 + KNB1 | 808 / 800 | 800 clientes | – | 8 duplicatas removidas |
| VBAK | 29.877 | 29.877 | – | ✅ |
| VBAP | 89.869 | 89.420 | 449 | ✅ |
| VBRK | 28.725 | 28.725 | – | ✅ |
| VBRP | 86.446 | 86.187 | 259 | ✅ |
| BSID + BSAD | 3.352 + 25.373 | 28.725 | 0 | ✅ |

Checagem de consistência de negócio: **BSID + BSAD = VBRK** (toda fatura virou exatamente um título a receber).

## 7. Principais decisões de arquitetura

| Decisão | Por quê |
|---|---|
| Bronze com tudo como texto e sem correções | Preserva zeros à esquerda e a fidelidade à origem; se uma regra estiver errada, dá para reprocessar sem voltar ao SAP |
| Renomear as colunas na Silver | Da Silver em diante, o consumidor é o analista, não o especialista SAP; o nome original fica preservado na Bronze |
| Flag quando o registro é usável; quarentena quando não é | Cliente sem CNPJ continua devendo; item com quantidade zero não faz sentido |
| `decimal(15,2)` para valores monetários | Evita os erros de arredondamento do `double`; mesmo padrão do SAP |
| Integridade referencial contra a Silver e left joins | Reaproveita dado já tratado e impede que registros sumam em silêncio |
| Não recalcular o cabeçalho da ordem de venda | Mantém o valor oficial do SAP; os KPIs financeiros nascem da fatura |

## 8. Estrutura do repositório

```
data_generator/   Gerador de dados sintéticos no modelo SAP
pipelines/        Notebooks Bronze → Silver → Gold
ml/               Modelo de previsão de atraso
dashboards/       Dashboards e espaço Genie
docs/             Dicionário de dados e decisões de arquitetura
```

Notebooks do pipeline:

| Notebook | O que faz |
|---|---|
| `01_bronze_ingestao` | Lê os CSVs do volume e grava as 8 tabelas Bronze com metadados de auditoria |
| `02_silver_clientes` | Deduplica a KNA1, junta com a KNB1 e sinaliza CNPJ ausente |
| `03_silver_vendas` | Separa ordens e itens, tipa valores e envia itens inválidos para a quarentena |
| `04_silver_faturamento` | Faturas e itens com duas checagens de integridade referencial |
| `05_silver_contas_receber` | Unifica BSID e BSAD em títulos a receber, calcula o vencimento e valida contra as faturas |

## 9. Como gerar os dados

```bash
pip install -r requirements.txt
python data_generator/generate_sap_o2c.py --saida data/raw
```

Opções: `--clientes`, `--inicio`, `--corte`, `--seed`, `--formato csv|parquet` e `--limpo`
(desativa os problemas de qualidade injetados de propósito).

Ao ler os CSVs, trate todas as colunas-chave como **texto**, senão os zeros à esquerda somem
(ex.: `pd.read_csv(..., dtype=str)` ou `inferSchema=false` no Spark).

A pasta `data/_gabarito/` contém o perfil real de pagamento de cada cliente. Ela serve **somente para
validar** o modelo no final e nunca deve ser usada como variável de entrada (evita *data leakage*).

## 10. Roadmap

- [x] Definição do problema de negócio
- [x] Gerador de dados SAP (SD + FI-AR)
- [x] Ingestão Bronze no Databricks
- [x] Camada Silver com regras de qualidade e reconciliação
- [ ] Camada Gold e KPIs
- [ ] Modelo de risco de atraso (MLflow)
- [ ] Dashboard e espaço Genie
- [ ] Exploração do SAP Databricks no basic trial do SAP Business Data Cloud
- [ ] Carga no SAP HANA Cloud
- [ ] CI/CD com GitHub Actions + Databricks Asset Bundles
- [ ] Artigo (SpecificData e LinkedIn)

---

Autor: **Cauã Souza Almeida**
