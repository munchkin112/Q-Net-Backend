"""여러 기술자격을 순서대로 수집하며 종목별 상세정보·일정 결과를 따로 기록한다."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time

import psycopg

from backend.db.connection import database_connection
from backend.db.exam_repository import get_certificate_by_code, save_exam_information
from backend.db.repository import save_schedule
from backend.exam_data import normalize_exam_information
from backend.official_api import (
    OfficialAPIError, fetch_exam_information, fetch_exam_fees, fetch_technical_schedules,
)
from backend.official_data import normalize_technical_schedules


PROJECT_ROOT = Path(__file__).resolve().parents[1]
# 공식 목록에서 확인한 기사 5개, 산업기사 2개, 기능사 3개다.
SAMPLE_CODES = ["1320", "1431", "1150", "1630", "1250", "2290", "2140", "7910", "7780", "6892"]


def error_result(error: Exception, step: str) -> dict:
    """오류 원인은 기록하되 DB 연결 URL이나 인증정보는 기록하지 않는다."""
    result = {"status": "failed", "step": step, "retry_count": 0}
    if isinstance(error, OfficialAPIError):
        result.update(error_type=error.code, message=str(error), retry_count=error.retry_count)
    elif isinstance(error, psycopg.Error):
        result.update(error_type="database_error", message="DB 연결·저장 실패. 해당 작업의 변경은 취소됩니다.")
    elif isinstance(error, RuntimeError):
        result.update(error_type="configuration_error", message="DB 연결 설정을 확인해주세요.")
    else:
        result.update(error_type="validation_error", message=str(error)[:800])
    return result


def collect_details(certificate: dict, apply: bool, interval: float) -> dict:
    """기존 원문 변환·저장 함수를 재사용하고 일부 누락 시 기존 자료를 유지한다."""
    step = "detail_api"
    evidence = {}
    try:
        detail = fetch_exam_information(certificate["qnet_code"])
        evidence["detail_response"] = {**detail, "retrieved_at": detail["retrieved_at"].isoformat()}
        time.sleep(interval)
        step = "fee_api"
        fees = fetch_exam_fees(certificate["qnet_code"])
        evidence["fee_response"] = {**fees, "retrieved_at": fees["retrieved_at"].isoformat()}
        step = "normalize"
        information = normalize_exam_information(certificate["id"], certificate["name"], detail, fees)
        field_statuses = {}
        for field in ("subjects", "pass_criteria", "fees"):
            field_statuses[field] = getattr(information, field).status
        result = {
            **evidence,
            "status": "validated", "field_statuses": field_statuses,
            "detail_retry_count": detail["retry_count"], "fee_retry_count": fees["retry_count"],
            "information": information.model_dump(mode="json"),
            # 원문 구조를 다시 검토할 수 있게 응답 item도 보관한다. 비밀키는 포함하지 않는다.
            "detail_items": detail["items"], "fee_items": fees["items"],
        }
        if any(status != "available" for status in field_statuses.values()):
            result.update(status="incomplete", error_type="missing_information",
                          message="필기·실기 과목·기준·수수료를 모두 확인하지 못해 저장하지 않았습니다.")
            return result
        if apply:
            step = "database_save"
            with database_connection() as connection:
                saved = save_exam_information(connection, information)
            same_times = []
            for field in ("subjects", "pass_criteria", "fees"):
                stored_time = datetime.fromisoformat(saved[field]["retrieved_at"])
                same_times.append(stored_time == getattr(information, field).retrieved_at)
            result["status"] = "saved" if all(same_times) else "unchanged"
        return result
    except (OfficialAPIError, ValueError, psycopg.Error, RuntimeError) as error:
        return {**evidence, **error_result(error, step)}


def collect_schedules(certificate: dict, apply: bool) -> dict:
    """일정 실패·정상 빈 목록을 구분하고 해당 종목의 일정만 하나의 트랜잭션으로 저장한다."""
    step = "schedule_api"
    evidence = {}
    try:
        response = fetch_technical_schedules(certificate["qnet_code"])
        evidence["schedule_response"] = {**response, "retrieved_at": response["retrieved_at"].isoformat()}
        step = "normalize"
        schedules = normalize_technical_schedules(
            response["items"], certificate["id"], certificate["name"],
            response["source_url"], response["retrieved_at"],
        )
        result = {
            **evidence,
            "status": "validated" if schedules else "empty", "schedule_count": len(schedules),
            "retry_count": response["retry_count"], "source_url": response["source_url"],
            "retrieved_at": response["retrieved_at"].isoformat(),
            "schedules": [schedule.model_dump(mode="json") for schedule in schedules],
        }
        if not schedules:
            result["message"] = "이 API에서 반환된 일정이 없습니다. 기존 일정을 유지하며 상시시험 등은 별도 확인해야 합니다."
        elif apply:
            step = "database_save"
            accepted = 0
            with database_connection() as connection:
                for schedule in schedules:
                    saved = save_schedule(connection, schedule, preserve_known=True)
                    if saved["last_synced_at"] == schedule.last_synced_at:
                        accepted += 1
            result["accepted_count"] = accepted
            result["status"] = "saved" if accepted == len(schedules) else "unchanged"
        return result
    except (OfficialAPIError, ValueError, psycopg.Error, RuntimeError) as error:
        return {**evidence, **error_result(error, step)}


def write_report(path: Path, report: dict) -> None:
    """완료된 종목마다 진행 결과를 저장한다. 도중 종료되어도 앞선 결과를 유지한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    # Windows에서 백신 검사나 파일 읽기가 잠깐 겹치면 교체를 짧게 재시도한다.
    for attempt in range(5):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.2)


