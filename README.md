# ConciliaFlow

Conciliação de planilhas de pagamento entre fontes que não conversam: sistema
interno de um lado, extrato da adquirente ou do banco do outro.

> **Estado: v0.1 — etapa 1 de 3.** Upload, normalização e persistência prontos.
> O motor de conciliação (etapa 2) e a interface (etapa 3) ainda não existem.
> Especificação completa: [`div_job/portfolio/conciliaflow.md`](https://github.com/TrveLeo/div_job/blob/main/portfolio/conciliaflow.md).

## O problema

Em PME, conferir pagamento é uma pessoa abrindo duas planilhas lado a lado e
comparando linha por linha. As duas planilhas nunca combinam de formato:

| | Sistema interno | Extrato da adquirente |
|---|---|---|
| Separador | `;` | `,` |
| Data | `03/06/2026` | `2026-06-03` |
| Valor | `1.234,56` | `1234.56` |
| Coluna de referência | `Pedido` | `Referencia` |
| Coluna de valor | `Valor Total` | `Valor Liquido` |

O resultado é atraso de fechamento, divergência sem rastro e dependência da
única pessoa que entende a planilha.

## O que a v0.1 faz

- Recebe CSV (`;`, `,`, tab ou `|`, em UTF-8 ou Latin-1) e XLSX
- **Descobre sozinho quais colunas são quais**, por dicionário de apelidos —
  `Data Pgto.`, `Data Venda` e `Data Credito` caem todas em `occurred_on`
- Aceita correção manual do mapeamento quando o arquivo tem duas colunas de
  valor e só o operador sabe qual vale
- Converte valor e data dos formatos brasileiros para tipos reais
- **Guarda a linha original inteira** em `raw_payload` — divergência sem o dado
  de entrada vira discussão
- **Importa a linha ruim marcando o motivo** em vez de descartá-la em silêncio
- Guarda o arquivo enviado em disco, para auditoria
- Reenviar a mesma fonte substitui o conteúdo dela: corrigir a planilha e subir
  de novo é operação normal, não erro

## Decisões que valem explicar

**`parse_error` em vez de rejeitar o arquivo.** Uma célula digitada à mão não
pode derrubar a importação de 500 linhas boas. A linha entra, marcada, e aparece
em `GET /jobs/{id}/records?only_errors=true`.

**`match_rule` em vez de `confidence`.** A especificação original previa um
score de confiança. Com regras determinísticas, esse número seria inventado —
saber *qual* regra fechou o par (`exata`, `janela_data`, `tolerancia_valor`)
é informação real e explica a divergência para quem opera.

**Parâmetros de conciliação salvos no job.** Janela de data e tolerância de
centavos ficam gravadas em cada execução, não só no `.env`. Resultado antigo
continua explicável depois de o padrão mudar.

**Desempate do ponto decimal.** Sem vírgula, `1.000` é mil e `1234.56` é
decimal. A regra é o tamanho do último grupo: separador de milhar sempre deixa
exatamente 3 dígitos depois dele.

## Stack

Python 3.12 · FastAPI · SQLAlchemy 2.0 · PostgreSQL · Pandas (só para XLSX) ·
Docker Compose · pytest

## Rodando

```bash
git clone https://github.com/TrveLeo/conciliaflow.git
cd conciliaflow
cp .env.example .env
docker-compose up -d
```

API em `http://localhost:8000`, documentação interativa em `/docs`.

Sem Docker:

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload
```

## Dataset de demonstração

```bash
python scripts/generate_demo_data.py --out demo/
```

**Dados 100% fictícios**, gerados por semente fixa — rodar de novo produz os
mesmos arquivos. 120 vendas contra 119 créditos, com divergências plantadas de
propósito: 6 diferenças de centavos, 8 créditos com 1 a 3 dias de atraso, 5
vendas sem compensação, 4 créditos sem venda e 3 linhas ilegíveis.

O que foi plantado está em [`demo/GABARITO.md`](demo/GABARITO.md) — serve para
conferir o resultado da conciliação quando a etapa 2 existir.

## Endpoints

| Método | Rota | O que faz |
|---|---|---|
| `POST` | `/jobs/` | Cria uma execução de conciliação |
| `GET` | `/jobs/` | Lista execuções, filtrável por status |
| `GET` | `/jobs/{id}` | Detalhe com resumo por fonte (linhas, erros, total) |
| `PATCH` | `/jobs/{id}` | Ajusta nome, janela de data e tolerância |
| `DELETE` | `/jobs/{id}` | Apaga a execução e os registros dela |
| `POST` | `/jobs/{id}/upload/{a\|b\|c}` | Envia e importa um arquivo |
| `GET` | `/jobs/{id}/records` | Lista as linhas importadas, filtrável por fonte e por erro |

## Testes

```bash
.venv/bin/python -m pytest
```

44 testes, sem banco externo — a suíte roda em SQLite.

## Próximas etapas

- **Etapa 2** — motor de conciliação: match exato, janela de data, tolerância de
  centavos, e endpoint de resumo e divergências
- **Etapa 3** — frontend mínimo de upload e revisão, exportação CSV do resultado

---

Projeto demonstrativo de [Leandro Baldan](https://github.com/TrveLeo),
Consultor de Automação e Dados para PMEs.
