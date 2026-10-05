"""시험 상세정보 저장과 종목별 조회를 담당한다."""

from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Jsonb

from backend.exam_schemas import ExamInformationInput


def get_certificate(connection: Connection, certificate_id: UUID) -> dict | None:
    """내부 ID로 공식 종목을 찾고, 없으면 None을 반환한다."""
    return connection.execute("SELECT * FROM certificates WHERE id = %s", (certificate_id,)).fetchone()


def get_certificate_by_code(connection: Connection, qnet_code: str) -> dict | None:
    """공식 종목 코드로 조회하며 코드 앞자리의 0을 유지한다."""
    return connection.execute("SELECT * FROM certificates WHERE qnet_code = %s", (qnet_code,)).fetchone()


def get_exam_information(connection: Connection, certificate_id: UUID) -> dict | None:
    """DB에 보관된 공식 상세정보를 조회한다."""
    return connection.execute(
        "SELECT * FROM exam_information WHERE certificate_id = %s", (certificate_id,)
    ).fetchone()


def save_exam_information(connection: Connection, information: ExamInformationInput, allow_partial: bool = False) -> dict:
    """검증한 정보를 저장하고, 오래되거나 누락된 자료로 기존 값을 지우지 않는다."""
    fields = (information.subjects, information.pass_criteria, information.fees)
    # 파싱 실패나 일부 누락이 있으면 기존 자료를 지우지 않고 저장을 거절한다.
    if not allow_partial and any(field.status != "available" for field in fields):
        raise ValueError("전체 저장은 세 정보의 확인 상태가 모두 available이어야 가능합니다.")
    if all(field.status == "unavailable" for field in fields):
        raise ValueError("확인된 시험정보가 없어 저장하지 않습니다.")
    if allow_partial:
        existing = get_exam_information(connection, information.certificate_id)
        if existing is not None:
            # 새로운 원문이 일부 누락되면 이전에 확인한 값을 지우지 않고 기존 전체 자료를 유지한다.
            for name in ("subjects", "pass_criteria", "fees"):
                incoming = getattr(information, name).model_dump(mode="json")
                for phase in ("written", "practical", "interview", "common"):
                    if existing[name].get(phase) is not None and incoming.get(phase) is None:
                        return existing
    retrieved_at = max(field.retrieved_at for field in fields if field.retrieved_at is not None)
    saved = connection.execute(
        """INSERT INTO exam_information
        (certificate_id, subjects, pass_criteria, fees, raw_acquisition_text, raw_fee_text, retrieved_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (certificate_id) DO UPDATE SET
            subjects = EXCLUDED.subjects, pass_criteria = EXCLUDED.pass_criteria,
            fees = EXCLUDED.fees, raw_acquisition_text = EXCLUDED.raw_acquisition_text,
            raw_fee_text = EXCLUDED.raw_fee_text, retrieved_at = EXCLUDED.retrieved_at, updated_at = now()
        WHERE COALESCE((EXCLUDED.subjects->>'retrieved_at')::timestamptz, '-infinity'::timestamptz)
              >= COALESCE((exam_information.subjects->>'retrieved_at')::timestamptz, '-infinity'::timestamptz)
          AND COALESCE((EXCLUDED.pass_criteria->>'retrieved_at')::timestamptz, '-infinity'::timestamptz)
              >= COALESCE((exam_information.pass_criteria->>'retrieved_at')::timestamptz, '-infinity'::timestamptz)
          AND COALESCE((EXCLUDED.fees->>'retrieved_at')::timestamptz, '-infinity'::timestamptz)
              >= COALESCE((exam_information.fees->>'retrieved_at')::timestamptz, '-infinity'::timestamptz)
        RETURNING *""",
        (information.certificate_id, Jsonb(information.subjects.model_dump(mode="json")),
         Jsonb(information.pass_criteria.model_dump(mode="json")), Jsonb(information.fees.model_dump(mode="json")),
         information.raw_acquisition_text, information.raw_fee_text, retrieved_at),
    ).fetchone()
    if saved is not None:
        return saved
    return get_exam_information(connection, information.certificate_id)
