"""보관한 원본을 검증해 재사용 데이터와 누락 목록을 만든다. API·DB 호출은 없다."""

import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from backend.exam_schemas import ExamInformationInput
from backend.official_data import normalize_catalog, parse_official_date
from backend.schemas import ScheduleInput


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "research/preparation"


def read_json(relative: str) -> dict:
    """프로젝트에 보관한 JSON 원본을 읽는다."""
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def write_json(name: str, value: object) -> None:
    """한글·코드·원본 조회 시각을 유지해서 저장한다."""
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def prepare_professional_schedules(sources: list[dict]) -> tuple[list[dict], list[dict]]:
    """계열별 날짜를 검증한다. 1·2차를 필기·실기로 추정하거나 종목별로 복제하지 않는다."""
    schedules, issues = [], []
    seen = set()
    fields = {"registration_start": "examregstartdt", "registration_end": "examregenddt",
              "exam_start": "examstartdt", "exam_end": "examenddt",
              "result_date": "passstartdt", "result_display_end": "passenddt"}
    for source in sources:
        if source["kind"] != "schedules" or source["status"] != "fetched":
            continue
        for item in source["items"]:
            label = item.get("description", "")
            try:
                match = re.match(r"^(\d{4})년도", label)
                if not match:
                    raise ValueError("공식 회차명에서 연도를 확인할 수 없습니다.")
                dates = {field: parse_official_date(item.get(raw)) for field, raw in fields.items()}
                if any(value is None for value in dates.values()):
                    raise ValueError("접수·시험·발표 날짜가 누락되었습니다.")
                ordered = list(dates.values())
                if ordered != sorted(ordered):
                    raise ValueError("접수·시험·발표 날짜 순서가 맞지 않습니다.")
                if dates["exam_start"].year != int(match.group(1)):
                    raise ValueError("공식 회차 연도와 시험 시작 연도가 다릅니다.")
                key = (source["code"], label)
                if key in seen:
                    raise ValueError("같은 계열·회차명이 중복되었습니다.")
                seen.add(key)
                phase = "other"
                if re.search(r"1차$", label):
                    phase = "first"
                elif re.search(r"2차$", label):
                    phase = "second"
                schedules.append({"series_code": source["code"], "year": int(match.group(1)),
                                  "round_label": label, "phase": phase,
                                  **{field: value.isoformat() for field, value in dates.items()},
                                  "source_url": source["source_url"], "source_params": source["params"],
                                  "retrieved_at": source["retrieved_at"], "response_file": source["response_file"],
                                  "review_status": "unreviewed", "database_applied": False})
            except ValueError as error:
                issues.append({"series_code": source["code"], "round_label": label,
                               "message": str(error), "raw_item": item,
                               "response_file": source["response_file"]})
    return schedules, issues


