# Gabarito do dataset de demonstração

**Dados fictícios**, gerados por `scripts/generate_demo_data.py` com semente
`20260728`. Rodar de novo produz exatamente os mesmos arquivos.

- Linhas na fonte A (`vendas_sistema.csv`): **120**
- Linhas na fonte B (`extrato_adquirente.csv`): **119**

## Divergências plantadas

| Situação | Qtd | Regra que deve pegar |
|---|---|---|
| Diferença de centavos (taxa arredondada) | 6 | tolerância de valor |
| Crédito 1 a 3 dias depois da venda | 8 | janela de data |
| Venda sem compensação (só em A) | 5 | pendente |
| Crédito sem venda (só em B) | 4 | pendente |
| Linha com data ou valor ilegível | 3 | importada com `parse_error` |

Conciliação exata esperada: **98** pares.

## Diferenças de formato entre as fontes

De propósito, para exercitar a normalização:

- Separador `;` na fonte A, `,` na fonte B
- Data `dd/mm/aaaa` na A, `aaaa-mm-dd` na B
- Valor `1.234,56` na A, `1234.56` na B
- Cabeçalhos diferentes para o mesmo campo: `Pedido` / `Referencia`,
  `Data Venda` / `Data Credito`, `Valor Total` / `Valor Liquido`
