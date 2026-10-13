"""Read official operation documentation and finish previously untested coverage."""

import argparse
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter

from probe_official_sources import ROOT, fetch, inspect_page
from probe_supplement import xml_summary


def execute_documented_operations():
    """Probe only URLs obtained from official per-operation documentation."""
    metadata = json.loads((ROOT / "official_remaining_results.json").read_text(encoding="utf-8"))
    results = []
    for operation in metadata["operation_documentation"]:
        urls = operation["endpoint_urls"]
        if len(urls) != 1:
            continue
        cases = [None] if operation["operation_id"] in ("7196", "7197") else ["1320", "1431", "7910"]
        for code in cases:
            label = "api_operation_" + operation["operation_id"] + ("_" + code if code else "")
            record, text = fetch(label, urls[0], {"jmCd": code} if code else {})
            record.update(xml_summary(text))
            if record.get("result_code") == "00":
                record["items"] = [{child.tag: child.text or "" for child in item} for item in ET.fromstring(text).findall("./body/items/item")]
            results.append(record)
            print(label, record.get("http_status", record.get("error")), record.get("result_code"), record.get("item_count"), flush=True)
    for code in ("1431", "7910"):
        record, text = fetch("api_information_" + code, "http://openapi.q-net.or.kr/api/service/rest/InquiryInformationTradeNTQSVC/getList", {"jmCd": code})
        record.update(xml_summary(text))
        if record.get("result_code") == "00":
            record["items"] = [{child.tag: child.text or "" for child in item} for item in ET.fromstring(text).findall("./body/items/item")]
        results.append(record)
        print(record["label"], record.get("result_code"), record.get("item_count"), flush=True)
    (ROOT / "official_operation_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


def retry_incomplete():
    """Retry each timed-out operation at most once; retain both attempts."""
    path = ROOT / "official_operation_results.json"
    records = json.loads(path.read_text(encoding="utf-8"))
    for record in records:
        if not record.get("error") or record.get("retry_attempt"):
            continue
        retry, text = fetch(record["label"] + "_retry", record["source_url"], record["params"])
        retry.update(xml_summary(text))
        if retry.get("result_code") == "00":
            retry["items"] = [{child.tag: child.text or "" for child in item} for item in ET.fromstring(text).findall("./body/items/item")]
        record["retry_attempt"] = retry
        print(retry["label"], retry.get("http_status", retry.get("error")), retry.get("result_code"), retry.get("item_count"), flush=True)
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def summarize():
    """Compare independent official sources and save a compact capability summary."""
    analysis = json.loads((ROOT / "official_source_analysis.json").read_text(encoding="utf-8"))
    remaining = json.loads((ROOT / "official_remaining_results.json").read_text(encoding="utf-8"))
    operations = json.loads((ROOT / "official_operation_results.json").read_text(encoding="utf-8"))
    pages = {page["source_params"]["jmCd"]: page for page in analysis["certificates"]}
    names = {item["jmcd"]: item["jmfldnm"] for item in analysis["catalog"]["selected"]}
    final = {"assessment_date": "2026-10-05", "catalog": analysis["catalog"], "eligibility_item_count": remaining["probes"][0]["item_count"], "grade_counts": remaining["probes"][0]["grade_counts"], "fee_comparisons": [], "schedule_comparisons": [], "operation_results": [], "limitations": ["인증 없는 성공은 이번 조사에서 관찰한 결과이며, 공식 문서는 인증키를 필수로 요구한다.", "종목 목록 613건 전체의 상세정보·최신성·일정은 검증하지 않았다.", "시험장소 API는 최초 호출과 1회 재시도 모두 20초 시간초과였다.", "응시요건 원문 확보는 개인별 최종 응시자격 판정·증빙심사 성공을 뜻하지 않는다.", "상시시험 일정 및 개인별 확정 시험일·배정 시험장은 추가 연동 검증이 필요하다.", "RAG 검색·PDF 본문 추출·Google OAuth·Calendar 이벤트 생성은 이번 조사 범위에서 실행하지 않았다."], "discarded_initial_probe": {"label": "certificate_1470", "reason": "처음 사용한 산업안전기사 코드가 실제 공식 목록과 달랐으며, 공식 목록의 1431로 수정해 재검증했다."}}
    for original in operations:
        record = original.get("retry_attempt", original)
        final["operation_results"].append({"label": original["label"], "result_code": record.get("result_code"), "http_status": record.get("http_status"), "item_count": record.get("item_count"), "error": record.get("error"), "retry_used": "retry_attempt" in original, "source_url": record["source_url"], "params": record["params"]})
        if record.get("result_code") != "00":
            continue
        code = record["params"].get("jmCd")
        if "7198" in original["label"]:
            api_values = re.findall(r"차\s*:\s*(\d+)", record["items"][0]["contents"])
            fees = pages[code]["exam_fee"]
            page_values = [re.sub(r"\D", "", fees[key]) for key in ("written", "practical")]
            final["fee_comparisons"].append({"certificate": names[code], "code": code, "name_matches": record["items"][0]["jmfldnm"] == names[code], "api_values": api_values, "page_values": page_values, "matches": api_values == page_values})
        elif "7199" in original["label"]:
            comparisons = []
            for item in record["items"]:
                for phase in pages[code]["schedule_phases"]:
                    if item.get("implplannm") != phase["round"]:
                        continue
                    prefix = "doc" if phase["phase"] == "written" else "prac"
                    field_map = {"registration_start": prefix + "regstartdt", "registration_end": prefix + "regenddt", "exam_start": prefix + "examstartdt", "exam_end": prefix + "examenddt", "result_date": "docpassdt" if prefix == "doc" else "pracpassstartdt"}
                    matches = {}
                    for field, api_field in field_map.items():
                        value = item.get(api_field, "")
                        iso = value[:4] + "-" + value[4:6] + "-" + value[6:8] if re.fullmatch(r"\d{8}", value) else value
                        matches[field] = iso == phase[field]
                    comparisons.append({"round": phase["round"], "phase": phase["phase"], "name_matches": item.get("jmfldnm") == names[code], "field_matches": matches})
            final["schedule_comparisons"].append({"certificate": names[code], "item_count": record["item_count"], "compared_phases": len(comparisons), "all_compared_fields_match": bool(comparisons) and all(all(c["field_matches"].values()) and c["name_matches"] for c in comparisons), "checks": comparisons})
    phases = [phase for page in pages.values() for phase in page["schedule_phases"]]
    final["date_validation"] = {"checked_phases": len(phases), "errors": [phase for phase in phases if phase["validation_errors"]], "assessment_date": "2026-10-05"}
    output = ROOT / "feasibility_summary.json"
    output.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"catalog_count": final["catalog"]["count"], "eligibility_count": final["eligibility_item_count"], "fees": final["fee_comparisons"], "schedule_checks": [{k: v for k, v in entry.items() if k != "checks"} for entry in final["schedule_comparisons"]], "date_validation": final["date_validation"], "saved": str(output)}, ensure_ascii=True, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--retry-incomplete", action="store_true")
    parser.add_argument("--summarize", action="store_true")
    options = parser.parse_args()
    if options.execute:
        execute_documented_operations()
        return
    if options.retry_incomplete:
        retry_incomplete()
        return
    if options.summarize:
        summarize()
        return
    results = {"operation_documentation": [], "probes": []}
    document = (ROOT / "responses/technical_api_documentation.html").read_text(encoding="utf-8")
    detail = re.search(r'id="publicDataDetailPk"\s+value="([^"]+)"', document).group(1)
    for operation in ("7196", "7197", "7198", "7199"):
        record, text = fetch("operation_" + operation, "https://www.data.go.kr/tcs/dss/selectApiDetailFunction.do", form={"oprtinSeqNo": operation, "publicDataDetailPk": detail, "publicDataPk": "15003029"})
        record["operation_id"] = operation
        record["extracted"] = inspect_page(text)
        record["endpoint_urls"] = sorted(set(re.findall(r'https?://openapi\.q-net\.or\.kr/[^\s<>"\']+', text)))
        results["operation_documentation"].append(record)
        print(operation, record.get("http_status"), record["endpoint_urls"], flush=True)
    record, text = fetch("eligibility_all", "http://openapi.q-net.or.kr/api/service/rest/InquiryExamQualItemSVC/getList", {"pageNo": "1", "numOfRows": "200"})
    record.update(xml_summary(text))
    if record.get("result_code") == "00":
        items = [{child.tag: child.text or "" for child in item} for item in ET.fromstring(text).findall("./body/items/item")]
        record["grade_counts"] = dict(Counter(item.get("grdNm") for item in items))
        record["engineer_items"] = [item for item in items if item.get("grdNm") == "기사"]
    results["probes"].append(record)
    print("eligibility_all", record.get("result_code"), record.get("item_count"), flush=True)
    (ROOT / "official_remaining_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