def main() -> None:
    """목록·기술자격 모델·원본 파일을 검증한 다음 사전 준비 결과를 생성한다."""
    OUT.mkdir(parents=True, exist_ok=True)
    evidence = read_json("research/official_source_results.json")
    catalog_source = next(row for row in evidence["api_probes"] if row["label"] == "certificate_list")
    catalog_file = "research/" + catalog_source["response_file"]
    tree = ET.parse(ROOT / catalog_file)
    items = [{field.tag.lower(): (field.text or "").strip() for field in item}
             for item in tree.findall("./body/items/item")]
    validated = normalize_catalog(items, catalog_source["source_url"], datetime.fromisoformat(catalog_source["retrieved_at"]))
    catalog = []
    for certificate, item in zip(validated, items):
        catalog.append({**certificate.model_dump(mode="json"),
                        "series_code": item.get("seriescd") or None,
                        "series_name": item.get("seriesnm") or None,
                        "major_job_code": item.get("mdobligfldcd") or None,
                        "major_job_name": item.get("mdobligfldnm") or None,
                        "job_code": item.get("obligfldcd") or None,
                        "job_name": item.get("obligfldnm") or None})
    detail_report = read_json("research/all_technical_detail_applied.json")
    schedule_report = read_json("research/all_technical_schedule_applied.json")
    if not detail_report["completed"] or not schedule_report["completed"]:
        raise ValueError("기술자격 원본 보고서가 완료되지 않았습니다.")
    details = {row["qnet_code"]: row for row in detail_report["results"]}
    schedule_sources = {row["qnet_code"]: row for row in schedule_report["results"]}
    information, schedules, coverage, queue, documents = [], [], [], [], []
    seen_schedules = set()
    for certificate in catalog:
        code = certificate["qnet_code"]
        detail = details.get(code, {}).get("details", {})
        schedule = schedule_sources.get(code, {})
        info = detail.get("information")
        statuses = {field: "unavailable" for field in ("subjects", "pass_criteria", "fees")}
        if info:
            model = ExamInformationInput.model_validate(info)
            if str(model.certificate_id) != details[code]["certificate_id"]:
                raise ValueError(f"{code}: 상세정보의 종목 UUID가 다릅니다.")
            statuses = {field: getattr(model, field).status for field in statuses}
            if any(status != "unavailable" for status in statuses.values()):
                information.append({"qnet_code": code, "name": certificate["name"],
                                    "information": model.model_dump(mode="json")})
        for raw in schedule.get("schedules", []):
            model = ScheduleInput.model_validate(raw)
            if str(model.certificate_id) != schedule["certificate_id"]:
                raise ValueError(f"{code}: 일정의 종목 UUID가 다릅니다.")
            key = (str(model.certificate_id), model.round_key, model.phase)
            if key in seen_schedules:
                raise ValueError(f"{code}: 중복 일정입니다.")
            seen_schedules.add(key)
            schedules.append({"qnet_code": code, "name": certificate["name"], **model.model_dump(mode="json")})
        row = {"qnet_code": code, "name": certificate["name"], "category": certificate["category"],
               "series_code": certificate["series_code"], **{field + "_status": status for field, status in statuses.items()},
               "technical_schedule_rows": len(schedule.get("schedules", [])),
               "schedule_status": schedule.get("status", "not_collected"),
               "professional_detail_status": "not_applicable", "professional_series_status": "not_applicable"}
        coverage.append(row)
        if certificate["category"] == "T":
            missing = [field for field, status in statuses.items() if status != "available"]
            if missing:
                queue.append({"qnet_code": code, "name": certificate["name"], "task": "technical_detail_review",
                              "missing_fields": missing, "field_statuses": statuses,
                              "official_url": details.get(code, {}).get("official_url"),
                              "phases": info["subjects"]["phases"] if info else None,
                              "collection_error": detail.get("collection_error"),
                              "source_report": "research/all_technical_detail_applied.json",
                              "reason": "공식 원문·단계 충돌·누락을 확인해야 합니다. 미시행으로 단정하지 않습니다."})
            if not row["technical_schedule_rows"]:
                queue.append({"qnet_code": code, "name": certificate["name"], "task": "technical_schedule_review",
                              "collection_status": row["schedule_status"],
                              "reason": schedule.get("message") or schedule.get("on_demand_notice", {}).get("message") or "정기 일정이 비어 있습니다. 상시시험·공식 공고를 별도 확인합니다.",
                              "response_file": schedule.get("response_file")})
        response = detail.get("detail_response", {})
        for index, item in enumerate(response.get("items", [])):
            if item.get("contents", "").strip():
                documents.append({"document_id": f"T:{code}:{index}", "qnet_code": code,
                                  "certificate_name": certificate["name"], "section": item.get("infogb"),
                                  "content": item["contents"], "source_url": response["source_url"],
                                  "retrieved_at": response["retrieved_at"], "review_status": "unreviewed"})
    professional = read_json("research/preparation/professional_sources.json") if (OUT / "professional_sources.json").exists() else {"completed": False, "results": []}
    professional_details = {row["code"]: row for row in professional["results"] if row["kind"] == "details"}
    professional_series = {row["code"]: row for row in professional["results"] if row["kind"] == "schedules"}
    for certificate, row in zip(catalog, coverage):
        if certificate["category"] != "S":
            continue
        code = certificate["qnet_code"]
        detail = professional_details.get(code, {})
        series = professional_series.get(certificate["series_code"], {})
        row["professional_detail_status"] = detail.get("status", "not_collected")
        row["professional_series_status"] = series.get("status", "not_collected")
        row["subjects_status"] = row["pass_criteria_status"] = row["fees_status"] = "not_normalized"
        for index, item in enumerate(detail.get("items", [])):
            if item.get("contents", "").strip():
                documents.append({"document_id": f"S:{code}:{index}", "qnet_code": code,
                                  "certificate_name": certificate["name"], "reported_name": item.get("jmfldnm"),
                                  "section": item.get("infogb"), "content": item["contents"],
                                  "source_url": detail["source_url"], "source_params": detail["params"],
                                  "retrieved_at": detail["retrieved_at"], "response_file": detail["response_file"],
                                  "review_status": "unreviewed"})
        queue.append({"qnet_code": code, "name": certificate["name"], "task": "professional_mapping_review",
                      "series_code": certificate["series_code"], "detail_status": row["professional_detail_status"],
                      "series_status": row["professional_series_status"],
                      "reason": "원문 최신성·종목명·단계·과목·기준·응시료를 검토한 뒤 기존 모델·DB 연결 범위를 정합니다."})
    professional_schedules, issues = prepare_professional_schedules(professional["results"])
    inventory = []
    for certificate in catalog:
        if certificate["category"] != "S":
            continue
        detail = professional_details.get(certificate["qnet_code"], {})
        names = sorted({item.get("jmfldnm", "") for item in detail.get("items", [])})
        inventory.append({"qnet_code": certificate["qnet_code"], "name": certificate["name"],
                          "series_code": certificate["series_code"], "series_name": certificate["series_name"],
                          "collection_status": detail.get("status", "not_collected"),
                          "section_labels": [item.get("infogb") for item in detail.get("items", [])],
                          "reported_names": names, "exact_name_match": bool(names) and names == [certificate["name"]],
                          "response_file": detail.get("response_file"), "review_status": "unreviewed"})
    source_paths = {"research/official_source_results.json", catalog_file,
                    "research/all_technical_detail_applied.json", "research/all_technical_schedule_applied.json",
                    "research/technical_2026_annual_notice.json", "research/technical_2026_annual_notice.pdf"}
    for source in schedule_sources.values():
        if source.get("response_file"):
            source_paths.add(source["response_file"])
    for source in professional["results"]:
        for attempt in source["attempts"]:
            if attempt.get("response_file"):
                source_paths.add("research/" + attempt["response_file"])
    if (OUT / "professional_sources.json").exists():
        source_paths.add("research/preparation/professional_sources.json")
    if (OUT / "professional_fallback_sources.json").exists():
        fallback = read_json("research/preparation/professional_fallback_sources.json")
        source_paths.add("research/preparation/professional_fallback_sources.json")
        for row in fallback["results"]:
            if row.get("response_file"):
                source_paths.add("research/" + row["response_file"])
    manifest = []
    for relative in sorted(source_paths):
        path = ROOT / relative
        if not path.is_file():
            raise ValueError(f"원본 파일 누락: {relative}")
        manifest.append({"path": relative, "bytes": path.stat().st_size,
                         "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    write_json("catalog.json", catalog)
    write_json("technical_exam_information.json", information)
    write_json("technical_schedules.json", schedules)
    write_json("professional_series_schedules.json", professional_schedules)
    write_json("professional_schedule_issues.json", issues)
    write_json("professional_inventory.json", inventory)
    write_json("work_queue.json", queue)
    write_json("source_manifest.json", manifest)
    with (OUT / "coverage.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(coverage[0]))
        writer.writeheader()
        writer.writerows(coverage)
    with (OUT / "official_documents.jsonl").open("w", encoding="utf-8") as file:
        for document in documents:
            file.write(json.dumps(document, ensure_ascii=False) + "\n")
    result = {"prepared_at": datetime.now(timezone.utc).isoformat(), "database_checked": False,
              "professional_collection_completed": professional["completed"],
              "catalog_count": len(catalog), "technical_information_count": len(information),
              "technical_schedule_count": len(schedules), "technical_scheduled_certificates": len({row["qnet_code"] for row in schedules}),
              "professional_detail_statuses": {status: sum(row.get("status") == status for row in professional_details.values()) for status in ("fetched", "empty", "failed")},
              "professional_series_statuses": {status: sum(row.get("status") == status for row in professional_series.values()) for status in ("fetched", "empty", "failed")},
              "professional_series_schedule_rows": len(professional_schedules), "professional_schedule_issues": len(issues),
              "official_document_count": len(documents), "source_file_count": len(manifest),
              "technical_detail_review_count": sum(row["task"] == "technical_detail_review" for row in queue),
              "technical_schedule_review_count": sum(row["task"] == "technical_schedule_review" for row in queue),
              "notes": ["기술자격은 과거 저장 결과를 현재 입력 모델로 재검증했습니다. 현재 Render DB 검증 결과가 아닙니다.",
                        "전문자격은 공식 원본과 계열별 후보 일정입니다. 상세 정규화·종목별 연결·DB 반영은 하지 않았습니다.",
                        "RAG 문서는 원문 준비 단계이며 최신성 검토·청킹·임베딩·검색 구현은 별도 결정이 필요합니다."]}
    write_json("validation_report.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