def batch_summary(rows: list[dict]) -> dict:
    """상세정보와 일정의 상태별 개수를 각각 집계한다."""
    result = {"details": {}, "schedules": {}}
    for row in rows:
        for field in result:
            status = row[field]["status"]
            result[field][status] = result[field].get(status, 0) + 1
    return result


def run_batch(codes: list[str], apply: bool, only: str, interval: float, output: Path,
              catalog: dict | None = None, resume: bool = False) -> dict:
    """중복 코드는 한 번 처리하고, 각 작업 실패 후에도 다음 작업과 종목을 계속한다."""
    codes = list(dict.fromkeys(codes))
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(), "mode": "live",
        "apply_requested": apply, "requested_codes": codes, "only": only,
        "interval_seconds": interval, "completed": False, "results": [],
    }
    if resume and output.exists():
        previous = json.loads(output.read_text(encoding="utf-8"))
        if previous["requested_codes"] != codes or previous["only"] != only or previous["apply_requested"] != apply:
            raise ValueError("이어받을 결과의 종목·작업·저장 모드가 현재 옵션과 다릅니다.")
        report = previous
        report["completed"] = False
    completed_codes = {row["qnet_code"] for row in report["results"]}
    write_report(output, report)
    for index, code in enumerate(codes, start=1):
        if code in completed_codes:
            continue
        row = {"qnet_code": code, "details": {"status": "not_requested"}, "schedules": {"status": "not_requested"}}
        try:
            if catalog is None:
                with database_connection() as connection:
                    certificate = get_certificate_by_code(connection, code)
            else:
                certificate = catalog.get(code)
            if certificate is None:
                raise ValueError("DB의 공식 목록에 없는 종목 코드입니다.")
            if certificate["category"] != "T":
                raise ValueError("현재 일괄 수집은 기술자격만 지원합니다.")
            row.update(name=certificate["name"], certificate_id=str(certificate["id"]),
                       official_url="https://www.q-net.or.kr/crf005.do?id=crf00503&jmCd=" + code)
            if only in {"details", "both"}:
                row["details"] = collect_details(certificate, apply, interval)
            if only in {"schedules", "both"}:
                time.sleep(interval)
                row["schedules"] = collect_schedules(certificate, apply)
        except (ValueError, psycopg.Error, RuntimeError) as error:
            for field in ("details", "schedules"):
                if only == "both" or only == field:
                    row[field] = error_result(error, "certificate_lookup")
        report["results"].append(row)
        report["summary"] = batch_summary(report["results"])
        write_report(output, report)
        print(f"[{index}/{len(codes)}] {row.get('name', code)}: 상세={row['details']['status']}, 일정={row['schedules']['status']}", flush=True)
        if index < len(codes):
            time.sleep(interval)
    report["completed"] = True
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    write_report(output, report)
    return report


def load_technical_catalog() -> dict:
    """기술자격 목록을 한 번 읽어 종목마다 같은 목록 조회를 반복하지 않는다."""
    with database_connection() as connection:
        rows = connection.execute("SELECT * FROM certificates WHERE category = 'T' ORDER BY qnet_code").fetchall()
    return {row["qnet_code"]: row for row in rows}


