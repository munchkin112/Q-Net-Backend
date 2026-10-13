"""이번 산업안전기사 검증에서 저장한 공식 페이지를 기존 일정 코드에 연결한다."""

import argparse
from datetime import datetime
import json
from pathlib import Path
import re

import httpx

from backend.db.connection import database_connection
from backend.db.exam_repository import get_certificate_by_code
from backend.db.repository import save_schedule
from backend.official_data import normalize_technical_schedules, parse_official_date
from backend.schemas import ScheduleInput
from research.probe_official_sources import inspect_page


ROOT = Path(__file__).resolve().parent


def read_dates(cell: str, allowed_counts: set[int]) -> list[str]:
    """공식 표의 날짜만 읽고 지원하지 않는 날짜 개수는 거절한다."""
    dates = re.findall(r"\d{4}\.\d{2}\.\d{2}", cell)
    if len(dates) not in allowed_counts:
        raise ValueError("공식 일정 표의 날짜 개수가 예상과 다릅니다.")
    return [value.replace(".", "") for value in dates]


def page_schedules(certificate: dict, metadata: dict, page: dict) -> list[ScheduleInput]:
    """공식 표를 기존 API 변환 함수의 입력으로 맞춘 뒤 날짜 검증을 재사용한다."""
    if certificate["qnet_code"] != "1431" or metadata["params"].get("jmCd") != "1431":
        raise ValueError("이번 공식 페이지 검증은 산업안전기사만 대상으로 합니다.")
    if certificate["name"] not in page["visible_text"]:
        raise ValueError("공식 페이지에서 선택한 종목을 확인할 수 없습니다.")
    source_url = str(httpx.URL(metadata["source_url"], params=metadata["params"]))
    retrieved_at = datetime.fromisoformat(metadata["retrieved_at"])
    schedules = []
    for table in page["tables"]:
        for row in table:
            if not row or not re.fullmatch(r"\d{4}년 정기 기사 \d+회", row[0]):
                continue
            if len(row) != 7:
                raise ValueError("공식 일정 표의 열 구조가 변경되었습니다.")
            item = {"jmfldnm": certificate["name"], "implplannm": row[0]}
            vacancies = {}
            for phase, prefix, offset in (("written", "doc", 1), ("practical", "prac", 4)):
                registration = read_dates(row[offset], {2, 4})
                exam = read_dates(row[offset + 1], {1, 2})
                result = read_dates(row[offset + 2], {1})
                item[prefix + "regstartdt"], item[prefix + "regenddt"] = registration[:2]
                item[prefix + "examstartdt"], item[prefix + "examenddt"] = exam[0], exam[-1]
                result_key = "docpassdt" if phase == "written" else "pracpassstartdt"
                item[result_key] = result[0]
                if len(registration) == 4:
                    vacancies[phase] = {
                        "vacancy_registration_start": parse_official_date(registration[2]),
                        "vacancy_registration_end": parse_official_date(registration[3]),
                    }
            normalized = normalize_technical_schedules(
                [item], certificate["id"], certificate["name"], source_url, retrieved_at,
            )
            for schedule in normalized:
                values = schedule.model_dump()
                values.update(vacancies.get(schedule.phase, {}))
                schedules.append(ScheduleInput(**values))
    keys = {(schedule.round_key, schedule.phase) for schedule in schedules}
    if len(schedules) != 6 or len(keys) != 6:
        raise ValueError("이번 검증 대상인 산업안전기사 정기 3회차·6단계를 확인할 수 없습니다.")
    return schedules


def main() -> None:
    """이번에 저장한 원본으로 검증하며 --apply로 일정 저장을 명시적으로 선택한다."""
    parser = argparse.ArgumentParser(description="산업안전기사 공식 페이지 일정 검증")
    parser.add_argument("--apply", action="store_true")
    options = parser.parse_args()
    metadata = json.loads((ROOT / "industrial_safety_page_metadata.json").read_text(encoding="utf-8"))
    if metadata.get("http_status") != 200:
        raise ValueError("정상 조회한 공식 페이지 원본이 필요합니다.")
    page = inspect_page((ROOT / metadata["response_file"]).read_text(encoding="utf-8"))
    with database_connection() as connection:
        certificate = get_certificate_by_code(connection, "1431")
    if certificate is None:
        raise ValueError("공식 종목 목록에서 산업안전기사를 찾을 수 없습니다.")
    schedules = page_schedules(certificate, metadata, page)
    if options.apply:
        with database_connection() as connection:
            for schedule in schedules:
                save_schedule(connection, schedule)
    report = {
        "qnet_code": "1431", "certificate_id": str(certificate["id"]),
        "source_type": "official_page", "fallback_used": True,
        "api_error": "timeout", "api_retry_count": 1,
        "automatic_fallback": False,
        "schedule_count": len(schedules), "database_applied": options.apply,
        "schedules": [schedule.model_dump(mode="json") for schedule in schedules],
    }
    (ROOT / "industrial_safety_page_schedule_result.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(f"공식 페이지 일정 검증: {len(schedules)}단계, DB 저장: {options.apply}")


if __name__ == "__main__":
    main()
