from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import Base, engine
from app.routers import jobs


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # MVP sem Alembic: o schema é criado no start. Migração entra quando houver
    # dado de verdade para preservar.
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="ConciliaFlow",
    version="0.1.0",
    description=(
        "Conciliação de planilhas de pagamento entre fontes diferentes: "
        "upload, normalização, matching e relatório de divergências."
    ),
    lifespan=lifespan,
)

app.include_router(jobs.router)


@app.get("/health", tags=["infra"])
def health() -> dict:
    return {"status": "ok"}
