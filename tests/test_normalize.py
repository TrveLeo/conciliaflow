from datetime import date
from decimal import Decimal

import pytest

from app.services.normalize import (
    detect_mapping,
    normalize_row,
    parse_amount,
    parse_date,
    slug_header,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1.234,56", Decimal("1234.56")),
        ("R$ 1.234,56", Decimal("1234.56")),
        ("1234.56", Decimal("1234.56")),
        ("89,90", Decimal("89.90")),
        # Sem vírgula, o ponto é ambíguo. Desempate pelo tamanho do último grupo.
        ("1.000", Decimal("1000")),
        ("1.234.567", Decimal("1234567")),
        ("1234.5", Decimal("1234.50")),
        ("(50,00)", Decimal("-50.00")),
        ("-12,34", Decimal("-12.34")),
        (1234.56, Decimal("1234.56")),
        ("", None),
        ("valor a conferir", None),
        (None, None),
    ],
)
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("03/06/2026", date(2026, 6, 3)),
        ("2026-06-03", date(2026, 6, 3)),
        ("2026-06-03 00:00:00", date(2026, 6, 3)),
        ("03-06-2026", date(2026, 6, 3)),
        ("31/02/2026", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_date(raw, expected):
    assert parse_date(raw) == expected


def test_slug_header_remove_acento_e_pontuacao():
    assert slug_header("Data Pgto.") == "data pgto"
    assert slug_header("REFERÊNCIA") == "referencia"
    assert slug_header("Valor  (R$)") == "valor r"


def test_detect_mapping_vocabularios_diferentes():
    """As duas fontes chamam o mesmo campo por nomes diferentes."""
    fonte_a = detect_mapping(["Pedido", "Data Venda", "Valor Total", "Cliente"])
    assert fonte_a["reference"] == "Pedido"
    assert fonte_a["occurred_on"] == "Data Venda"
    assert fonte_a["amount"] == "Valor Total"
    assert fonte_a["description"] == "Cliente"

    fonte_b = detect_mapping(
        ["NSU", "Referencia", "Data Credito", "Valor Liquido", "Historico"]
    )
    assert fonte_b["external_id"] == "NSU"
    assert fonte_b["reference"] == "Referencia"
    assert fonte_b["occurred_on"] == "Data Credito"
    assert fonte_b["amount"] == "Valor Liquido"


def test_detect_mapping_por_prefixo():
    """'Valor (R$)' não é apelido exato, mas começa com 'valor'."""
    mapping = detect_mapping(["Valor (R$)", "Data de Pagamento"])
    assert mapping["amount"] == "Valor (R$)"
    assert mapping["occurred_on"] == "Data de Pagamento"


def test_detect_mapping_coluna_ausente_fica_de_fora():
    mapping = detect_mapping(["Coluna X", "Coluna Y"])
    assert mapping == {}


def test_normalize_row_converte_formato_brasileiro():
    mapping = detect_mapping(["Pedido", "Data Venda", "Valor Total", "Cliente"])
    row = {
        "Pedido": "PED-1001",
        "Data Venda": "03/06/2026",
        "Valor Total": "1.234,56",
        "Cliente": "Padaria Trigo Dourado",
    }

    result = normalize_row(row, mapping)

    assert result["reference"] == "PED-1001"
    assert result["occurred_on"] == date(2026, 6, 3)
    assert result["amount"] == Decimal("1234.56")
    assert result["parse_error"] is None


def test_normalize_row_registra_erro_sem_descartar_linha():
    """Linha ruim é importada com o motivo. Sumir com ela em silêncio é pior."""
    mapping = detect_mapping(["Pedido", "Data Venda", "Valor Total"])
    row = {
        "Pedido": "PED-1004",
        "Data Venda": "31/02/2026",
        "Valor Total": "valor a conferir",
    }

    result = normalize_row(row, mapping)

    assert result["reference"] == "PED-1004"
    assert result["amount"] is None
    assert result["occurred_on"] is None
    assert "valor ilegível" in result["parse_error"]
    assert "data ilegível" in result["parse_error"]
