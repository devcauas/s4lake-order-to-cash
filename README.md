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

| Área | Pergunta | Decisão apoiada | Onde é respondida |
|---|---|---|---|
| Diretoria financeira | Quanto tempo levamos, em média, para transformar venda em caixa (DSO)? Está piorando? | Planejamento de capital de giro | `kpis_gerais` · Power BI, página 1 |
| Crédito e Cobrança | Quais faturas **ainda não vencidas** têm maior risco de atraso? | Priorizar a cobrança preventiva | Modelo de ML *(previsto)* |
| Crédito e Cobrança | Quais clientes mudaram de comportamento recentemente? | Revisar limite e condição de pagamento | Modelo de ML *(previsto)* |
| Comercial | Algum ramo, região ou condição de pagamento concentra o atraso? | Política comercial e de prazos | Recortes da Gold · Power BI, página 2 |

## 3. Indicadores (KPIs)

- **DSO** (Days Sales Outstanding): prazo médio de recebimento, comparado ao prazo médio concedido
- **Dias além do prazo**: DSO menos o prazo médio concedido; permite comparar grupos com prazos diferentes
- **Aging da carteira**: a vencer, vencido 1–30, 31–60, 61–90 e 90+ dias, em quantidade e em R$
- **% de faturas pagas com atraso** e **atraso médio** (simples e ponderado pelo valor)
- **Valor em risco (R$)**: soma das faturas em aberto com alta probabilidade de atraso *(previsto, com o modelo de ML)*

### Resultados na data de corte (22/09/2026)

Todos os atrasos de títulos em aberto são medidos contra uma **data de corte fixa**, o mesmo conceito da
data-chave (*key date*) dos relatórios de contas a receber do SAP, como a FBL5N. Assim, o resultado é
reproduzível: rodar o pipeline em outro dia não muda os números.

| Indicador | Valor |
|---|---:|
| Carteira em aberto | R$ 94.812.358,05 |
| Carteira vencida | R$ 20.072.845,68 (21,17%) |
| Faturas pagas com atraso | 47,87% (12.147 de 25.373) |
| Atraso médio simples / ponderado pelo valor | 5,54 / 5,69 dias |
| DSO (janela de 90 dias) | 79,67 dias |
| Prazo médio concedido (ponderado pelo valor) | 61,66 dias |
| Dias além do prazo (DSO − prazo médio concedido) | 18,01 dias |

**Principais leituras:**

- **Faturas maiores atrasam mais:** o atraso ponderado pelo valor é maior que o simples.
- **O aging tem forma de "U":** a maior parte dos vencidos está em 1–30 dias ou já passou de 90 dias
  (402 de 728 títulos vencidos, R$ 11,16 mi). A janela de cobrança efetiva é o primeiro mês.
- **Um único KPI não basta:** o atraso médio dos pagos fica abaixo de 6 dias, mas o DSO está 18 dias acima
  do prazo concedido. O atraso médio só enxerga quem pagou (viés de sobrevivência); o DSO enxerga a
  carteira, onde ficam os títulos que nunca foram pagos.

> **Duas medidas parecidas, mas diferentes:** os **dias além do prazo** (18,01) comparam o DSO com o prazo
> médio concedido e são usados nos recortes e no painel. A definição de livro do *Average Days Delinquent*
> é o DSO menos o *Best Possible DSO* (calculado só com a carteira a vencer), o que equivale à
> **carteira vencida medida em dias de venda: 16,87 dias**. Os dois números não devem ser misturados.

### Onde está o atraso: recortes por ramo, UF e prazo

O DSO bruto **engana** na comparação entre grupos, porque cada grupo tem uma mistura diferente de prazos.
Por isso, os recortes são comparados pelos **dias além do prazo**:

- **Prazo:** o D090 tem o maior DSO (98 dias), mas é o grupo que menos atrasa (8 dias além do prazo,
  contra 19 a 26 nos demais). Quem recebe 90 dias naturalmente demora mais para pagar, mesmo pagando em dia.
- **Ramo:** e-commerce é o pior (27,35 dias além do prazo) e farmacêutico, o melhor (11,09). Pelo DSO
  bruto, o farmacêutico parecia mediano.
- **UF:** Pernambuco se destaca com 46,80 dias além do prazo, mais que o dobro do segundo colocado. O Ceará,
  que parecia ruim pelo DSO bruto (80,70), é um dos melhores estados (10,13).
- **Concentração:** em Pernambuco, um único cliente responde por **81% da carteira vencida do estado**.
  Ele continua ativo e pagando a maioria das faturas, mas acumulou títulos específicos sem pagamento ao longo
  de quase dois anos. A ação indicada é revisar esses títulos, e não mudar a política comercial do estado.
- **Grupos pequenos pedem cautela:** cada recorte traz a quantidade de clientes, porque segmentos com poucos
  clientes (CE com 29, BA com 39) variam ao acaso.

## 4. Arquitetura

