# ConciliaFlow

Conciliação de planilhas de pagamento entre fontes que não conversam: sistema
interno de um lado, extrato da adquirente ou do banco do outro.

> **Estado: v0.2 — etapas 1 e 2 de 3.** Upload, normalização, motor de
> conciliação e exportação prontos. Falta a interface (etapa 3).
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

## O que a v0.2 faz

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
- **Concilia as duas fontes por três regras** e classifica cada linha em
  conciliado, divergente ou pendente
- **Escreve o motivo da divergência em português** — "diferença de R$ 0,03 a
  menos na fonte B; crédito 2 dias depois do lançamento"
- Exporta o resultado em CSV que o Excel em português abre direto

## O motor de conciliação

Três regras determinísticas, em passadas sucessivas sobre o que sobrou da
anterior. Sem score, sem heurística adaptativa: o operador precisa conseguir
refazer no braço qualquer par que o sistema propôs.

| Ordem | Regra | Casa quando | Resultado |
|---|---|---|---|
| 1 | `exata` | valor, referência e data iguais | conciliado |
| 2 | `janela_data` | mesmo valor, data dentro da janela | divergente |
| 3 | `tolerancia_valor` | mesma referência, centavos dentro da tolerância | divergente |
| — | `nenhuma` | sobrou de um dos lados | pendente |

Quando há mais de um candidato, ganha o de menor diferença — de dias na regra 2,
de valor na regra 3. Empate fica com a linha mais acima no arquivo, para o
resultado não depender da ordem de iteração.

No dataset de demonstração: **98 conciliados, 14 divergentes, 15 pendentes**,
77,2% de conciliação automática — números conferidos por teste contra o
gabarito, não estimados.

## Decisões que valem explicar

**`parse_error` em vez de rejeitar o arquivo.** Uma célula digitada à mão não
pode derrubar a importação de 500 linhas boas. A linha entra, marcada, e aparece
em `GET /jobs/{id}/records?only_errors=true`.

**`match_rule` em vez de `confidence`.** A especificação original previa um
score de confiança. Com regras determinísticas, esse número seria inventado —
saber *qual* regra fechou o par (`exata`, `janela_data`, `tolerancia_valor`)
é informação real e explica a divergência para quem opera.

**Linha ilegível não é conciliada.** Casar por referência uma linha com data
ilegível esconderia o problema de qualidade do dado. Ela fica pendente com o
motivo — e deixa o crédito do outro lado órfão de propósito, até a planilha ser
corrigida e reenviada.

**Conciliação é idempotente.** `POST /jobs/{id}/reconcile` recalcula do zero com
os parâmetros atuais. Apertar a tolerância e rodar de novo é o fluxo normal de
uso, não recuperação de erro.

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

O que foi plantado está em [`demo/GABARITO.md`](demo/GABARITO.md), junto com o
resultado esperado da conciliação — é contra ele que a suíte de testes confere.

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
| `POST` | `/jobs/{id}/reconcile` | Roda a conciliação e devolve o resumo |
| `GET` | `/jobs/{id}/summary` | Resumo gravado da última execução |
| `GET` | `/jobs/{id}/matches` | Lista os pares, filtrável por status e por regra |
| `GET` | `/jobs/{id}/export.csv` | Resultado em CSV para abrir no Excel |

## Testes

```bash
.venv/bin/python -m pytest
```

61 testes, sem banco externo — a suíte roda em SQLite. Um deles concilia o
dataset de demonstração inteiro e confere o resultado contra o gabarito.

## Próximas etapas

- **Etapa 3** — frontend mínimo de upload e revisão das divergências
- Suporte à terceira fonte opcional na conciliação (hoje ela é importada, mas o
  matching é entre A e B)
- Marcar divergência como resolvida, com quem resolveu e quando

---

Projeto demonstrativo de [Leandro Baldan](https://github.com/TrveLeo),
Consultor de Automação e Dados para PMEs.
