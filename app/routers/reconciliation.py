import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.enums import JobStatus, MatchRule, MatchStatus
from app.models import MatchResult
from app.routers.jobs import _get_job
from app.schemas import MatchOut
from app.services.matching import reconcile

router = APIRouter(prefix="/jobs", tags=["conciliação"])

EXPORT_HEADER = [
    "status",
    "regra",
    "motivo",
    "a_linha",
    "a_referencia",
    "a_data",
    "a_valor",
    "a_descricao",
    "b_linha",
    "b_referencia",
    "b_data",
    "b_valor",
    "b_descricao",
    "diferenca_valor",
    "diferenca_dias",
]


def _matches_query(job_id: int, status: MatchStatus | None, rule: MatchRule | None):
    stmt = (
        select(MatchResult)
        .where(MatchResult.job_id == job_id)
        .options(
            selectinload(MatchResult.record_a),
            selectinload(MatchResult.record_b),
        )
        .order_by(MatchResult.status, MatchResult.id)
    )
    if status is not None:
        stmt = stmt.where(MatchResult.status == status)
    if rule is not None:
        stmt = stmt.where(MatchResult.rule == rule)
    return stmt


@router.post("/{job_id}/reconcile")
def run_reconciliation(job_id: int, db: Session = Depends(get_db)) -> dict:
    """Roda a conciliação e devolve o resumo.

    Pode ser chamado de novo à vontade: recalcula do zero com os parâmetros
    atuais do job.
    """
    job = _get_job(db, job_id)

    job.status = JobStatus.conciliando
    db.add(job)
    db.commit()

    try:
        return reconcile(db, job)
    except ValueError as exc:
        db.rollback()
        job.status = JobStatus.erro
        job.error_message = str(exc)[:500]
        db.add(job)
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{job_id}/summary")
def get_summary(job_id: int, db: Session = Depends(get_db)) -> dict:
    job = _get_job(db, job_id)
    if not job.summary_json:
        raise HTTPException(status_code=409, detail="job ainda não foi conciliado")
    return job.summary_json


@router.get("/{job_id}/matches", response_model=list[MatchOut])
def list_matches(
    job_id: int,
    status: MatchStatus | None = None,
    rule: MatchRule | None = None,
    limit: int = Query(default=100, le=1000),
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[MatchResult]:
    _get_job(db, job_id)
    stmt = _matches_query(job_id, status, rule).limit(limit).offset(offset)
    return list(db.scalars(stmt))


@router.get("/{job_id}/export.csv")
def export_csv(
    job_id: int,
    status: MatchStatus | None = None,
    rule: MatchRule | None = None,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Resultado em CSV para abrir no Excel.

    `;` e vírgula decimal: é o que o Excel em português abre sem assistente de
    importação.
    """
    job = _get_job(db, job_id)
    if not job.summary_json:
        raise HTTPException(status_code=409, detail="job ainda não foi conciliado")

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(EXPORT_HEADER)

    def cell(value) -> str:
        if value is None:
            return ""
        return str(value)

    def money(value) -> str:
        return "" if value is None else f"{value:.2f}".replace(".", ",")

    def day(value) -> str:
        return "" if value is None else value.strftime("%d/%m/%Y")

    for match in db.scalars(_matches_query(job_id, status, rule)):
        a, b = match.record_a, match.record_b
        writer.writerow(
            [
                match.status.value,
                match.rule.value,
                cell(match.mismatch_reason),
                cell(a.row_number) if a else "",
                cell(a.reference) if a else "",
                day(a.occurred_on) if a else "",
                money(a.amount) if a else "",
                cell(a.description) if a else "",
                cell(b.row_number) if b else "",
                cell(b.reference) if b else "",
                day(b.occurred_on) if b else "",
                money(b.amount) if b else "",
                cell(b.description) if b else "",
                money(match.amount_difference),
                cell(match.days_difference),
            ]
        )

    # BOM: sem ele o Excel abre acento quebrado.
    data = "﻿" + buffer.getvalue()
    return StreamingResponse(
        io.BytesIO(data.encode("utf-8")),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="conciliacao_{job_id}.csv"'
        },
    )
