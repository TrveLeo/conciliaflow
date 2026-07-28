"""Leitura do arquivo enviado e persistência das linhas normalizadas."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.enums import SourceSide
from app.models import ImportedRecord, ReconciliationJob
from app.services.normalize import detect_mapping, normalize_row

SUPPORTED_SUFFIXES = {".csv", ".txt", ".xlsx", ".xls"}


class IngestError(Exception):
    """Arquivo que não dá para processar. Vira 400, não 500."""


def _decode(content: bytes) -> str:
    """Exportação de sistema brasileiro vem em UTF-8 ou Latin-1, sem aviso."""
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise IngestError("não foi possível ler o arquivo: codificação desconhecida")


def _sniff_delimiter(sample: str) -> str:
    """CSV brasileiro costuma usar ';' porque a vírgula é decimal."""
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ";" if sample.count(";") > sample.count(",") else ","


def read_tabular(content: bytes, filename: str) -> tuple[list[str], list[dict]]:
    """Devolve (cabeçalhos, linhas) de um CSV ou XLSX.

    Pandas só é importado no ramo do Excel: instalação sem openpyxl continua
    servindo CSV em vez de quebrar no import.
    """
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise IngestError(
            f"formato não suportado: {suffix or 'sem extensão'}. "
            f"Aceitos: {', '.join(sorted(SUPPORTED_SUFFIXES))}"
        )

    if suffix in {".xlsx", ".xls"}:
        try:
            import pandas as pd
        except ImportError as exc:  # pragma: no cover - depende do ambiente
            raise IngestError(
                "leitura de Excel requer pandas e openpyxl instalados"
            ) from exc

        frame = pd.read_excel(io.BytesIO(content), dtype=object)
        frame = frame.where(frame.notna(), None)
        headers = [str(c) for c in frame.columns]
        rows = frame.to_dict(orient="records")
        return headers, [{str(k): v for k, v in row.items()} for row in rows]

    text = _decode(content)
    if not text.strip():
        raise IngestError("arquivo vazio")

    delimiter = _sniff_delimiter(text[:4096])
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames:
        raise IngestError("arquivo sem cabeçalho")

    headers = [h.strip() for h in reader.fieldnames if h is not None]
    rows = [dict(row) for row in reader]
    return headers, rows


def store_upload(job_id: int, source: SourceSide, filename: str, content: bytes) -> Path:
    """Guarda o arquivo original em disco.

    Guardar o original é requisito de auditoria: sem ele não dá para provar que
    a divergência veio do dado de entrada e não do nosso processamento.
    """
    directory = Path(settings.upload_dir) / str(job_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{source.value}_{Path(filename).name}"
    path.write_bytes(content)
    return path


def ingest_file(
    db: Session,
    job: ReconciliationJob,
    source: SourceSide,
    filename: str,
    content: bytes,
    mapping_override: dict[str, str] | None = None,
) -> dict:
    """Importa um arquivo para o job, substituindo o conteúdo anterior daquela fonte.

    Reenviar o mesmo lado é operação normal — o usuário corrige a planilha e
    sobe de novo. Por isso os registros antigos daquela fonte são apagados.
    """
    limit = settings.max_upload_mb * 1024 * 1024
    if len(content) > limit:
        raise IngestError(f"arquivo maior que o limite de {settings.max_upload_mb} MB")

    headers, rows = read_tabular(content, filename)
    if not rows:
        raise IngestError("arquivo não tem nenhuma linha de dados")

    mapping = detect_mapping(headers)
    if mapping_override:
        unknown = set(mapping_override) - set(headers)
        if unknown:
            raise IngestError(
                f"mapeamento aponta para colunas inexistentes: {', '.join(sorted(unknown))}"
            )
        # O override vem como {coluna_do_arquivo: campo_interno}; invertemos.
        mapping.update({field: column for column, field in mapping_override.items()})

    if "amount" not in mapping:
        raise IngestError(
            "não foi possível identificar a coluna de valor. "
            f"Colunas do arquivo: {', '.join(headers)}"
        )

    db.query(ImportedRecord).filter(
        ImportedRecord.job_id == job.id, ImportedRecord.source == source
    ).delete(synchronize_session=False)

    records: list[ImportedRecord] = []
    for index, row in enumerate(rows, start=1):
        normalized = normalize_row(row, mapping)
        records.append(
            ImportedRecord(
                job_id=job.id,
                source=source,
                row_number=index,
                raw_payload={str(k): (None if v is None else str(v)) for k, v in row.items()},
                **normalized,
            )
        )

    db.add_all(records)
    store_upload(job.id, source, filename, content)

    setattr(job, f"source_{source.value}_name", Path(filename).name)
    db.add(job)
    db.commit()

    with_errors = sum(1 for r in records if r.parse_error)
    return {
        "source": source.value,
        "filename": Path(filename).name,
        "rows_imported": len(records),
        "rows_with_error": with_errors,
        "detected_mapping": mapping,
        "unmapped_columns": [h for h in headers if h not in mapping.values()],
    }
