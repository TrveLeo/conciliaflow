from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.enums import JobStatus, MatchRule, MatchStatus, SourceSide


class JobCreate(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    date_window_days: int = Field(default=3, ge=0, le=60)
    amount_tolerance_cents: int = Field(default=5, ge=0, le=10_000)


class JobUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    date_window_days: int | None = Field(default=None, ge=0, le=60)
    amount_tolerance_cents: int | None = Field(default=None, ge=0, le=10_000)


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
    name: str
    description: str | None
    status: JobStatus
    source_a_name: str | None
    source_b_name: str | None
    source_c_name: str | None
    date_window_days: int
    amount_tolerance_cents: int
    summary_json: dict | None
    error_message: str | None


class RecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: SourceSide
    row_number: int
    external_id: str | None
    occurred_on: date | None
    amount: Decimal | None
    reference: str | None
    description: str | None
    parse_error: str | None
    raw_payload: dict


class UploadResult(BaseModel):
    source: SourceSide
    filename: str
    rows_imported: int
    rows_with_error: int
    detected_mapping: dict[str, str]
    unmapped_columns: list[str]


class SourceSummary(BaseModel):
    source: SourceSide
    filename: str | None
    rows: int
    rows_with_error: int
    total_amount: Decimal


class JobDetail(JobOut):
    sources: list[SourceSummary]


class MatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: MatchStatus
    rule: MatchRule
    mismatch_reason: str | None
    amount_difference: Decimal | None
    days_difference: int | None
    record_a: RecordOut | None
    record_b: RecordOut | None
