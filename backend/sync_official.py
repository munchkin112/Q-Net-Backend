"""공식 응답을 검증하고 미리보기 파일을 만든다. DB 저장은 --apply로만 실행한다."""

import argparse
from datetime import datetime
import json
from pathlib import Path
from uuid import uuid4

import psycopg

from backend.db.connection import database_connection
from backend.db.repository import save_certificate, save_schedule
from backend.official_api import OfficialAPIError, fetch_catalog, fetch_technical_schedules, parse_xml_items
from backend.official_data import normalize_catalog, normalize_technical_schedules


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_snapshot(metadata_file: str, label: str) -> dict:
    """기존 조사 응답과 당시 조회 시각을 읽는다. 최신 재조회로 표시하지 않는다."""
    metadata = json.loads((PROJECT_ROOT / "research" / metadata_file).read_text(encoding="utf-8"))
    records = metadata["api_probes"] if isinstance(metadata, dict) else metadata
    for record in records:
        if record.get("label") == label and record.get("response_file"):
            xml_text = (PROJECT_ROOT / "research" / record["response_file"]).read_text(encoding="utf-8")
            return {
                "items": parse_xml_items(xml_text),
                "source_url": record["source_url"],
                "retrieved_at": datetime.fromisoformat(record["retrieved_at"]),
                "retry_count": 0,
            }
    raise ValueError("해당 종목의 저장된 공식 응답이 없습니다. 실시간 조회로 확인해야 합니다.")


def prepare_official_data(qnet_code: str, live: bool = False) -> dict:
    """모든 공식 데이터를 변환·검증한 뒤 반환하며, 이 함수는 DB를 변경하지 않는다."""
    if live:
        catalog_result = fetch_catalog()
    else:
        catalog_result = read_snapshot("official_source_results.json", "certificate_list")
    certificates = normalize_catalog(
        catalog_result["items"], catalog_result["source_url"], catalog_result["retrieved_at"]
    )
    selected = None
    for certificate in certificates:
        if certificate.qnet_code == qnet_code:
            selected = certificate
            break
    if selected is None:
        raise ValueError("공식 목록에서 선택한 종목 코드를 찾을 수 없습니다.")
    if selected.category != "T":
        raise ValueError("이번 일정 변환은 기술자격만 지원합니다. 전문자격은 별도 연동이 필요합니다.")
    if live:
        schedule_result = fetch_technical_schedules(qnet_code)
    else:
        schedule_result = read_snapshot("official_operation_results.json", "api_operation_7199_" + qnet_code)
        schedule_result["source_url"] += "?jmCd=" + qnet_code
    schedules = normalize_technical_schedules(
        schedule_result["items"], uuid4(), selected.name,
        schedule_result["source_url"], schedule_result["retrieved_at"],
    )
    return {
        "certificates": certificates, "selected": selected, "schedules": schedules,
        "mode": "live" if live else "snapshot",
        "catalog_retry_count": catalog_result["retry_count"],
        "schedule_retry_count": schedule_result["retry_count"],
    }


def apply_official_data(prepared: dict) -> dict:
    """검증된 종목·일정을 한 트랜잭션으로 저장하며 중간 실패 시 전체를 취소한다."""
    with database_connection() as connection:
        selected_id = None
        for certificate in prepared["certificates"]:
            saved = save_certificate(connection, certificate)
            if certificate.qnet_code == prepared["selected"].qnet_code:
                selected_id = saved["id"]
        if selected_id is None:
            raise ValueError("저장된 자격증 ID를 확인할 수 없습니다.")
        saved_schedule_ids = []
        for schedule in prepared["schedules"]:
            # 미리보기의 임시 ID 대신 DB에서 실제 종목 ID를 얻어 연결한다.
            database_schedule = schedule.model_copy(update={"certificate_id": selected_id})
            saved = save_schedule(connection, database_schedule, preserve_known=True)
            saved_schedule_ids.append(str(saved["id"]))
    return {"certificate_id": str(selected_id), "schedule_ids": saved_schedule_ids}


def main() -> None:
    """기본은 저장된 응답으로 미리보기만 생성하고, 명시한 옵션만 실행한다."""
    parser = argparse.ArgumentParser(description="공식 종목 목록과 필기·실기 일정 변환")
    parser.add_argument("--qnet-code", default="1320")
    parser.add_argument("--live", action="store_true", help="공식 API에서 새로 조회")
    parser.add_argument("--apply", action="store_true", help="검증 완료 후 DATABASE_URL의 DB에 저장")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "research" / "normalized_preview.json")
    options = parser.parse_args()
    try:
        prepared = prepare_official_data(options.qnet_code, options.live)
        report = {
            "status": "validated", "mode": prepared["mode"],
            "qnet_code": prepared["selected"].qnet_code, "name": prepared["selected"].name,
            "certificate_count": len(prepared["certificates"]),
            "schedule_phase_count": len(prepared["schedules"]),
            "catalog_retrieved_at": prepared["selected"].last_synced_at.isoformat(),
            "catalog_retry_count": prepared["catalog_retry_count"],
            "schedule_retry_count": prepared["schedule_retry_count"],
            "schedules": [], "database_applied": False,
        }
        for schedule in prepared["schedules"]:
            row = schedule.model_dump(mode="json")
            row.pop("certificate_id")  # 아직 DB에 연결하지 않은 임시 ID는 공개하지 않는다.
            report["schedules"].append(row)
        if options.apply:
            report["database_result"] = apply_official_data(prepared)
            report["database_applied"] = True
        options.output.parent.mkdir(parents=True, exist_ok=True)
        options.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"검증 완료: 종목 {report['certificate_count']}개, 시험 단계 {report['schedule_phase_count']}개")
        print(f"DB 저장 여부: {report['database_applied']}")
    except OfficialAPIError as error:
        print(json.dumps({"status": "unavailable", "error_type": error.code,
                          "retry_count": error.retry_count, "message": str(error),
                          "official_confirmation_url": "https://www.q-net.or.kr/"}, ensure_ascii=False))
        raise SystemExit(1) from None
    except ValueError as error:
        print(f"변환·검증 실패: {error}")
        raise SystemExit(1) from None
    except (psycopg.Error, RuntimeError):
        print("DB 연결·저장 실패: DATABASE_URL과 초기 테이블 적용 상태를 확인해주세요. 변경은 취소됩니다.")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
