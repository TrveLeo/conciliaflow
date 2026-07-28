from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.enums import JobStatus, MatchRule, MatchStatus, SourceSide


class ReconciliationJob(Base):
    """Uma execução de conciliação: os arquivos enviados e o resultado."""

    __tablename__ = "reconciliation_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(String(500), default=None)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, native_enum=False), default=JobStatus.criado
    )

    source_a_name: Mapped[str | None] = mapped_column(String(255), default=None)
    source_b_name: Mapped[str | None] = mapped_column(String(255), default=None)
    source_c_name: Mapped[str | None] = mapped_column(String(255), default=None)

    # Parâmetros efetivos desta execução. Guardados no job e não só no config
    # para que um resultado antigo continue explicável depois de o padrão mudar.
    date_window_days: Mapped[int] = mapped_column(Integer, default=3)
    amount_tolerance_cents: Mapped[int] = mapped_column(Integer, default=5)

    # Contagens do último processamento. Redundante com MatchResult de
    # propósito: a tela de resumo não pode depender de agregação em tabela
    # grande a cada abertura.
    summary_json: Mapped[dict | None] = mapped_column(JSON, default=None)
    error_message: Mapped[str | None] = mapped_column(String(500), default=None)

    records: Mapped[list["ImportedRecord"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    matches: Mapped[list["MatchResult"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class ImportedRecord(Base):
    """Uma linha de um arquivo, já normalizada.

    `raw_payload` guarda a linha original inteira. Sem isso, divergência vira
    discussão: o usuário precisa ver o que veio no arquivo, não a nossa
    interpretação dele.
    """

    __tablename__ = "imported_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("reconciliation_jobs.id", ondelete="CASCADE")
    )
    source: Mapped[SourceSide] = mapped_column(Enum(SourceSide, native_enum=False))

    # Número da linha no arquivo original (1 = primeira linha de dados).
    row_number: Mapped[int] = mapped_column(Integer)

    external_id: Mapped[str | None] = mapped_column(String(120), default=None)
    occurred_on: Mapped[date | None] = mapped_column(Date, default=None)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    reference: Mapped[str | None] = mapped_column(String(120), default=None)
    description: Mapped[str | None] = mapped_column(String(255), default=None)

    raw_payload: Mapped[dict] = mapped_column(JSON)

    # Preenchido quando a linha não pôde ser normalizada (data ilegível, valor
    # não numérico). A linha é importada mesmo assim: sumir com ela em silêncio
    # é pior do que mostrá-la como pendente.
    parse_error: Mapped[str | None] = mapped_column(String(255), default=None)

    job: Mapped[ReconciliationJob] = relationship(back_populates="records")


Index("ix_imported_records_job_source", ImportedRecord.job_id, ImportedRecord.source)
Index("ix_imported_records_match_keys", ImportedRecord.job_id, ImportedRecord.amount)


class MatchResult(Base):
    """Resultado da comparação entre um registro de A e um de B."""

    __tablename__ = "match_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("reconciliation_jobs.id", ondelete="CASCADE")
    )

    record_a_id: Mapped[int | None] = mapped_column(
        ForeignKey("imported_records.id", ondelete="CASCADE"), default=None
    )
    record_b_id: Mapped[int | None] = mapped_column(
        ForeignKey("imported_records.id", ondelete="CASCADE"), default=None
    )

    status: Mapped[MatchStatus] = mapped_column(Enum(MatchStatus, native_enum=False))
    rule: Mapped[MatchRule] = mapped_column(
        Enum(MatchRule, native_enum=False), default=MatchRule.nenhuma
    )

    # Texto legível para o operador: "diferença de R$ 0,03" bate mais que um
    # código de erro.
    mismatch_reason: Mapped[str | None] = mapped_column(String(255), default=None)
    amount_difference: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2), default=None
    )
    days_difference: Mapped[int | None] = mapped_column(Integer, default=None)

    job: Mapped[ReconciliationJob] = relationship(back_populates="matches")
    record_a: Mapped[ImportedRecord | None] = relationship(foreign_keys=[record_a_id])
    record_b: Mapped[ImportedRecord | None] = relationship(foreign_keys=[record_b_id])


Index("ix_match_results_job_status", MatchResult.job_id, MatchResult.status)
