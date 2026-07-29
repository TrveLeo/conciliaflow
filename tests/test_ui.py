"""A tela é servida pela própria API — sem build step e sem segundo processo."""


def test_raiz_serve_a_tela(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "ConciliaFlow" in response.text
    assert "/static/app.js" in response.text


def test_estaticos_disponiveis(client):
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_a_tela_nao_aparece_no_schema(client):
    """A raiz é HTML; o /docs continua sendo só a API."""
    caminhos = client.get("/openapi.json").json()["paths"]

    assert "/" not in caminhos
    assert "/jobs/{job_id}/reconcile" in caminhos
