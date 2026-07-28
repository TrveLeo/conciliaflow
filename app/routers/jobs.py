import json
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.enums import JobStatus, SourceSide
from app.models import ImportedRecord, ReconciliationJob
from app.schemas import (
    JobCreate,
    JobDetail,
    JobOut,
    JobUpdate,
    RecordOut,
    SourceSummary,
    UploadResult,
)
from app.services.ingest import IngestError, ingest_file

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _get_job(db: Session, job_id: int) -> ReconciliationJob:
    job = db.get(ReconciliationJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job não encontrado")
    return job


@router.post("/", response_model=JobOut, status_code=201)
def create_job(payload: JobCreate, db: Session = Depends(get_db)) -> ReconciliationJob:
    job = ReconciliationJob(**payload.model_dump())
    db.add(job)
    db.commit()
    return job


@router.get("/", response_model=list[JobOut])
def list_jobs(
    status: JobStatus | None = None,
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
) -> list[ReconciliationJob]:
    stmt = select(ReconciliationJob).order_by(ReconciliationJob.id.desc()).limit(limit)
    if status is not None:
        stmt = stmt.where(ReconciliationJob.status == status)
    return list(db.scalars(stmt))


@router.get("/{job_id}", response_model=JobDetail)
def get_job(job_id: int, db: Session = Depends(get_db)) -> dict:
    job = _get_job(db, job_id)

    rows = db.execute(
        select(
            ImportedRecord.source,
            func.count(ImportedRecord.id),
            func.count(ImportedRecord.parse_error),
            func.coalesce(func.sum(ImportedRecord.amount), 0),
        )
        .where(ImportedRecord.job_id == job_id)
        .group_by(ImportedRecord.source)
    ).all()
    by_source = {source: (total, errors, amount) for source, total, errors, amount in rows}

    sources = [
        SourceSummary(
            source=side,
            filename=getattr(job, f"source_{side.value}_name"),
            rows=by_source.get(side, (0, 0, Decimal("0")))[0],
            rows_with_error=by_source.get(side, (0, 0, Decimal("0")))[1],
            total_amount=Decimal(str(by_source.get(side, (0, 0, Decimal("0")))[2])),
        )
        for side in SourceSide
        if getattr(job, f"source_{side.value}_name") or side in by_source
    ]

    detail = JobOut.model_validate(job).model_dump()
    detail["sources"] = sources
    return detail


@router.patch("/{job_id}", response_model=JobOut)
def update_job(
    job_id: int, payload: JobUpdate, db: Session = Depends(get_db)
) -> ReconciliationJob:
    job = _get_job(db, job_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(job, field, value)
    db.add(job)
    db.commit()
    return job


@router.delete("/{job_id}", status_code=204)
def delete_job(job_id: int, db: Session = Depends(get_db)) -> None:
    job = _get_job(db, job_id)
    db.delete(job)
    db.commit()


@router.post("/{job_id}/upload/{source}", response_model=UploadResult)
def upload_source(
    job_id: int,
    source: SourceSide,
    file: UploadFile = File(...),
    column_mapping: str | None = Form(
        default=None,
        description='JSON opcional {"Coluna do arquivo": "campo_interno"} para '
        "corrigir a detecção automática.",
    ),
    db: Session = Depends(get_db),
) -> dict:
    job = _get_job(db, job_id)
    if job.status == JobStatus.conciliando:
        raise HTTPException(
            status_code=409, detail="job em conciliação; aguarde antes de reenviar"
        )

    override: dict[str, str] | None = None
    if column_mapping:
        try:
            override = json.loads(column_mapping)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=400, detail=f"column_mapping não é um JSON válido: {exc}"
            ) from exc
        if not isinstance(override, dict):
            raise HTTPException(
                status_code=400, detail="column_mapping deve ser um objeto JSON"
            )

    content = file.file.read()
    job.status = JobStatus.importando
    db.add(job)
    db.commit()

    try:
        result = ingest_file(db, job, source, file.filename or "arquivo", content, override)
    except IngestError as exc:
        db.rollback()
        job.status = JobStatus.erro
        job.error_message = str(exc)[:500]
        db.add(job)
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    has_a = bool(job.source_a_name)
    has_b = bool(job.source_b_name)
    job.status = JobStatus.pronto if has_a and has_b else JobStatus.criado
    job.error_message = None
    db.add(job)
    db.commit()

    return result


@router.get("/{job_id}/records", response_model=list[RecordOut])
def list_records(
    job_id: int,
    source: SourceSide | None = None,
    only_errors: bool = False,
    limit: int = Query(default=100, le=1000),
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[ImportedRecord]:
    _get_job(db, job_id)
    stmt = (
        select(ImportedRecord)
        .where(ImportedRecord.job_id == job_id)
        .order_by(ImportedRecord.source, ImportedRecord.row_number)
        .limit(limit)
        .offset(offset)
    )
    if source is not None:
        stmt = stmt.where(ImportedRecord.source == source)
    if only_errors:
        stmt = stmt.where(ImportedRecord.parse_error.is_not(None))
    return list(db.scalars(stmt))
