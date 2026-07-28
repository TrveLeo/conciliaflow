"""Normalização de planilha para o formato interno.

Duas coisas quebram conciliação de PME antes de qualquer regra de matching:
nome de coluna que muda a cada exportação, e valor/data em formato brasileiro.
Este módulo resolve as duas e nada mais.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

# Nome interno -> apelidos aceitos no cabeçalho do arquivo.
# Comparação é feita sobre o cabeçalho já normalizado (sem acento, minúsculo,
# sem pontuação), então "Data Pgto." casa com "data pgto".
COLUMN_ALIASES: dict[str, list[str]] = {
    "external_id": [
        "id", "codigo", "cod", "identificador", "id transacao", "transacao",
        "documento", "doc", "nsu", "id pagamento",
    ],
    "occurred_on": [
        "data", "data pagamento", "data pgto", "data lancamento", "data movimento",
        "data transacao", "vencimento", "data credito", "dt",
    ],
    "amount": [
        "valor", "valor pago", "valor liquido", "valor bruto", "montante",
        "total", "vlr", "credito", "valor total",
    ],
    "reference": [
        "referencia", "ref", "pedido", "nota", "nota fiscal", "nf", "contrato",
        "fatura", "boleto", "num pedido", "numero pedido",
    ],
    "description": [
        "descricao", "historico", "observacao", "obs", "cliente", "favorecido",
        "detalhe", "memo",
    ],
}

DATE_FORMATS = ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%Y", "%Y/%m/%d")


def slug_header(value: str) -> str:
    """Reduz um cabeçalho a uma forma comparável.

    'Data Pgto.' -> 'data pgto'
    """
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def detect_mapping(headers: list[str]) -> dict[str, str]:
    """Descobre quais colunas do arquivo correspondem aos campos internos.

    Retorna {campo_interno: cabeçalho_original}. Campo não encontrado fica de
    fora — quem chama decide se isso é erro.
    """
    slugged = {slug_header(h): h for h in headers}
    mapping: dict[str, str] = {}

    for field, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in slugged:
                mapping[field] = slugged[alias]
                break
        else:
            # Segunda passada: aceita cabeçalho que *começa* com o apelido,
            # cobrindo "valor (R$)" e "data de pagamento".
            for slug, original in slugged.items():
                if any(slug.startswith(alias) for alias in aliases):
                    mapping[field] = original
                    break

    return mapping


def parse_amount(value: object) -> Decimal | None:
    """Converte valor monetário para Decimal.

    Aceita '1.234,56', '1234.56', 'R$ 1.234,56', '(50,00)' como negativo e
    número já tipado pelo Pandas.
    """
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            return Decimal(str(value)).quantize(Decimal("0.01"))
        except InvalidOperation:
            return None

    text = str(value).strip()
    if not text:
        return None

    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    text = re.sub(r"[^\d,.\-]", "", text)
    if not text:
        return None

    # Formato brasileiro: ponto é milhar, vírgula é decimal.
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif "." in text:
        # Sem vírgula, o ponto é ambíguo: '1234.56' é decimal, '1.000' é mil.
        # Desempate pelo tamanho do último grupo — separador de milhar sempre
        # deixa exatamente 3 dígitos depois dele.
        groups = text.lstrip("-").split(".")
        if len(groups) > 2 or len(groups[-1]) == 3:
            text = text.replace(".", "")

    try:
        amount = Decimal(text).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None

    return -amount if negative else amount


def parse_date(value: object) -> date | None:
    """Converte data para `date`, aceitando os formatos comuns de exportação."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    if not text:
        return None

    # Timestamp do Pandas vem como '2026-07-28 00:00:00'.
    text = text.split(" ")[0]

    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def clean_text(value: object, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none"}:
        return None
    return text[:limit]


def normalize_row(row: dict, mapping: dict[str, str]) -> dict:
    """Aplica o mapeamento a uma linha e converte os tipos.

    Devolve os campos internos mais `parse_error` — texto legível com o que não
    deu para interpretar. A linha nunca é descartada: dado que some em silêncio
    é o problema que este projeto existe para resolver.
    """
    problems: list[str] = []

    raw_amount = row.get(mapping.get("amount", ""))
    amount = parse_amount(raw_amount)
    if "amount" not in mapping:
        problems.append("coluna de valor não encontrada")
    elif amount is None and clean_text(raw_amount, 50):
        problems.append(f"valor ilegível: {clean_text(raw_amount, 30)}")

    raw_date = row.get(mapping.get("occurred_on", ""))
    occurred_on = parse_date(raw_date)
    if "occurred_on" in mapping and occurred_on is None and clean_text(raw_date, 50):
        problems.append(f"data ilegível: {clean_text(raw_date, 30)}")

    return {
        "external_id": clean_text(row.get(mapping.get("external_id", "")), 120),
        "occurred_on": occurred_on,
        "amount": amount,
        "reference": clean_text(row.get(mapping.get("reference", "")), 120),
        "description": clean_text(row.get(mapping.get("description", "")), 255),
        "parse_error": "; ".join(problems)[:255] or None,
    }
