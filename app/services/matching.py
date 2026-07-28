"""Motor de conciliação.

Três regras determinísticas, aplicadas em passadas sucessivas sobre o que
sobrou da anterior. Nenhuma heurística adaptativa e nenhum score: o operador
precisa conseguir refazer no braço qualquer par que o sistema propôs.

Ordem das passadas — da mais forte para a mais fraca:

1. **exata** — mesmo valor, mesma referência e mesma data
2. **janela_data** — mesmo valor, data dentro da janela configurada
3. **tolerancia_valor** — mesma referência, diferença de centavos dentro da
   tolerância

O que sobrar dos dois lados vira `pendente`.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import JobStatus, MatchRule, MatchStatus, SourceSide
from app.models import ImportedRecord, MatchResult, ReconciliationJob

ZERO = Decimal("0.00")


def ref_key(value: str | None) -> str | None:
    """Reduz a referência a uma forma comparável.

    'PED-1001', 'ped 1001' e 'Ped.1001' são o mesmo pedido para quem opera.
    """
    if not value:
        return None
    key = re.sub(r"[^A-Za-z0-9]+", "", value).upper()
    return key or None


def brl(value: Decimal) -> str:
    text = f"{abs(value):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {text}"


def _describe(
    record_a: ImportedRecord,
    record_b: ImportedRecord,
    amount_difference: Decimal,
    days_difference: int | None,
) -> str | None:
    """Motivo legível da divergência. Vazio quando o par bate perfeito."""
    reasons: list[str] = []

    if amount_difference:
        lado = "a menos" if amount_difference > 0 else "a mais"
        reasons.append(f"diferença de {brl(amount_difference)} {lado} na fonte B")

    if days_difference:
        dias = abs(days_difference)
        plural = "dia" if dias == 1 else "dias"
        quando = "depois" if days_difference > 0 else "antes"
        reasons.append(f"crédito {dias} {plural} {quando} do lançamento")

    key_a, key_b = ref_key(record_a.reference), ref_key(record_b.reference)
    if key_a and key_b and key_a != key_b:
        reasons.append(f"referência diferente ({record_a.reference} × {record_b.reference})")

    return "; ".join(reasons) or None


def _days_between(a: date | None, b: date | None) -> int | None:
    if a is None or b is None:
        return None
    return (b - a).days


def _build_match(
    job_id: int, record_a: ImportedRecord, record_b: ImportedRecord, rule: MatchRule
) -> MatchResult:
    amount_a = record_a.amount or ZERO
    amount_b = record_b.amount or ZERO
    amount_difference = amount_a - amount_b
    days_difference = _days_between(record_a.occurred_on, record_b.occurred_on)
    reason = _describe(record_a, record_b, amount_difference, days_difference)

    return MatchResult(
        job_id=job_id,
        record_a_id=record_a.id,
        record_b_id=record_b.id,
        # Casou, mas com diferença? É divergente: alguém precisa olhar.
        status=MatchStatus.conciliado if reason is None else MatchStatus.divergente,
        rule=rule,
        mismatch_reason=reason,
        amount_difference=amount_difference,
        days_difference=days_difference,
    )


def _pending(job_id: int, record: ImportedRecord, other_side: str) -> MatchResult:
    if record.parse_error:
        reason = f"não foi possível ler a linha: {record.parse_error}"
    elif record.amount is None:
        reason = "linha sem valor"
    else:
        reason = f"sem correspondente na fonte {other_side}"

    side = record.source
    return MatchResult(
        job_id=job_id,
        record_a_id=record.id if side == SourceSide.a else None,
        record_b_id=record.id if side == SourceSide.b else None,
        status=MatchStatus.pendente,
        rule=MatchRule.nenhuma,
        mismatch_reason=reason,
    )


def _pass_exact(
    job: ReconciliationJob,
    pending_a: list[ImportedRecord],
    pending_b: list[ImportedRecord],
) -> tuple[list[MatchResult], list[ImportedRecord], list[ImportedRecord]]:
    """Valor, referência e data iguais.

    A data entra na chave de propósito: `exata` precisa significar diferença
    zero. Mesmo pedido creditado três dias depois é um par legítimo, mas é a
    janela de data que pega — e o resultado tem que dizer isso.
    """
    index: dict[tuple[Decimal, str, date | None], list[ImportedRecord]] = defaultdict(list)
    for record in pending_b:
        key = ref_key(record.reference)
        if record.amount is not None and key:
            index[(record.amount, key, record.occurred_on)].append(record)

    matches: list[MatchResult] = []
    used_b: set[int] = set()
    left_a: list[ImportedRecord] = []

    for record in pending_a:
        key = ref_key(record.reference)
        candidates = (
            index.get((record.amount, key, record.occurred_on), [])
            if record.amount is not None and key
            else []
        )
        candidate = next((c for c in candidates if c.id not in used_b), None)
        if candidate is None:
            left_a.append(record)
            continue
        used_b.add(candidate.id)
        matches.append(_build_match(job.id, record, candidate, MatchRule.exata))

    return matches, left_a, [r for r in pending_b if r.id not in used_b]


def _pass_date_window(
    job: ReconciliationJob,
    pending_a: list[ImportedRecord],
    pending_b: list[ImportedRecord],
) -> tuple[list[MatchResult], list[ImportedRecord], list[ImportedRecord]]:
    """Mesmo valor, data dentro da janela. Empate resolve pela data mais próxima."""
    index: dict[Decimal, list[ImportedRecord]] = defaultdict(list)
    for record in pending_b:
        if record.amount is not None:
            index[record.amount].append(record)

    matches: list[MatchResult] = []
    used_b: set[int] = set()
    left_a: list[ImportedRecord] = []

    for record in pending_a:
        if record.amount is None:
            left_a.append(record)
            continue

        best: ImportedRecord | None = None
        best_distance: int | None = None
        for candidate in index.get(record.amount, []):
            if candidate.id in used_b:
                continue
            days = _days_between(record.occurred_on, candidate.occurred_on)
            if days is None or abs(days) > job.date_window_days:
                continue
            distance = abs(days)
            # Empate de distância: fica com a linha mais acima no arquivo,
            # para o resultado não depender da ordem de iteração.
            if best_distance is None or distance < best_distance:
                best, best_distance = candidate, distance

        if best is None:
            left_a.append(record)
            continue
        used_b.add(best.id)
        matches.append(_build_match(job.id, record, best, MatchRule.janela_data))

    return matches, left_a, [r for r in pending_b if r.id not in used_b]


def _pass_amount_tolerance(
    job: ReconciliationJob,
    pending_a: list[ImportedRecord],
    pending_b: list[ImportedRecord],
) -> tuple[list[MatchResult], list[ImportedRecord], list[ImportedRecord]]:
    """Mesma referência, centavos de diferença. Pega taxa arredondada."""
    tolerance = Decimal(job.amount_tolerance_cents) / 100

    index: dict[str, list[ImportedRecord]] = defaultdict(list)
    for record in pending_b:
        key = ref_key(record.reference)
        if key and record.amount is not None:
            index[key].append(record)

    matches: list[MatchResult] = []
    used_b: set[int] = set()
    left_a: list[ImportedRecord] = []

    for record in pending_a:
        key = ref_key(record.reference)
        if not key or record.amount is None:
            left_a.append(record)
            continue

        best: ImportedRecord | None = None
        best_difference: Decimal | None = None
        for candidate in index.get(key, []):
            if candidate.id in used_b:
                continue
            difference = abs(record.amount - (candidate.amount or ZERO))
            if difference > tolerance:
                continue
            if best_difference is None or difference < best_difference:
                best, best_difference = candidate, difference

        if best is None:
            left_a.append(record)
            continue
        used_b.add(best.id)
        matches.append(_build_match(job.id, record, best, MatchRule.tolerancia_valor))

    return matches, left_a, [r for r in pending_b if r.id not in used_b]


def build_summary(job: ReconciliationJob, matches: list[MatchResult]) -> dict:
    """Números da tela de resumo.

    Gravados no job de propósito: a tela não pode depender de agregação em
    tabela grande a cada abertura.
    """
    by_status = {status.value: 0 for status in MatchStatus}
    by_rule = {rule.value: 0 for rule in MatchRule}
    amount_gap = ZERO

    pending_a = pending_b = 0
    for match in matches:
        by_status[match.status.value] += 1
        by_rule[match.rule.value] += 1
        if match.amount_difference:
            amount_gap += match.amount_difference
        if match.status == MatchStatus.pendente:
            if match.record_a_id is not None:
                pending_a += 1
            else:
                pending_b += 1

    paired = by_status[MatchStatus.conciliado.value] + by_status[MatchStatus.divergente.value]
    considered = paired + by_status[MatchStatus.pendente.value]

    return {
        "total_resultados": len(matches),
        "conciliados": by_status[MatchStatus.conciliado.value],
        "divergentes": by_status[MatchStatus.divergente.value],
        "pendentes": by_status[MatchStatus.pendente.value],
        "pendentes_fonte_a": pending_a,
        "pendentes_fonte_b": pending_b,
        "por_regra": by_rule,
        # Percentual do que fechou sozinho, sem intervenção humana.
        "taxa_conciliacao_automatica": (
            round(by_status[MatchStatus.conciliado.value] / considered * 100, 1)
            if considered
            else 0.0
        ),
        "diferenca_de_valor_total": str(amount_gap),
        "parametros": {
            "janela_de_dias": job.date_window_days,
            "tolerancia_em_centavos": job.amount_tolerance_cents,
        },
    }


def reconcile(db: Session, job: ReconciliationJob) -> dict:
    """Roda a conciliação do job e grava o resultado.

    Idempotente: apaga o resultado anterior e recalcula do zero. Rodar de novo
    depois de ajustar a janela ou a tolerância é o fluxo normal de uso.
    """
    records = list(
        db.scalars(
            select(ImportedRecord)
            .where(ImportedRecord.job_id == job.id)
            .order_by(ImportedRecord.source, ImportedRecord.row_number)
        )
    )
    # Linha que não deu para ler não entra nas passadas. Casar por referência
    # uma linha com data ilegível esconderia o problema de qualidade do dado —
    # ela fica pendente até alguém corrigir a planilha e reenviar.
    broken = [r for r in records if r.parse_error]
    readable = [r for r in records if not r.parse_error]

    if not any(r.source == SourceSide.a for r in records) or not any(
        r.source == SourceSide.b for r in records
    ):
        raise ValueError("job precisa das duas fontes obrigatórias importadas")

    pending_a = [r for r in readable if r.source == SourceSide.a]
    pending_b = [r for r in readable if r.source == SourceSide.b]

    db.query(MatchResult).filter(MatchResult.job_id == job.id).delete(
        synchronize_session=False
    )

    matches: list[MatchResult] = []
    for step in (_pass_exact, _pass_date_window, _pass_amount_tolerance):
        found, pending_a, pending_b = step(job, pending_a, pending_b)
        matches.extend(found)

    matches.extend(_pending(job.id, record, "B") for record in pending_a)
    matches.extend(_pending(job.id, record, "A") for record in pending_b)
    matches.extend(
        _pending(job.id, record, "B" if record.source == SourceSide.a else "A")
        for record in broken
    )

    db.add_all(matches)
    db.flush()

    job.summary_json = build_summary(job, matches)
    job.status = JobStatus.concluido
    job.error_message = None
    db.add(job)
    db.commit()

    return job.summary_json
