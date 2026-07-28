"""Gera o dataset de demonstração do ConciliaFlow.

**Dados 100% fictícios**, gerados por semente fixa — nenhum dado de empresa
real, nem anonimizado. As divergências são plantadas de propósito, para que o
case mostre cada regra de conciliação funcionando.

Uso:
    python scripts/generate_demo_data.py --out demo/

Gera:
    vendas_sistema.csv    — lançamentos do sistema interno da empresa (fonte A)
    extrato_adquirente.csv — extrato exportado da adquirente (fonte B)
    GABARITO.md            — o que foi plantado, para conferir o resultado
"""

from __future__ import annotations

import argparse
import csv
import random
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

SEED = 20260728
TOTAL = 120

# Divergências plantadas. O resto das linhas casa exatamente.
N_CENTS_DIFF = 6        # diferença de centavos (taxa arredondada)
N_DATE_SHIFT = 8        # compensação caiu 1 a 3 dias depois
N_ONLY_IN_A = 5         # venda registrada que nunca foi compensada
N_ONLY_IN_B = 4         # crédito no extrato sem lançamento interno
N_BROKEN_ROWS = 3       # linha com data ou valor ilegível

CLIENTS = [
    "Padaria Trigo Dourado", "Auto Peças Vinhedo", "Clínica Bem Estar",
    "Mercearia São Jorge", "Studio Pilates Norte", "Pet Shop Focinho Feliz",
    "Óptica Visão Clara", "Restaurante Canto Mineiro", "Livraria Página Viva",
    "Academia Corpo Ativo", "Floricultura Jardim", "Barbearia Navalha",
]


def brl(value: Decimal) -> str:
    """Formata no padrão brasileiro: 1.234,56."""
    text = f"{value:,.2f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="demo", help="diretório de saída")
    args = parser.parse_args()

    rng = random.Random(SEED)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    start = date(2026, 6, 1)
    rows = []
    for i in range(1, TOTAL + 1):
        rows.append(
            {
                "pedido": f"PED-{1000 + i}",
                "data": start + timedelta(days=rng.randint(0, 29)),
                "valor": Decimal(rng.randrange(2_500, 480_000)) / 100,
                "cliente": rng.choice(CLIENTS),
            }
        )

    indexes = list(range(TOTAL))
    rng.shuffle(indexes)
    cursor = 0

    def take(n: int) -> set[int]:
        nonlocal cursor
        chunk = set(indexes[cursor : cursor + n])
        cursor += n
        return chunk

    cents_diff = take(N_CENTS_DIFF)
    date_shift = take(N_DATE_SHIFT)
    only_in_a = take(N_ONLY_IN_A)
    broken = take(N_BROKEN_ROWS)

    # Fonte A — sistema interno. Cabeçalhos "bonitos", separador ';'.
    path_a = out / "vendas_sistema.csv"
    with path_a.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["Pedido", "Data Venda", "Valor Total", "Cliente"])
        for i, row in enumerate(rows):
            valor = brl(row["valor"])
            data = row["data"].strftime("%d/%m/%Y")
            if i in broken:
                # Planilha real tem célula digitada à mão.
                valor = "valor a conferir" if i % 2 else valor
                data = "31/02/2026" if i % 2 == 0 else data
            writer.writerow([row["pedido"], data, valor, row["cliente"]])

    # Fonte B — extrato da adquirente. Outro vocabulário de cabeçalho, outra
    # ordem de colunas, separador ','. É assim que chega na vida real.
    path_b = out / "extrato_adquirente.csv"
    with path_b.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter=",")
        writer.writerow(["NSU", "Referencia", "Data Credito", "Valor Liquido", "Historico"])
        for i, row in enumerate(rows):
            if i in only_in_a:
                continue  # venda sem compensação

            valor = row["valor"]
            data = row["data"]
            if i in cents_diff:
                valor = valor - Decimal("0.03")
            if i in date_shift:
                data = data + timedelta(days=rng.randint(1, 3))

            writer.writerow(
                [
                    f"NSU{700000 + i}",
                    row["pedido"],
                    data.strftime("%Y-%m-%d"),
                    f"{valor:.2f}",
                    "CREDITO VENDA CARTAO",
                ]
            )

        # Créditos que não existem no sistema interno: estorno, tarifa
        # devolvida, venda lançada fora do sistema.
        for j in range(N_ONLY_IN_B):
            writer.writerow(
                [
                    f"NSU{900000 + j}",
                    f"AJU-{j + 1}",
                    (start + timedelta(days=rng.randint(0, 29))).strftime("%Y-%m-%d"),
                    f"{Decimal(rng.randrange(1_000, 25_000)) / 100:.2f}",
                    "AJUSTE / ESTORNO",
                ]
            )

    gabarito = out / "GABARITO.md"
    gabarito.write_text(
        f"""# Gabarito do dataset de demonstração

**Dados fictícios**, gerados por `scripts/generate_demo_data.py` com semente
`{SEED}`. Rodar de novo produz exatamente os mesmos arquivos.

- Linhas na fonte A (`vendas_sistema.csv`): **{TOTAL}**
- Linhas na fonte B (`extrato_adquirente.csv`): **{TOTAL - N_ONLY_IN_A + N_ONLY_IN_B}**

## Divergências plantadas

| Situação | Qtd | Regra que deve pegar |
|---|---|---|
| Diferença de centavos (taxa arredondada) | {N_CENTS_DIFF} | tolerância de valor |
| Crédito 1 a 3 dias depois da venda | {N_DATE_SHIFT} | janela de data |
| Venda sem compensação (só em A) | {N_ONLY_IN_A} | pendente |
| Crédito sem venda (só em B) | {N_ONLY_IN_B} | pendente |
| Linha com data ou valor ilegível | {N_BROKEN_ROWS} | importada com `parse_error` |

## Resultado esperado da conciliação

Com os parâmetros padrão (janela de 3 dias, tolerância de 5 centavos):

| Resultado | Qtd |
|---|---|
| Conciliado (regra `exata`) | {TOTAL - N_CENTS_DIFF - N_DATE_SHIFT - N_ONLY_IN_A - N_BROKEN_ROWS} |
| Divergente (regra `janela_data`) | {N_DATE_SHIFT} |
| Divergente (regra `tolerancia_valor`) | {N_CENTS_DIFF} |
| Pendente na fonte A | {N_ONLY_IN_A + N_BROKEN_ROWS} |
| Pendente na fonte B | {N_ONLY_IN_B + N_BROKEN_ROWS} |

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
""",
        encoding="utf-8",
    )

    print(f"gerado: {path_a}")
    print(f"gerado: {path_b}")
    print(f"gerado: {gabarito}")


if __name__ == "__main__":
    main()
