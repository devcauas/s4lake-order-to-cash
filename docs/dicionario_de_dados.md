# Dicionário de dados — tabelas SAP do Order-to-Cash

Convenções: datas em `YYYYMMDD` (texto; `00000000` = vazio), chaves com zeros à esquerda,
`MANDT` (mandante) em todas as tabelas. Valores em BRL.

## Fluxo do documento

```
KNA1/KNB1 (cliente) ─▶ VBAK/VBAP (ordem) ─▶ VBRK/VBRP (fatura) ─▶ BSID (em aberto) ─▶ BSAD (paga)
                          VBELN ◀── AUBEL        VBELN ◀── VBELN
```

## KNA1 — Mestre de clientes (dados gerais)
| Campo | Descrição |
|---|---|
| KUNNR | Código do cliente (chave) |
| NAME1 | Razão social |
| ORT01 / REGIO / LAND1 | Cidade / UF / país |
| STCD1 | CNPJ (sem máscara) |
| KTOKD | Grupo de contas do cliente |
| BRSCH | Ramo de atividade (ALIM, VARE, ECOM, COSM, FARM, AUTO) |
| ERDAT | Data de cadastro |

## KNB1 — Mestre de clientes (dados da empresa)
| Campo | Descrição |
|---|---|
| KUNNR + BUKRS | Chave: cliente + empresa |
| AKONT | Conta de reconciliação no razão |
| ZTERM | Condição de pagamento (D028, D030, D045, D060, D090 = dias) |

## VBAK / VBAP — Ordem de venda (cabeçalho / itens)
| Campo | Descrição |
|---|---|
| VBELN | Número da ordem (chave) |
| POSNR | Item da ordem (VBAP) |
| ERDAT | Data de criação |
| AUART | Tipo de ordem (TA = ordem padrão) |
| VKORG / VTWEG / SPART | Organização de vendas / canal / setor |
| KUNNR | Cliente emissor |
| MATNR / ARKTX | Material / descrição (VBAP) |
| KWMENG / VRKME | Quantidade / unidade (VBAP) |
| NETWR / WAERK | Valor líquido / moeda |
| ZTERM | Condição de pagamento da ordem |

## VBRK / VBRP — Faturamento (cabeçalho / itens)
| Campo | Descrição |
|---|---|
| VBELN | Número da fatura (chave) |
| FKART | Tipo de faturamento (F2 = fatura) |
| FKDAT | Data da fatura |
| KUNAG | Cliente emissor |
| NETWR / MWSBK | Valor líquido / imposto (simplificado: 18%) |
| AUBEL / AUPOS | Ordem e item de origem (VBRP) |
| FKIMG | Quantidade faturada (VBRP) |

## BSID / BSAD — Contas a receber (em aberto / compensadas)
| Campo | Descrição |
|---|---|
| BUKRS + GJAHR + BELNR + BUZEI | Chave do documento contábil |
| KUNNR | Cliente |
| BUDAT / BLDAT | Data de lançamento / data do documento |
| BLART | Tipo de documento (RV = fatura vinda do SD) |
| SHKZG | Débito (S) / crédito (H) |
| DMBTR / WRBTR | Valor em moeda interna / do documento (bruto, com imposto) |
| ZFBDT + ZBD1T | Data base + dias de prazo → **vencimento = ZFBDT + ZBD1T** |
| VBELN | Fatura de origem (liga com VBRK) |
| AUGDT / AUGBL | Data e documento de compensação (**pagamento**; só em BSAD) |

**Atraso em dias** = `AUGDT − (ZFBDT + ZBD1T)` para faturas pagas; para faturas em aberto,
`data de corte − vencimento`.

## Problemas de qualidade injetados (modo padrão)
| Tabela | Problema | Tratamento esperado na Silver |
|---|---|---|
| KNA1 | CNPJ vazio | Sinalizar e manter (regra de alerta) |
| KNA1 | KUNNR duplicado com nome em maiúsculas e espaços | Deduplicar e padronizar texto |
| VBAP | Quantidade zerada | Colocar em quarentena |
| VBRP | AUBEL apontando para ordem inexistente | Integridade referencial → quarentena |
