"""공식 상세정보를 조회·검증하고 --apply를 지정한 경우에만 DB에 저장한다."""

import argparse
import json
from pathlib import Path

import psycopg

from backend.db.connection import database_connection
from backend.db.exam_repository import get_certificate_by_code, save_exam_information
from backend.exam_data import normalize_exam_information
from backend.exam_schemas import ExamInformationInput
from backend.official_api import OfficialAPIError, fetch_exam_information, fetch_exam_fees


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def prepare_exam_information(qnet_code: str) -> tuple[dict, ExamInformationInput, dict]:
    """DB에서 대상 종목을 확인하고 공식 API 두 응답을 저장 전에 검증한다."""
    with database_connection() as connection:
        certificate = get_certificate_by_code(connection, qnet_code)
    if certificate is None:
        raise ValueError("저장된 공식 목록에서 종목 코드를 찾을 수 없습니다.")
    if certificate["category"] != "T":
        raise ValueError("현재 상세정보 변환은 기술자격만 지원합니다. 전문자격은 별도 연동이 필요합니다.")
    detail_result = fetch_exam_information(qnet_code)
    fee_result = fetch_exam_fees(qnet_code)
    information = normalize_exam_information(
        certificate["id"], certificate["name"], detail_result, fee_result,
    )
    return certificate, information, {
        "detail_retry_count": detail_result["retry_count"], "fee_retry_count": fee_result["retry_count"],
    }


def main() -> None:
    """기본은 새 공식 자료의 미리보기이며 DB 저장은 명시적으로 선택한다."""
    parser = argparse.ArgumentParser(description="공식 시험과목·합격기준·응시료 조회")
    parser.add_argument("--qnet-code", default="1320")
    parser.add_argument("--apply", action="store_true", help="검증한 상세정보를 DB에 저장")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "research" / "exam_information_preview.json")
    options = parser.parse_args()
    try:
        certificate, information, retry_counts = prepare_exam_information(options.qnet_code)
        report = {
            "mode": "live", "qnet_code": certificate["qnet_code"], "name": certificate["name"],
            "information": information.model_dump(mode="json"), **retry_counts, "database_applied": False,
        }
        if options.apply:
            with database_connection() as connection:
                saved = save_exam_information(connection, information)
            report["database_applied"] = True
            report["saved_retrieved_at"] = saved["retrieved_at"].isoformat()
        options.output.parent.mkdir(parents=True, exist_ok=True)
        options.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"상세정보 확인: {certificate['name']}, DB 저장 여부: {report['database_applied']}")
        for field in ("subjects", "pass_criteria", "fees"):
            print(f"{field}: {getattr(information, field).status}")
    except OfficialAPIError as error:
        print(f"공식 조회 실패: {error.code}, 재시도 {error.retry_count}회. 기존 DB 자료를 유지합니다.")
        raise SystemExit(1) from None
    except ValueError as error:
        print(f"상세정보 검증 실패: {error}")
        raise SystemExit(1) from None
    except (psycopg.Error, RuntimeError):
        print("DB 연결·저장 실패: 설정과 상세정보 테이블 적용 상태를 확인해주세요.")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
