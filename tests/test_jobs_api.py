import json


def create_job(client, **overrides) -> dict:
    payload = {"name": "Conciliação junho/2026", "description": "Vendas x adquirente"}
    payload.update(overrides)
    response = client.post("/jobs/", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_criar_job_comeca_como_criado(client):
    job = create_job(client)
    assert job["status"] == "criado"
    assert job["date_window_days"] == 3
    assert job["amount_tolerance_cents"] == 5
    assert job["source_a_name"] is None


def test_criar_job_recusa_nome_curto(client):
    assert client.post("/jobs/", json={"name": "ab"}).status_code == 422


def test_job_inexistente_da_404(client):
    assert client.get("/jobs/9999").status_code == 404


def test_upload_das_duas_fontes_deixa_job_pronto(client, csv_sistema, csv_extrato):
    job = create_job(client)

    resposta_a = client.post(
        f"/jobs/{job['id']}/upload/a",
        files={"file": ("vendas_sistema.csv", csv_sistema, "text/csv")},
    )
    assert resposta_a.status_code == 200, resposta_a.text
    assert resposta_a.json()["rows_imported"] == 3
    assert resposta_a.json()["rows_with_error"] == 0
    # Só uma fonte: ainda não dá para conciliar.
    assert client.get(f"/jobs/{job['id']}").json()["status"] == "criado"

    resposta_b = client.post(
        f"/jobs/{job['id']}/upload/b",
        files={"file": ("extrato_adquirente.csv", csv_extrato, "text/csv")},
    )
    assert resposta_b.status_code == 200
    assert resposta_b.json()["rows_imported"] == 2

    detalhe = client.get(f"/jobs/{job['id']}").json()
    assert detalhe["status"] == "pronto"
    assert detalhe["source_a_name"] == "vendas_sistema.csv"
    assert detalhe["source_b_name"] == "extrato_adquirente.csv"


def test_upload_detecta_colunas_de_vocabularios_diferentes(client, csv_sistema, csv_extrato):
    job = create_job(client)

    mapa_a = client.post(
        f"/jobs/{job['id']}/upload/a",
        files={"file": ("vendas.csv", csv_sistema, "text/csv")},
    ).json()["detected_mapping"]
    assert mapa_a["amount"] == "Valor Total"
    assert mapa_a["reference"] == "Pedido"

    mapa_b = client.post(
        f"/jobs/{job['id']}/upload/b",
        files={"file": ("extrato.csv", csv_extrato, "text/csv")},
    ).json()["detected_mapping"]
    assert mapa_b["amount"] == "Valor Liquido"
    assert mapa_b["external_id"] == "NSU"


def test_upload_normaliza_valores_das_duas_fontes(client, csv_sistema, csv_extrato):
    """O mesmo valor escrito de dois jeitos vira o mesmo número."""
    job = create_job(client)
    client.post(
        f"/jobs/{job['id']}/upload/a",
        files={"file": ("vendas.csv", csv_sistema, "text/csv")},
    )
    client.post(
        f"/jobs/{job['id']}/upload/b",
        files={"file": ("extrato.csv", csv_extrato, "text/csv")},
    )

    registros = client.get(f"/jobs/{job['id']}/records").json()
    a1 = next(r for r in registros if r["source"] == "a" and r["row_number"] == 1)
    b1 = next(r for r in registros if r["source"] == "b" and r["row_number"] == 1)

    assert a1["amount"] == "1234.56"   # veio "1.234,56"
    assert b1["amount"] == "1234.56"   # veio "1234.56"
    assert a1["occurred_on"] == b1["occurred_on"] == "2026-06-03"


def test_upload_guarda_linha_original(client, csv_sistema):
    job = create_job(client)
    client.post(
        f"/jobs/{job['id']}/upload/a",
        files={"file": ("vendas.csv", csv_sistema, "text/csv")},
    )

    registro = client.get(f"/jobs/{job['id']}/records").json()[0]
    assert registro["raw_payload"]["Valor Total"] == "1.234,56"


def test_upload_importa_linha_ruim_marcando_o_erro(client):
    conteudo = (
        "Pedido;Data Venda;Valor Total\n"
        "PED-1001;03/06/2026;1.234,56\n"
        "PED-1002;31/02/2026;valor a conferir\n"
    ).encode("utf-8")
    job = create_job(client)

    resposta = client.post(
        f"/jobs/{job['id']}/upload/a",
        files={"file": ("vendas.csv", conteudo, "text/csv")},
    ).json()

    assert resposta["rows_imported"] == 2
    assert resposta["rows_with_error"] == 1

    com_erro = client.get(f"/jobs/{job['id']}/records?only_errors=true").json()
    assert len(com_erro) == 1
    assert com_erro[0]["row_number"] == 2
    assert "data ilegível" in com_erro[0]["parse_error"]


def test_reenviar_a_mesma_fonte_substitui_o_conteudo(client, csv_sistema):
    job = create_job(client)
    client.post(
        f"/jobs/{job['id']}/upload/a",
        files={"file": ("vendas.csv", csv_sistema, "text/csv")},
    )

    corrigido = b"Pedido;Data Venda;Valor Total\nPED-1001;03/06/2026;10,00\n"
    resposta = client.post(
        f"/jobs/{job['id']}/upload/a",
        files={"file": ("vendas_corrigido.csv", corrigido, "text/csv")},
    ).json()

    assert resposta["rows_imported"] == 1
    registros = client.get(f"/jobs/{job['id']}/records?source=a").json()
    assert len(registros) == 1
    assert registros[0]["amount"] == "10.00"


def test_upload_sem_coluna_de_valor_da_400(client):
    job = create_job(client)
    conteudo = b"Coluna X;Coluna Y\nfoo;bar\n"

    resposta = client.post(
        f"/jobs/{job['id']}/upload/a",
        files={"file": ("estranho.csv", conteudo, "text/csv")},
    )

    assert resposta.status_code == 400
    assert "coluna de valor" in resposta.json()["detail"]
    assert client.get(f"/jobs/{job['id']}").json()["status"] == "erro"


def test_upload_de_formato_nao_suportado_da_400(client):
    job = create_job(client)
    resposta = client.post(
        f"/jobs/{job['id']}/upload/a",
        files={"file": ("contrato.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert resposta.status_code == 400
    assert "formato não suportado" in resposta.json()["detail"]


def test_upload_de_arquivo_vazio_da_400(client):
    job = create_job(client)
    resposta = client.post(
        f"/jobs/{job['id']}/upload/a",
        files={"file": ("vazio.csv", b"", "text/csv")},
    )
    assert resposta.status_code == 400


def test_column_mapping_manual_sobrescreve_a_deteccao(client):
    """Duas colunas de valor: o usuário escolhe qual vale."""
    conteudo = (
        "Pedido;Data;Valor Bruto;Valor Liquido\n"
        "PED-1;03/06/2026;100,00;95,00\n"
    ).encode("utf-8")
    job = create_job(client)

    resposta = client.post(
        f"/jobs/{job['id']}/upload/a",
        files={"file": ("vendas.csv", conteudo, "text/csv")},
        data={"column_mapping": json.dumps({"Valor Liquido": "amount"})},
    )

    assert resposta.status_code == 200
    assert resposta.json()["detected_mapping"]["amount"] == "Valor Liquido"
    assert client.get(f"/jobs/{job['id']}/records").json()[0]["amount"] == "95.00"


def test_column_mapping_para_coluna_inexistente_da_400(client, csv_sistema):
    job = create_job(client)
    resposta = client.post(
        f"/jobs/{job['id']}/upload/a",
        files={"file": ("vendas.csv", csv_sistema, "text/csv")},
        data={"column_mapping": json.dumps({"Coluna Fantasma": "amount"})},
    )
    assert resposta.status_code == 400
    assert "inexistentes" in resposta.json()["detail"]


def test_detalhe_do_job_traz_resumo_por_fonte(client, csv_sistema, csv_extrato):
    job = create_job(client)
    client.post(
        f"/jobs/{job['id']}/upload/a",
        files={"file": ("vendas.csv", csv_sistema, "text/csv")},
    )
    client.post(
        f"/jobs/{job['id']}/upload/b",
        files={"file": ("extrato.csv", csv_extrato, "text/csv")},
    )

    fontes = {s["source"]: s for s in client.get(f"/jobs/{job['id']}").json()["sources"]}

    assert fontes["a"]["rows"] == 3
    assert fontes["a"]["total_amount"] == "3824.46"   # 1234,56 + 89,90 + 2500,00
    assert fontes["b"]["rows"] == 2
    assert fontes["b"]["total_amount"] == "1324.43"


def test_apagar_job_apaga_os_registros(client, csv_sistema, db):
    from app.models import ImportedRecord

    job = create_job(client)
    client.post(
        f"/jobs/{job['id']}/upload/a",
        files={"file": ("vendas.csv", csv_sistema, "text/csv")},
    )

    assert client.delete(f"/jobs/{job['id']}").status_code == 204
    assert client.get(f"/jobs/{job['id']}").status_code == 404
    assert db.query(ImportedRecord).filter_by(job_id=job["id"]).count() == 0


def test_listar_jobs_filtra_por_status(client):
    create_job(client, name="Job um")
    create_job(client, name="Job dois")

    assert len(client.get("/jobs/").json()) == 2
    assert len(client.get("/jobs/?status=criado").json()) == 2
    assert len(client.get("/jobs/?status=concluido").json()) == 0
