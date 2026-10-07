# Espaço Genie — S4Lake

O espaço Genie fica no Databricks e não é versionado pelo Git. Este arquivo guarda a configuração, as instruções e as perguntas de teste, para que o espaço possa ser recriado e reavaliado a cada nova data de corte.

**Papel no projeto:** exploração em linguagem natural sobre a Gold. O Power BI é a fonte oficial dos números; o Genie acerta os valores das tabelas, mas a narrativa às vezes exagera ou erra a leitura, então toda resposta nova é conferida por SQL.

## Configuração

| Item | Valor |
|---|---|
| Compute | Serverless Starter Warehouse (SQL warehouse) |
| Tabelas | `workspace.s4lake_gold`: `fato_titulos`, `kpis_gerais`, `kpis_por_ramo`, `kpis_por_uf`, `kpis_por_prazo`, `aging_carteira`, `risco_titulos` |
| Fora do espaço | Silver e Bronze (apenas dados governados da Gold) |
| Contexto principal | Comentários de tabelas e colunas no Unity Catalog, aplicados pelos notebooks 06, 07, 08, 10 e 11 |

## Instruções do espaço

As instruções são regras gerais, sem números fixos, para continuarem válidas em qualquer data de corte.

1. Só afirmar tendência entre grupos ordenados se ela valer para todos, na ordem; caso contrário, descrever os grupos que se destacam.
2. Não afirmar causa; usar "está associado a" ou "concentra". Prazo e porte do cliente andam juntos. Avisar quando `qtd_clientes` for pequeno.
3. DSO e `dias_alem_prazo` medem a carteira em dias de venda, não o tempo que os clientes levam para pagar; para isso, usar os atrasos médios.
4. Antes de chamar um cliente de inadimplente crônico ou recomendar cobrança urgente, verificar títulos pagos e o último pagamento. Se paga até hoje, descrever como títulos vencidos específicos; se a maioria dos pagos foi com atraso, como atrasador habitual.
5. Ao falar de concentração, informar o percentual sobre o total, e não palavras como "significativa".
6. A `risco_titulos` cobre só os títulos em aberto que ainda não completaram 30 dias após o vencimento. Os vencidos há mais de 30 dias não estão nela, porque já são atraso grave e estão na `fato_titulos`. Ao falar de "valor em risco da empresa", deixar claro que ele não inclui a carteira já vencida há mais de 30 dias.
7. `probabilidade_atraso` é uma estimativa para ordenar a cobrança, não uma certeza. Apresentá-la em percentual. O `valor_em_risco` é uma perda esperada e tende a ser superestimado; não descrevê-lo como valor que será perdido.

## Perguntas de teste

Respostas esperadas na data de corte de 22/09/2026, obtidas por SQL antes de perguntar ao Genie.

### Rodada 1 (02/10/2026): tabelas de KPIs

| Pergunta | Resposta certa | O que testa | Resultado |
|---|---|---|---|
| Qual é o DSO da empresa? | 79,67 dias | Achar a `kpis_gerais` | Certo |
| Qual condição de pagamento tem o pior atraso? | D030, 26,47 dias além do prazo | Armadilha: pelo DSO bruto seria D090 (98,01) | Certo: usou `dias_alem_prazo` |
| Qual cliente tem mais valor vencido? | 0000100178, R$ 2.946.302,56 | Filtrar vencidos na `fato_titulos` e agrupar | Certo |

### Rodada 2 (07/10/2026): tabela de risco

| Pergunta | Resposta certa | O que testa | Resultado |
|---|---|---|---|
| Qual é o valor em risco total? | R$ 9.140.483,95 | Achar a `risco_titulos`; regras 6 e 7 | Certo, com as duas ressalvas |
| Quantos títulos têm probabilidade de atraso acima de 50%? | 200 títulos, R$ 6.292.977,27 | Filtro por probabilidade | Certo: 200 títulos, R$ 6,29 mi; 57% do valor em risco |
| Quais são os cinco clientes com maior valor em risco? | 0000100178 (R$ 1.554.160,82), 0000100710 (R$ 611.723,54), 0000100276 (R$ 587.984,22), 0000100788 (R$ 480.864,72), 0000100784 (R$ 350.944,57) | Agrupar por cliente e ordenar | Valores idênticos; 39% do total informado |

## Erros de interpretação observados

| Rodada | Erro | Instrução que corrigiu |
|---|---|---|
| 1 | Chamou 39,68% de "segunda maior taxa" (era a maior) | Persistiu como erro de leitura |
| 1 | Inventou a escada "quanto menor o prazo, maior o atraso" | 1 |
| 1 | Afirmou que prazos longos causam menos atraso | 2 |
| 1 | Tratou o DSO como prazo médio de pagamento | 3 |
| 1 | Chamou o cliente 178 de inadimplente crônico | 4 |
| 1 | Somou os cinco maiores como R$ 6,85 mi (certo: R$ 6,84 mi) | Persistiu como erro de aritmética |
| 2 | Descreveu a exposição de um cliente como "significativa" | 5 (descumprida na narrativa) |
| 2 | Apresentou probabilidade média de 99,9% sem ressalva | 7 (cumprida na primeira resposta, não repetida) |

## Como reavaliar

1. Ao mudar a data de corte ou reprocessar a Gold, recalcular por SQL as respostas certas das perguntas de teste.
2. Fazer as perguntas em conversas novas do espaço, sem instruções extras.
3. Conferir o número e a narrativa de cada resposta contra as sete instruções.
4. Registrar nesta página os resultados e qualquer erro novo, e só então ajustar as instruções.