```
SAP (tabelas SD + FI-AR)                  Databricks (Unity Catalog)
KNA1 KNB1 VBAK VBAP    ──▶  Landing  ──▶  Bronze  ──▶  Silver  ──▶  Gold  ──▶  Power BI + Genie
VBRK VBRP BSID BSAD         (Volume)      (bruto)      (limpo)      (KPIs)      Modelo de ML (MLflow)
```

- **Landing**: volume do Unity Catalog onde os arquivos chegam sem transformação
- **Bronze**: cópia fiel da origem (tudo como texto, datas `YYYYMMDD`, chaves com zeros à esquerda) com metadados de auditoria
- **Silver**: tipagem, deduplicação, nomes de negócio, integridade referencial, **quarentena** de registros inválidos e **reconciliação** de contagens
- **Gold**: fato de títulos, KPIs gerais, recortes por ramo, UF e prazo, e aging em R$ (detalhes abaixo)
- **Consumo**: painel no Power BI Desktop lendo a Gold por um SQL warehouse; espaço Genie *(previsto)*
- **ML**: classificação do risco de atraso de faturas em aberto *(previsto)*

Tudo fica no catálogo `workspace`, nos schemas `s4lake_bronze`, `s4lake_silver` e `s4lake_gold`.

### Tabelas da Gold

| Tabela | Grão (uma linha é...) | Linhas |
|---|---|---:|
| `fato_titulos` | um título a receber, com dias de atraso, situação e faixa de aging | 28.725 |
| `kpis_gerais` | a empresa inteira em uma data de corte | 1 |
| `kpis_por_ramo` | um ramo de atividade | 6 |
| `kpis_por_uf` | uma UF | 10 |
| `kpis_por_prazo` | um prazo de pagamento | 5 |
| `aging_carteira` | uma faixa de aging da carteira em aberto | 5 |

Os recortes são calculados pela mesma função que gera a `kpis_gerais`: chamada sem agrupamento, ela
reproduz exatamente os 12 indicadores gerais, o que serve de teste para os recortes.

### O processo Order-to-Cash nas tabelas SAP

O cliente é cadastrado (**KNA1/KNB1**), faz um pedido (**VBAK/VBAP**), recebe a fatura (**VBRK/VBRP**),
e essa fatura vira um título em aberto (**BSID**) até ser paga (**BSAD**).

## 5. Painel no Power BI

A pasta `dashboards/` contém o painel em Power BI Desktop, em **modo Import**: os dados (sintéticos)
vão dentro do `.pbix`, então qualquer pessoa consegue abri-lo no Power BI Desktop, sem acesso ao Databricks.
As credenciais de conexão não ficam salvas no arquivo.

| Página | Para quem | O que mostra |
|---|---|---|
| Visão executiva | Diretoria financeira | Carteira em aberto e vencida, DSO com o prazo concedido e os dias além do prazo, % pago com atraso e aging em R$ |
| Onde está o atraso | Área Comercial | Dias além do prazo por ramo, UF e prazo, com a média da empresa como referência e destaque para os grupos acima dela |
| Clientes | Crédito e Cobrança | *Prevista para a etapa de ML, com o risco previsto por título* |

Todas as regras de negócio ficam na Gold; o Power BI apenas exibe. O painel foi feito no Power BI Desktop;
a publicação no Power BI Service ficaria para um ambiente corporativo.

## 6. Stack

Python (pandas, numpy) · Databricks Free Edition · PySpark · Spark SQL · Delta Lake · Unity Catalog ·
Databricks SQL warehouse · Power BI Desktop · Git + GitHub (Databricks Git folders) ·
*previstos:* MLflow, Genie, SAP HANA Cloud, GitHub Actions + Databricks Asset Bundles

## 7. Qualidade de dados e reconciliação

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

Na Gold, as tabelas também se amarram:

- a soma dos títulos por situação reproduz as contagens da Silver (pagos no prazo + pagos com atraso = 25.373;
  a vencer + vencidos = 3.352);
- os valores somados na `fato_titulos` batem com a carteira aberta e o total pago da `kpis_gerais`;
- em cada recorte, as colunas de soma e contagem reproduzem a `kpis_gerais` (razões não são somadas entre grupos);
- a junção dos títulos com os clientes mantém as 28.725 linhas, sem nenhum título sem ramo ou UF;
- 790 dos 800 clientes têm títulos; os 10 restantes estão cadastrados, mas nunca foram faturados.

## 8. Principais decisões de arquitetura

