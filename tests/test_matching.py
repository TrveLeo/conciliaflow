"""Testes do motor de conciliação.

O caso do dataset de demonstração confere contra `demo/GABARITO.md`: o número
que vai para o portfólio precisa ser reproduzível, não estimado.
"""

from pathlib import Path

import pytest

DEMO = Path(__file__).resolve().parent.parent / "demo"


def criar_job(client, **params) -> int:
    payload = {"name": "Fechamento de junho"} | params
    response = client.post("/jobs/", json=payload)
    assert response.status_code == 201
    return response.json()["id"]


def subir(client, job_id: int, source: str, filename: str, content: bytes) -> None:
    response = client.post(
        f"/jobs/{job_id}/upload/{source}",
        files={"file": (filename, content, "text/csv")},
    )
    assert response.status_code == 200, response.text


def conciliar(client, job_id: int) -> dict:
    response = client.post(f"/jobs/{job_id}/reconcile")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def job_pronto(client, csv_sistema, csv_extrato) -> int:
    job_id = criar_job(client)
    subir(client, job_id, "a", "vendas.csv", csv_sistema)
    subir(client, job_id, "b", "extrato.csv", csv_extrato)
    return job_id


def test_reconcile_classifica_as_tres_situacoes(client, job_pronto):
    """PED-1001 bate exato, PED-1002 tem 3 centavos, PED-1003 não compensou."""
    summary = conciliar(client, job_pronto)

    assert summary["conciliados"] == 1
    assert summary["divergentes"] == 1
    assert summary["pendentes"] == 1
    assert summary["por_regra"]["exata"] == 1
    assert summary["por_regra"]["tolerancia_valor"] == 1


def test_match_exato_zera_as_diferencas(client, job_pronto):
    conciliar(client, job_pronto)
    matches = client.get(f"/jobs/{job_pronto}/matches?rule=exata").json()

    assert len(matches) == 1
    match = matches[0]
    assert match["status"] == "conciliado"
    assert match["record_a"]["reference"] == "PED-1001"
    assert match["record_b"]["reference"] == "PED-1001"
    assert match["mismatch_reason"] is None
    assert float(match["amount_difference"]) == 0
    assert match["days_difference"] == 0


def test_divergencia_de_centavos_explica_o_motivo(client, job_pronto):
    conciliar(client, job_pronto)
    matches = client.get(f"/jobs/{job_pronto}/matches?status=divergente").json()

    assert len(matches) == 1
    match = matches[0]
    assert match["rule"] == "tolerancia_valor"
    assert float(match["amount_difference"]) == pytest.approx(0.03)
    assert "0,03" in match["mismatch_reason"]
    assert "2 dias depois" in match["mismatch_reason"]


def test_pendente_aponta_a_fonte_que_faltou(client, job_pronto):
    conciliar(client, job_pronto)
    matches = client.get(f"/jobs/{job_pronto}/matches?status=pendente").json()

    assert len(matches) == 1
    match = matches[0]
    assert match["record_a"]["reference"] == "PED-1003"
    assert match["record_b"] is None
    assert match["mismatch_reason"] == "sem correspondente na fonte B"


def test_tolerancia_zero_transforma_o_par_em_pendente(client, csv_sistema, csv_extrato):
    """Parâmetro é do job: apertar a tolerância muda o resultado."""
    job_id = criar_job(client, amount_tolerance_cents=0)
    subir(client, job_id, "a", "vendas.csv", csv_sistema)
    subir(client, job_id, "b", "extrato.csv", csv_extrato)

    summary = conciliar(client, job_id)

    assert summary["conciliados"] == 1
    assert summary["divergentes"] == 0
    assert summary["pendentes"] == 3  # PED-1002 dos dois lados + PED-1003


def test_janela_de_data_pega_credito_atrasado(client, csv_sistema):
    """Mesmo valor e mesma referência, crédito 2 dias depois: janela, não exata."""
    extrato = (
        "NSU,Referencia,Data Credito,Valor Liquido\n"
        "NSU700001,PED-1001,2026-06-05,1234.56\n"
    ).encode("utf-8")
    job_id = criar_job(client)
    subir(client, job_id, "a", "vendas.csv", csv_sistema)
    subir(client, job_id, "b", "extrato.csv", extrato)

    summary = conciliar(client, job_id)
    assert summary["por_regra"]["janela_data"] == 1
    assert summary["por_regra"]["exata"] == 0

    match = client.get(f"/jobs/{job_id}/matches?rule=janela_data").json()[0]
    assert match["status"] == "divergente"
    assert match["days_difference"] == 2
    assert "2 dias depois" in match["mismatch_reason"]


def test_fora_da_janela_nao_casa(client, csv_sistema):
    extrato = (
        "NSU,Referencia,Data Credito,Valor Liquido\n"
        "NSU700001,SEM-REF,2026-06-20,1234.56\n"
    ).encode("utf-8")
    job_id = criar_job(client, date_window_days=3)
    subir(client, job_id, "a", "vendas.csv", csv_sistema)
    subir(client, job_id, "b", "extrato.csv", extrato)

    summary = conciliar(client, job_id)
    assert summary["conciliados"] == 0
    assert summary["divergentes"] == 0
    assert summary["pendentes"] == 4


