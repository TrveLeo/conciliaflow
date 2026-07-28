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

## Resultado esperado da conciliação

Com os parâmetros padrão (janela de 3 dias, tolerância de 5 centavos):

| Resultado | Qtd |
|---|---|
| Conciliado (regra `exata`) | 98 |
| Divergente (regra `janela_data`) | 8 |
| Divergente (regra `tolerancia_valor`) | 6 |
| Pendente na fonte A | 8 |
| Pendente na fonte B | 7 |

Linha ilegível não é conciliada de propósito: casá-la por referência esconderia
o problema de qualidade do dado. Ela fica pendente — e deixa o crédito
correspondente órfão do outro lado — até a planilha ser corrigida e reenviada.

Esses números são verificados em `tests/test_matching.py`.

## Diferenças de formato entre as fontes

De propósito, para exercitar a normalização:

- Separador `;` na fonte A, `,` na fonte B
- Data `dd/mm/aaaa` na A, `aaaa-mm-dd` na B
- Valor `1.234,56` na A, `1234.56` na B
- Cabeçalhos diferentes para o mesmo campo: `Pedido` / `Referencia`,
  `Data Venda` / `Data Credito`, `Valor Total` / `Valor Liquido`
