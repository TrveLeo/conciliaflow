from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.database import Base, engine
from app.routers import jobs, reconciliation

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # MVP sem Alembic: o schema é criado no start. Migração entra quando houver
    # dado de verdade para preservar.
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="ConciliaFlow",
    version="0.2.0",
    description=(
        "Conciliação de planilhas de pagamento entre fontes diferentes: "
        "upload, normalização, matching e relatório de divergências."
    ),
    lifespan=lifespan,
)

app.include_router(jobs.router)
app.include_router(reconciliation.router)

# A tela é HTML e JS servidos daqui mesmo: sem build step, sem segundo
# processo, sem CORS. Ela consome a mesma API pública de /docs — não existe
# rota especial para o frontend.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health", tags=["infra"])
def health() -> dict:
    return {"status": "ok"}