| Decisão | Por quê |
|---|---|
| Bronze com tudo como texto e sem correções | Preserva zeros à esquerda e a fidelidade à origem; se uma regra estiver errada, dá para reprocessar sem voltar ao SAP |
| Renomear as colunas na Silver | Da Silver em diante, o consumidor é o analista, não o especialista SAP; o nome original fica preservado na Bronze |
| Flag quando o registro é usável; quarentena quando não é | Cliente sem CNPJ continua devendo; item com quantidade zero não faz sentido |
| `decimal(15,2)` para valores monetários | Evita os erros de arredondamento do `double`; mesmo padrão do SAP |
| Integridade referencial contra a Silver e left joins | Reaproveita dado já tratado e impede que registros sumam em silêncio |
| Não recalcular o cabeçalho da ordem de venda | Mantém o valor oficial do SAP; os KPIs financeiros nascem da fatura |
| Data de corte fixa, e não `current_date()` | Reprodutibilidade; espelha a data-chave dos relatórios de contas a receber do SAP |
| Dias de atraso com sinal na fato; negativos zerados só no KPI | A fato fica intacta e cada indicador decide como usar o dado |
| Classificações sem valor padrão (`otherwise`) | Um caso inesperado aparece como nulo, em vez de ganhar um valor inventado |
| Gold com detalhe e resumos em tabelas separadas | Grãos diferentes para perguntas diferentes; o painel lê dos resumos |
| Colunas de soma e contagem mantidas nas tabelas de KPIs | Qualquer leitor consegue refazer cada indicador |
| DSO com carteira e faturamento na mesma base (valor bruto) | Dividir valor bruto por líquido inflaria o DSO |
| Recorte por prazo usa o prazo do título, e não o do cadastro | O prazo do cadastro é o atual; aplicado ao histórico, inverteria causa e efeito quando o prazo muda |
| Uma função de KPIs para o total e para os recortes | Evita código copiado; sem agrupamento, reproduz a `kpis_gerais` e serve de teste |
| Divisões com `try_divide` | No modo ANSI, uma divisão por zero quebraria o pipeline |
| Dias além do prazo e quantidade de clientes em cada recorte | O DSO bruto não é comparável entre grupos; grupos pequenos pedem cautela |
| Descrição do ramo na dimensão de clientes (Silver) | É atributo do cliente; Gold, Power BI e Genie herdam o nome legível |
| Regras de negócio na Gold, e não no Power BI | Cada regra existe em um só lugar; o painel apenas exibe |
| Power BI em modo Import | Economiza a cota da Free Edition e permite versionar o `.pbix` com os dados |

## 9. Estrutura do repositório

```
data_generator/   Gerador de dados sintéticos no modelo SAP
pipelines/        Notebooks Bronze → Silver → Gold
ml/               Modelo de previsão de atraso
dashboards/       Painel do Power BI (.pbix) e espaço Genie
docs/             Dicionário de dados e decisões de arquitetura
```

Notebooks do pipeline:

| Notebook | O que faz |
|---|---|
| `01_bronze_ingestao` | Lê os CSVs do volume e grava as 8 tabelas Bronze com metadados de auditoria |
| `02_silver_clientes` | Deduplica a KNA1, junta com a KNB1, sinaliza CNPJ ausente e acrescenta a descrição do ramo |
| `03_silver_vendas` | Separa ordens e itens, tipa valores e envia itens inválidos para a quarentena |
| `04_silver_faturamento` | Faturas e itens com duas checagens de integridade referencial |
| `05_silver_contas_receber` | Unifica BSID e BSAD em títulos a receber, calcula o vencimento e valida contra as faturas |
| `06_gold_fato_titulos` | Calcula dias de atraso contra a data de corte, situação e faixa de aging de cada título |
| `07_gold_kpis_gerais` | Resume a carteira em uma linha de KPIs: vencidos, atrasos médios, DSO, prazo médio e dias além do prazo |
| `08_gold_recortes` | Junta os títulos aos clientes e calcula os KPIs por ramo, UF e prazo, e o aging em R$ |

## 10. Como gerar os dados

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

### Simplificações conscientes

- A condição de pagamento (prazo em dias) é extraída do próprio código (`D030` → 30); num SAP real, viria da tabela **T052**.
- A descrição do ramo de atividade é mapeada no notebook; num SAP real, viria da tabela de textos **T016T**.

## 11. Roadmap

- [x] Definição do problema de negócio
- [x] Gerador de dados SAP (SD + FI-AR)
- [x] Ingestão Bronze no Databricks
- [x] Camada Silver com regras de qualidade e reconciliação
- [x] Camada Gold e KPIs
  - [x] Fato de títulos com atraso, situação e aging
  - [x] KPIs gerais com DSO e dias além do prazo
  - [x] Aging em R$ e recortes por ramo, UF e condição de pagamento
- [ ] Painel e espaço Genie
  - [x] Power BI: visão executiva
  - [x] Power BI: onde está o atraso
  - [X] Espaço Genie no Databricks
  - [ ] Power BI: clientes, com o risco previsto (junto com o modelo de ML)
- [ ] Modelo de risco de atraso (MLflow)
- [ ] Exploração do SAP Databricks no basic trial do SAP Business Data Cloud
- [ ] Carga no SAP HANA Cloud
- [ ] CI/CD com GitHub Actions + Databricks Asset Bundles
- [ ] Artigo (SpecificData e LinkedIn)

---

Autor: **Cauã Souza Almeida**