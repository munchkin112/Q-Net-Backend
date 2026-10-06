"""기능 범위 확정 전 전문자격 공식 원본을 수집한다. DB는 변경하지 않는다."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import xml.etree.ElementTree as ET

from backend.official_api import OfficialAPIError, parse_xml_items
from research.probe_official_sources import fetch


ROOT = Path(__file__).resolve().parents[1]
DETAIL_URL = "http://openapi.q-net.or.kr/api/service/rest/InquiryInformationTradeNTQSVC/getList"
SCHEDULE_URL = "http://openapi.q-net.or.kr/api/service/rest/InquiryTestDatesNationalProfessionalQualificationSVC/getList"
OUTPUT = ROOT / "research/preparation/professional_sources.json"


def load_professional_catalog() -> list[dict]:
    """보관한 공식 XML에서 전문자격만 읽는다. 코드 앞의 0을 유지한다."""
    tree = ET.parse(ROOT / "research/responses/certificate_list.txt")
    rows = []
    for item in tree.findall("./body/items/item"):
        row = {field.tag.lower(): (field.text or "").strip() for field in item}
        if row["qualgbcd"] == "S":
            rows.append(row)
    return rows


def collect_one(kind: str, code: str) -> dict:
    """통신·제공기관 오류는 한 번 재시도하고 정상 빈 응답은 반복하지 않는다."""
    url = DETAIL_URL if kind == "details" else SCHEDULE_URL
    params = {"jmCd": code} if kind == "details" else {"seriesCd": code}
    attempts = []
    for attempt in range(2):
        record, body = fetch(f"preparation_{kind}_{code}_attempt{attempt}", url, params)
        attempts.append(record)
        retryable = False
        try:
            if record.get("error"):
                retryable = True
                raise ValueError("통신 오류")
            if record.get("http_status") != 200:
                retryable = record.get("http_status", 0) >= 500 or record.get("http_status") == 429
                raise ValueError("HTTP 오류")
            if record.get("byte_count", 0) >= 2_000_000:
                raise ValueError("원본 크기 제한에 도달했습니다.")
            items = parse_xml_items(body)
            return {"kind": kind, "code": code, "status": "fetched" if items else "empty",
                    "items": items, "attempts": attempts, "retry_count": attempt,
                    "source_url": url, "params": params, "retrieved_at": record["retrieved_at"],
                    "response_file": record["response_file"]}
        except (OfficialAPIError, ValueError) as error:
            if isinstance(error, OfficialAPIError):
                retryable = error.retryable
            message = str(error)
        if not retryable or attempt == 1:
            return {"kind": kind, "code": code, "status": "failed", "attempts": attempts,
                    "retry_count": attempt, "message": message, "source_url": url, "params": params}
        time.sleep(1)
    raise RuntimeError("재시도 흐름을 확인해주세요.")


def main() -> None:
    """각 요청 후 진행 파일을 저장한다. --resume은 이미 기록된 실패도 건너뛴다."""
    parser = argparse.ArgumentParser(description="전문자격 공식 원본 사전 수집 (DB 쓰기 없음)")
    parser.add_argument("--resume", action="store_true")
    options = parser.parse_args()
    catalog = load_professional_catalog()
    series = sorted({row["seriescd"] for row in catalog})
    jobs = [("schedules", code) for code in series]
    jobs += [("details", row["jmcd"]) for row in catalog]
    report = {"started_at": datetime.now(timezone.utc).isoformat(), "completed": False,
              "catalog_source": "research/responses/certificate_list.txt",
              "professional_count": len(catalog), "series_count": len(series), "results": []}
    if OUTPUT.exists():
        if not options.resume:
            parser.error("기존 원본이 있습니다. --resume으로 이어받으세요.")
        report = json.loads(OUTPUT.read_text(encoding="utf-8"))
        if report["professional_count"] != len(catalog) or report["series_count"] != len(series):
            parser.error("기존 보고서와 현재 종목 목록이 다릅니다.")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    done = {(row["kind"], row["code"]) for row in report["results"]}
    for index, (kind, code) in enumerate(jobs, start=1):
        if (kind, code) in done:
            continue
        row = collect_one(kind, code)
        report["results"].append(row)
        report["completed"] = False
        temporary = OUTPUT.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(OUTPUT)
        print(f"[{index}/{len(jobs)}] {kind} {code}: {row['status']}", flush=True)
        time.sleep(0.5)
    report["completed"] = True
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