def reprocess_details(source: Path, apply: bool, output: Path, allow_partial: bool = False) -> dict:
    """저장한 공식 응답을 다시 검증한다. 외부 재호출 없이 원본 조회 시각을 유지한다."""
    previous = json.loads(source.read_text(encoding="utf-8"))
    catalog = load_technical_catalog()
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(), "mode": "saved_responses",
        "source_report": str(source), "apply_requested": apply, "only": "details",
        "requested_codes": previous["requested_codes"], "completed": False, "results": [],
        "allow_partial": allow_partial,
    }
    # 수백 건 저장에서 연결을 반복해서 만들지 않는다. INSERT 한 건마다 독립적으로 확정한다.
    with database_connection() as connection:
        connection.autocommit = True
        for index, original in enumerate(previous["results"], start=1):
            row = {**original, "schedules": {"status": "not_requested"}}
            old = original["details"]
            if "detail_response" not in old and "fee_response" not in old:
                row["details"] = {**old, "message": "공식 원본을 확보하지 못했습니다. 이전 호출 결과를 유지합니다."}
            else:
                step = "normalize"
                try:
                    certificate = catalog.get(row["qnet_code"])
                    if certificate is None or str(certificate["id"]) != row["certificate_id"]:
                        raise ValueError("원본 조회 당시 종목과 현재 DB 종목이 일치하지 않습니다.")
                    missing_response = {"items": [], "source_url": None, "retrieved_at": None}
                    detail = dict(old.get("detail_response", missing_response))
                    fees = dict(old.get("fee_response", missing_response))
                    for response in (detail, fees):
                        if response["retrieved_at"] is not None:
                            response["retrieved_at"] = datetime.fromisoformat(response["retrieved_at"])
                    information = normalize_exam_information(certificate["id"], certificate["name"], detail, fees)
                    statuses = {field: getattr(information, field).status for field in ("subjects", "pass_criteria", "fees")}
                    result = {**old, "information": information.model_dump(mode="json"), "field_statuses": statuses}
                    if old.get("status") == "failed":
                        result["collection_error"] = {key: old[key] for key in ("step", "error_type", "message", "retry_count") if key in old}
                    incomplete = any(status != "available" for status in statuses.values())
                    has_information = any(status != "unavailable" for status in statuses.values())
                    if incomplete and not (allow_partial and has_information):
                        result.update(status="incomplete", error_type="missing_information")
                    elif apply:
                        step = "database_save"
                        saved = save_exam_information(connection, information, allow_partial=allow_partial)
                        matches = [(datetime.fromisoformat(saved[field]["retrieved_at"]) if saved[field]["retrieved_at"] else None) == getattr(information, field).retrieved_at
                                   for field in ("subjects", "pass_criteria", "fees")]
                        result["status"] = ("saved_partial" if incomplete else "saved") if all(matches) else "unchanged"
                        result.pop("error_type", None)
                        result.pop("message", None)
                    else:
                        result["status"] = "validated_partial" if incomplete else "validated"
                        result.pop("error_type", None)
                        result.pop("message", None)
                    row["details"] = result
                except (ValueError, psycopg.Error, RuntimeError) as error:
                    row["details"] = {**old, **error_result(error, step)}
            report["results"].append(row)
            report["summary"] = batch_summary(report["results"])
            write_report(output, report)
            print(f"[{index}/{len(previous['results'])}] {row.get('name', row['qnet_code'])}: {row['details']['status']}", flush=True)
    report["completed"] = previous["completed"] and len(report["results"]) == len(report["requested_codes"])
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    write_report(output, report)
    return report


def main() -> None:
    """기본 표본 10개를 검증하며 --apply를 지정해야 DB에 저장한다."""
    parser = argparse.ArgumentParser(description="기술자격 상세정보·일정 일괄 수집")
    parser.add_argument("--codes", nargs="+", default=SAMPLE_CODES, help="공식 종목 코드 목록")
    parser.add_argument("--all-technical", action="store_true", help="DB의 기술자격 전체 선택")
    parser.add_argument("--resume", action="store_true", help="같은 결과 파일의 완료된 종목을 건너뛰고 계속")
    parser.add_argument("--from-report", type=Path, help="공식 원본이 있는 결과 파일을 외부 재호출 없이 재처리")
    parser.add_argument("--allow-partial", action="store_true", help="원본 재처리 시 확인한 일부 정보도 저장. 미확인은 null 유지")
    parser.add_argument("--only", choices=["details", "schedules", "both"], default="both")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--interval", type=float, default=1.0, help="외부 호출 사이 대기 시간(초)")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "research" / "batch_sync_result.json")
    options = parser.parse_args()
    if not 0.1 <= options.interval <= 30:
        parser.error("요청 간격은 0.1~30초로 지정해주세요.")
    if options.from_report:
        if options.from_report.resolve() == options.output.resolve():
            parser.error("원본 결과 파일과 새 출력 파일은 다른 경로로 지정해주세요.")
        report = reprocess_details(options.from_report, options.apply, options.output, options.allow_partial)
    else:
        catalog = load_technical_catalog() if options.all_technical else None
        codes = list(catalog) if catalog is not None else options.codes
        report = run_batch(codes, options.apply, options.only, options.interval, options.output, catalog, options.resume)
    print(json.dumps(report["summary"], ensure_ascii=False))
    # 정상 빈 일정은 오류와 구분한다. 일부 실패·누락은 종료 코드에도 표시한다.
    bad_states = {"failed", "incomplete"}
    if any(row[field]["status"] in bad_states for row in report["results"] for field in ("details", "schedules")):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