def test_referencia_casa_apesar_da_formatacao(client):
    """'PED-1001' e 'ped 1001' são o mesmo pedido para quem opera."""
    vendas = "Pedido;Data Venda;Valor Total\nPED-1001;03/06/2026;100,00\n".encode()
    extrato = "Referencia,Data Credito,Valor Liquido\nped 1001,2026-06-03,100.00\n".encode()
    job_id = criar_job(client)
    subir(client, job_id, "a", "vendas.csv", vendas)
    subir(client, job_id, "b", "extrato.csv", extrato)

    summary = conciliar(client, job_id)
    assert summary["conciliados"] == 1


def test_linha_ilegivel_vira_pendente_com_o_motivo(client, csv_extrato):
    vendas = (
        "Pedido;Data Venda;Valor Total\n"
        "PED-1001;03/06/2026;1.234,56\n"
        "PED-9999;03/06/2026;valor a conferir\n"
    ).encode("utf-8")
    job_id = criar_job(client)
    subir(client, job_id, "a", "vendas.csv", vendas)
    subir(client, job_id, "b", "extrato.csv", csv_extrato)

    conciliar(client, job_id)
    pendentes = client.get(f"/jobs/{job_id}/matches?status=pendente").json()
    motivos = {m["record_a"]["reference"]: m["mismatch_reason"] for m in pendentes if m["record_a"]}

    assert "não foi possível ler a linha" in motivos["PED-9999"]
    assert "valor ilegível" in motivos["PED-9999"]


def test_reconcile_e_idempotente(client, job_pronto):
    primeiro = conciliar(client, job_pronto)
    segundo = conciliar(client, job_pronto)

    assert primeiro == segundo
    assert len(client.get(f"/jobs/{job_pronto}/matches").json()) == 3


def test_reconcile_exige_as_duas_fontes(client, csv_sistema):
    job_id = criar_job(client)
    subir(client, job_id, "a", "vendas.csv", csv_sistema)

    response = client.post(f"/jobs/{job_id}/reconcile")

    assert response.status_code == 400
    assert "duas fontes" in response.json()["detail"]
    assert client.get(f"/jobs/{job_id}").json()["status"] == "erro"


def test_reconcile_de_job_inexistente(client):
    assert client.post("/jobs/999/reconcile").status_code == 404


def test_summary_antes_de_conciliar(client, job_pronto):
    response = client.get(f"/jobs/{job_pronto}/summary")

    assert response.status_code == 409
    assert "ainda não foi conciliado" in response.json()["detail"]


def test_summary_fica_gravado_no_job(client, job_pronto):
    summary = conciliar(client, job_pronto)

    assert client.get(f"/jobs/{job_pronto}/summary").json() == summary
    job = client.get(f"/jobs/{job_pronto}").json()
    assert job["status"] == "concluido"
    assert job["summary_json"]["parametros"]["janela_de_dias"] == 3


def test_export_csv_no_formato_do_excel(client, job_pronto):
    conciliar(client, job_pronto)
    response = client.get(f"/jobs/{job_pronto}/export.csv")

    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    texto = response.content.decode("utf-8")
    assert texto.startswith("﻿")  # BOM, senão o Excel quebra o acento

    linhas = texto.strip().splitlines()
    assert linhas[0].lstrip("﻿").startswith("status;regra;motivo")
    assert len(linhas) == 4  # cabeçalho + 3 resultados
    assert "1234,56" in texto  # vírgula decimal


def test_export_csv_filtra_por_status(client, job_pronto):
    conciliar(client, job_pronto)
    response = client.get(f"/jobs/{job_pronto}/export.csv?status=pendente")

    linhas = response.content.decode("utf-8").strip().splitlines()
    assert len(linhas) == 2
    assert "PED-1003" in linhas[1]


@pytest.mark.skipif(
    not (DEMO / "vendas_sistema.csv").exists(),
    reason="rode scripts/generate_demo_data.py --out demo/",
)
def test_dataset_de_demonstracao_bate_com_o_gabarito(client):
    """O número do portfólio sai daqui.

    Gabarito: 98 exatas, 8 de janela de data, 6 de centavos, 5 vendas sem
    crédito + 3 linhas ilegíveis na fonte A, 4 créditos sem venda na fonte B.
    """
    job_id = criar_job(client, name="Demonstração ConciliaFlow")
    subir(client, job_id, "a", "vendas_sistema.csv", (DEMO / "vendas_sistema.csv").read_bytes())
    subir(
        client,
        job_id,
        "b",
        "extrato_adquirente.csv",
        (DEMO / "extrato_adquirente.csv").read_bytes(),
    )

    summary = conciliar(client, job_id)

    assert summary["por_regra"]["exata"] == 98
    assert summary["por_regra"]["janela_data"] == 8
    assert summary["por_regra"]["tolerancia_valor"] == 6
    assert summary["conciliados"] == 98
    assert summary["divergentes"] == 14
    assert summary["pendentes_fonte_a"] == 8  # 5 sem crédito + 3 ilegíveis
    # 4 ajustes só no extrato + os 3 créditos que ficaram órfãos por causa das
    # linhas ilegíveis do outro lado.
    assert summary["pendentes_fonte_b"] == 7
    assert summary["taxa_conciliacao_automatica"] == pytest.approx(77.2, abs=0.1)
