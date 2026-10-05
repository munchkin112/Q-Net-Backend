"""Resolve incomplete probes and normalize verified public sample data."""

import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date, datetime

from probe_official_sources import API_SOURCES, KST, ROOT, fetch, inspect_page


def xml_summary(text):
    """Check application result code and actual items, not HTTP status alone."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return {"xml": False}
    items = [{node.tag: node.text or "" for node in item} for item in root.findall("./body/items/item")]
    return {"result_code": root.findtext("./header/resultCode"), "result_message": root.findtext("./header/resultMsg"), "item_count": len(items), "sample_items": items[:2], "total_count": root.findtext("./body/totalCount")}


def normalize_page(record, text):
    """Preserve main/vacancy registration and written/practical date ranges."""
    page = inspect_page(text)
    phases = []
    today = date(2026, 10, 5)
    for table in page["tables"]:
        for row in table:
            if len(row) != 7 or not re.match(r"2026년", row[0]):
                continue
            for label, reg_index, exam_index, pass_index in (("written", 1, 2, 3), ("practical", 4, 5, 6)):
                registration = re.findall(r"\d{4}\.\d{2}\.\d{2}", row[reg_index])
                exams = re.findall(r"\d{4}\.\d{2}\.\d{2}", row[exam_index])
                passes = re.findall(r"\d{4}\.\d{2}\.\d{2}", row[pass_index])
                if len(registration) < 2 or not exams or not passes:
                    phases.append({"round": row[0], "phase": label, "validation_errors": ["missing_dates"], "raw_cells": row})
                    continue
                def convert(value):
                    return date.fromisoformat(value.replace(".", "-"))
                reg_start, reg_end = map(convert, registration[:2])
                exam_start, exam_end = convert(exams[0]), convert(exams[-1])
                pass_date = convert(passes[0])
                errors = [] if reg_start <= reg_end <= exam_start <= exam_end <= pass_date else ["schedule_inconsistency"]
                phase = {"round": row[0], "phase": label, "registration_start": reg_start.isoformat(), "registration_end": reg_end.isoformat(), "exam_start": exam_start.isoformat(), "exam_end": exam_end.isoformat(), "result_date": pass_date.isoformat(), "validation_errors": errors, "registration_closed": reg_end < today, "exam_period_completed": exam_end < today, "days_to_exam_period_start": (exam_start - today).days, "d_day_basis": "published_exam_period_start_not_personal_exam_date"}
                if len(registration) > 2:
                    phase["vacancy_registration_dates"] = [convert(value).isoformat() for value in registration[2:]]
                phases.append(phase)
    fee_table = next((table for table in page["tables"] if table and table[0] == ["필기", "실기"] and len(table) > 1), None)
    acquisition = page["visible_text"].split("취득방법", 1)[-1]
    sections = {}
    for label in ("관련학과", "시험과목", "검정방법", "합격기준"):
        match = re.search(label + r"\s*:?\s*([\s\S]*?)(?=[①②③④⑤⑥]|\n출제기준|$)", acquisition)
        if match:
            sections[label] = match.group(1).strip()[:1500]
    return {"source_url": record["source_url"], "source_params": record.get("params", {}), "retrieved_at": record["retrieved_at"], "name_confirmed": record.get("expected_certificate", "") in page["visible_text"], "schedule_phase_count": len(phases), "schedule_phases": phases, "exam_fee": {"written": fee_table[1][0], "practical": fee_table[1][1]} if fee_table else None, "acquisition_method_text": acquisition.strip(), "sections": sections, "attachment_link_attributes": [link for link in page["links"] if "file" in json.dumps(link).lower() or "pdf" in json.dumps(link).lower() or "down" in json.dumps(link).lower()]}


def main():
    previous = json.loads((ROOT / "official_source_results.json").read_text(encoding="utf-8"))
    summary = {"assessment_date": "2026-10-05", "run_at": datetime.now(KST).isoformat(), "api_results": [], "supplemental_probes": [], "certificates": []}
    for record in previous["api_probes"]:
        body_file = record.get("response_file")
        body = (ROOT / body_file).read_text(encoding="utf-8") if body_file else ""
        summary["api_results"].append({"label": record["label"], "http_status": record.get("http_status"), "error": record.get("error"), "auth": record["auth"], "documentation_url": record["documentation_url"], **xml_summary(body)})
    certificate_xml = ET.fromstring((ROOT / "responses/certificate_list.txt").read_text(encoding="utf-8"))
    certificates = [{child.tag: child.text or "" for child in item} for item in certificate_xml.findall("./body/items/item")]
    summary["catalog"] = {"count": len(certificates), "categories": dict(Counter(item.get("qualgbcd") for item in certificates)), "unique_codes": len(set(item["jmcd"] for item in certificates)), "selected": [item for item in certificates if item["jmfldnm"] in ("정보처리기사", "산업안전기사", "한식조리기능사", "공인중개사")]}
    followups = [
        ("certificate_1431", "https://www.q-net.or.kr/crf005.do", {"id": "crf00503s02", "jmCd": "1431", "jmInfoDivCcd": "B0"}),
        ("engineer_eligibility_public", "https://www.q-net.or.kr/crf006.do", {"id": "crf00603s10", "gSite": "Q", "gradeType": "30"}),
        ("craftsman_eligibility_public", "https://www.q-net.or.kr/crf006.do", {"id": "crf00603s10", "gSite": "Q", "gradeType": "40"}),
        ("hansik_full_public", "https://www.q-net.or.kr/crf005.do", {"id": "crf00503", "gSite": "Q", "jmCd": "7910"}),
        ("eligibility_retry", API_SOURCES[3][2], API_SOURCES[3][4]),
        ("exam_sites_retry", API_SOURCES[4][2], API_SOURCES[4][4]),
        ("professional_schedule_series08", API_SOURCES[6][2], {"seriesCd": "08"}),
        ("legacy_technical_schedule", "http://openapi.q-net.or.kr/api/service/rest/InquiryTestInformationNTQSVC/getPEList", {}),
        ("technical_api_documentation", "https://www.data.go.kr/data/15003029/openapi.do", {}),
    ]
    for label, base, params in followups:
        record, text = fetch(label, base, params)
        record.update(xml_summary(text))
        if record.get("http_status") == 200 and "html" in record.get("content_type", ""):
            record["extracted"] = inspect_page(text)
        if label == "certificate_1431":
            record["expected_certificate"] = "산업안전기사"
            summary["certificates"].append(normalize_page(record, text))
        if label == "technical_api_documentation":
            record["operation_options"] = re.findall(r"<option[^>]*value=[\"']([^\"']*)[\"'][^>]*>(.*?)</option>", text, re.S)
            record["api_paths"] = sorted(set(re.findall(r"InquiryTestInformationNTQSVC/\w+", text)))
        summary["supplemental_probes"].append(record)
        print(label, record.get("http_status", record.get("error")), record.get("result_code", ""), record.get("item_count", ""), flush=True)
    for record in previous["public_pages"]:
        if record["label"] in ("certificate_1320", "certificate_7910"):
            summary["certificates"].append(normalize_page(record, (ROOT / record["response_file"]).read_text(encoding="utf-8")))
    (ROOT / "official_source_analysis.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Analysis saved.", flush=True)


if __name__ == "__main__":
    main()
