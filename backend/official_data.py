"""공식 종목·일정 데이터를 현재 DB 입력 구조로 변환한다."""

from datetime import date, datetime
import re
from uuid import UUID

from backend.schemas import CertificateInput, ScheduleInput


def parse_official_date(value: str | None) -> date | None:
    """YYYYMMDD 날짜를 변환하며 빈 값은 미확인으로 남긴다."""
    if not value:
        return None
    if not re.fullmatch(r"\d{8}", value):
        raise ValueError(f"공식 날짜 형식 오류: {value}")
    return datetime.strptime(value, "%Y%m%d").date()


def normalize_catalog(items: list[dict], source_url: str, retrieved_at: datetime) -> list[CertificateInput]:
    """공식 코드의 선행 0을 보존하고, 필수 값·중복 종목을 검사한다."""
    certificates = []
    seen_codes = set()
    for item in items:
        code = item.get("jmcd", "")
        if code in seen_codes:
            raise ValueError(f"공식 목록에 중복 종목 코드가 있습니다: {code}")
        certificate = CertificateInput(
            qnet_code=code,
            name=item.get("jmfldnm", ""),
            category=item.get("qualgbcd", ""),
            source_url=source_url,
            last_synced_at=retrieved_at,
        )
        seen_codes.add(code)
        certificates.append(certificate)
    return certificates


def normalize_technical_schedules(
    items: list[dict], certificate_id: UUID, expected_name: str,
    source_url: str, retrieved_at: datetime,
) -> list[ScheduleInput]:
    """한 공식 회차를 필기·실기·기술사 면접 행으로 나누고 날짜 순서를 검증한다."""
    schedules = []
    seen_keys = set()
    for item in items:
        if item.get("jmfldnm") != expected_name:
            raise ValueError("선택한 자격증과 공식 일정의 종목명이 다릅니다.")
        plan_name = " ".join(item.get("implplannm", "").split())
        year_match = re.match(r"^(\d{4})년", plan_name)
        if not year_match:
            raise ValueError("공식 시행계획명에서 연도를 확인할 수 없습니다.")
        # 회차 숫자만 쓰지 않고 공식 시행계획명 전체를 보존한다.
        round_key = "qnet-technical:" + plan_name
        second_phase = 'interview' if '정기 기술사' in plan_name else 'practical'
        for phase, prefix in (("written", "doc"), (second_phase, "prac")):
            values = {
                "registration_start": parse_official_date(item.get(prefix + "regstartdt")),
                "registration_end": parse_official_date(item.get(prefix + "regenddt")),
                "exam_start": parse_official_date(item.get(prefix + "examstartdt")),
                "exam_end": parse_official_date(item.get(prefix + "examenddt")),
            }
            if phase == "written":
                values["result_date"] = parse_official_date(item.get("docpassdt"))
                values["result_display_end"] = None
            else:
                values["result_date"] = parse_official_date(item.get("pracpassstartdt"))
                values["result_display_end"] = parse_official_date(item.get("pracpassenddt"))
            if not any(values.values()):
                continue
            key = (round_key, phase)
            if key in seen_keys:
                raise ValueError("같은 시행계획·시험 단계가 중복되어 있습니다.")
            schedule = ScheduleInput(
                certificate_id=certificate_id, year=int(year_match.group(1)),
                round_key=round_key, round_label=plan_name, phase=phase,
                source_url=source_url, last_synced_at=retrieved_at, **values,
            )
            seen_keys.add(key)
            schedules.append(schedule)
    return schedules
