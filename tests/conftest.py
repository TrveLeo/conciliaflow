import os
import tempfile
from collections.abc import Generator

import pytest

# Precisa vir antes de importar qualquer módulo que crie o engine.
_TMP = tempfile.mkdtemp(prefix="conciliaflow-test-")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TMP}/test.db")
os.environ.setdefault("UPLOAD_DIR", f"{_TMP}/uploads")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def clean_database() -> Generator[None, None, None]:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def csv_sistema() -> bytes:
    """Fonte A: separador ';', data dd/mm/aaaa, valor 1.234,56."""
    return (
        "Pedido;Data Venda;Valor Total;Cliente\n"
        "PED-1001;03/06/2026;1.234,56;Padaria Trigo Dourado\n"
        "PED-1002;04/06/2026;89,90;Pet Shop Focinho Feliz\n"
        "PED-1003;05/06/2026;2.500,00;Clínica Bem Estar\n"
    ).encode("utf-8")


@pytest.fixture
def csv_extrato() -> bytes:
    """Fonte B: separador ',', data aaaa-mm-dd, valor 1234.56."""
    return (
        "NSU,Referencia,Data Credito,Valor Liquido,Historico\n"
        "NSU700001,PED-1001,2026-06-03,1234.56,CREDITO VENDA CARTAO\n"
        "NSU700002,PED-1002,2026-06-06,89.87,CREDITO VENDA CARTAO\n"
    ).encode("utf-8")
