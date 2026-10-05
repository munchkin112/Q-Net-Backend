"""API에서 사용할 자격증 검색과 상세정보 조회 서비스를 제공한다."""

from uuid import UUID

from backend.db.connection import database_connection
from backend.db.repository import search_certificates
from backend.db.exam_repository import get_certificate, get_exam_information
from backend.exam_schemas import SubjectsInfo, PassCriteriaInfo, FeesInfo


def list_certificates(query: str, category: str | None, limit: int, offset: int) -> list[dict]:
    """DB 연결을 관리하고 공식 종목명·코드 검색 결과를 반환한다."""
    with database_connection() as connection:
        return search_certificates(connection, query, category, limit, offset)


def certificate_detail(certificate_id: UUID) -> dict | None:
    """저장된 공식 자료를 반환하고 미수집 종목은 확인 필요 상태로 표시한다."""
    with database_connection() as connection:
        certificate = get_certificate(connection, certificate_id)
        if certificate is None:
            return None
        information = get_exam_information(connection, certificate_id)
    if information is None:
        exam = {
            "subjects": SubjectsInfo().model_dump(),
            "pass_criteria": PassCriteriaInfo().model_dump(),
            "fees": FeesInfo().model_dump(),
            "retrieved_at": None, "updated_at": None,
        }
    else:
        exam = {}
        for field in ("subjects", "pass_criteria", "fees", "retrieved_at", "updated_at"):
            exam[field] = information[field]
    statuses = [exam[field]["status"] for field in ("subjects", "pass_criteria", "fees")]
    if all(status == "available" for status in statuses):
        data_status = "complete"
    elif any(status != "unavailable" for status in statuses):
        data_status = "partial"
    else:
        data_status = "unavailable"
    if data_status == "partial":
        message = "일부 시험정보만 확인되었습니다. null 항목은 공식 페이지에서 확인해주세요."
    elif information is not None:
        message = "저장된 공식 시험정보입니다. 원본 조회 시각을 확인해주세요."
    else:
        message = "아직 수집하지 않은 시험정보입니다. 공식 페이지에서 확인해주세요."
    # 출처 링크는 종목 코드로 만들며 아직 조회하지 않은 시각은 채우지 않는다.
    official_url = "https://www.q-net.or.kr/crf005.do?id=crf00503&jmCd=" + certificate["qnet_code"]
    return {
        **certificate, "exam_information": exam, "data_status": data_status,
        "source_type": "database" if information is not None else "none",
        "official_url": official_url,
        "message": message,
    }
