"""Probe documented official endpoints and public Q-Net pages; save evidence locally."""

import argparse
import hashlib
import html
import json
import os
import re
import time
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, unquote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
KST = timezone(timedelta(hours=9))
API_SOURCES = [
    ("schedule", "15074408", "https://apis.data.go.kr/B490007/qualExamSchd/getQualExamSchdList", "serviceKey", {"numOfRows": "10", "pageNo": "1", "dataFormat": "json", "implYy": "2026", "qualgbCd": "T", "jmCd": "1320"}),
    ("certificate_list", "15003024", "http://openapi.q-net.or.kr/api/service/rest/InquiryListNationalQualifcationSVC/getList", "serviceKey", {}),
    ("certificate_information", "15003003", "http://openapi.q-net.or.kr/api/service/rest/InquiryInformationTradeNTQSVC/getList", "ServiceKey", {"jmCd": "1320"}),
    ("eligibility_items", "15037519", "http://openapi.q-net.or.kr/api/service/rest/InquiryExamQualItemSVC/getList", "ServiceKey", {"pageNo": "1", "numOfRows": "5"}),
    ("exam_sites", "15068172", "http://openapi.q-net.or.kr/api/service/rest/InquiryExamAreaSVC/getList", "ServiceKey", {"brchCd": "01", "pageNo": "1", "numOfRows": "5"}),
    ("major_jobs", "15037356", "http://openapi.q-net.or.kr/api/service/rest/InquiryUdeptObligSVC/getList", "ServiceKey", {"pageNo": "1", "numOfRows": "5"}),
    ("professional_schedule", "15003027", "http://openapi.q-net.or.kr/api/service/rest/InquiryTestDatesNationalProfessionalQualificationSVC/getList", "serviceKey", {"seriesCd": "21"}),
]


class PageParser(HTMLParser):
    """Collect visible text, table cells, and links without third-party packages."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text = []
        self.tables = []
        self.links = []
        self.table = None
        self.row = None
        self.cell = None
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "style"):
            self.hidden += 1
        if tag == "table":
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []
        elif tag == "a":
            self.links.append(attrs)
        elif tag == "br":
            self.text.append("\n")
            if self.cell is not None:
                self.cell.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(re.sub(r"\s+", " ", "".join(self.cell)).strip())
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None
        if tag in ("p", "li", "div", "tr", "h1", "h2", "h3"):
            self.text.append("\n")

    def handle_data(self, data):
        if self.hidden:
            return
        self.text.append(data)
        if self.cell is not None:
            self.cell.append(data)


def fetch(label, base, params=None, key_name=None, key=None, form=None):
    """Fetch once with a timeout and persist response; never persist a real key."""
    params = dict(params or {})
    if key_name and key:
        params[key_name] = unquote(key)
    url = base + ("?" + urlencode(params) if params else "")
    start = time.monotonic()
    result = {"label": label, "source_url": base, "params": {k: v for k, v in params.items() if k != key_name}, "auth": "configured" if key else "missing", "retrieved_at": datetime.now(KST).isoformat(), "http_method": "POST" if form else "GET"}
    request_body = urlencode(form).encode("utf-8") if form else None
    try:
        try:
            response = urlopen(Request(url, data=request_body, headers={"User-Agent": "QNetProject-FeasibilityProbe/0.1"}), timeout=20)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read(2_000_000)
            result["http_status"] = response.code
            result["content_type"] = response.headers.get("Content-Type", "")
            charset = response.headers.get_content_charset()
            if not charset:
                meta = re.search(rb"charset\s*=\s*[\"']?([\w-]+)", raw[:4000], re.I)
                charset = meta.group(1).decode("ascii") if meta else "utf-8"
            text = raw.decode(charset, errors="replace")
            if key:
                text = text.replace(key, "[REDACTED]").replace(unquote(key), "[REDACTED]")
            result["byte_count"] = len(raw)
            result["sha256"] = hashlib.sha256(raw).hexdigest()
            suffix = "html" if "html" in result["content_type"] else "txt"
            filename = f"{label}.{suffix}"
            (ROOT / "responses" / filename).write_text(text, encoding="utf-8")
            result["response_file"] = "responses/" + filename
            if "html" not in result["content_type"]:
                result["body_excerpt"] = text[:1200]
            result["elapsed_seconds"] = round(time.monotonic() - start, 3)
            return result, text
    except (URLError, TimeoutError, OSError, LookupError) as error:
        result["error"] = str(error.reason) if isinstance(error, URLError) else type(error).__name__
        result["elapsed_seconds"] = round(time.monotonic() - start, 3)
        return result, ""


def inspect_page(text):
    """Unescape the embedded acquisition-method HTML and extract public tables."""
    parser = PageParser()
    parser.feed(text)
    embedded = PageParser()
    embedded.feed(html.unescape("\n".join(parser.text)))
    visible = re.sub(r"[ \t]+", " ", "\n".join(embedded.text))
    visible = re.sub(r"\n\s*\n", "\n", visible)
    return {
        "tables": parser.tables,
        "content_markers": {word: word in visible for word in ("시험일정", "관련학과", "시험과목", "합격기준", "수수료")},
        "fees": re.findall(r"[\d,]+\s*원", visible),
        "visible_text": visible,
        "links": parser.links,
    }


def main():
    args = argparse.ArgumentParser()
    args.add_argument("--with-key", action="store_true", help="Use QNET_SERVICE_KEY environment variable for API probes")
    options = args.parse_args()
    key = os.environ.get("QNET_SERVICE_KEY") if options.with_key else None
    if options.with_key and not key:
        raise SystemExit("Set QNET_SERVICE_KEY locally before using --with-key.")
    (ROOT / "responses").mkdir(parents=True, exist_ok=True)
    results = {"run_at": datetime.now(KST).isoformat(), "api_probes": [], "public_pages": []}
    for label, dataset, url, key_name, params in API_SOURCES:
        record, _ = fetch(label, url, params, key_name, key)
        record["documentation_url"] = f"https://www.data.go.kr/data/{dataset}/openapi.do"
        results["api_probes"].append(record)
        print(label, record.get("http_status", record.get("error")), flush=True)
    for code, name in (("1320", "정보처리기사"), ("1431", "산업안전기사"), ("7910", "한식조리기능사")):
        label = "certificate_" + code
        record, text = fetch(label, "https://www.q-net.or.kr/crf005.do", {"id": "crf00503s02", "jmCd": code, "jmInfoDivCcd": "B0"})
        record["expected_certificate"] = name
        if record.get("http_status") == 200:
            record["extracted"] = inspect_page(text)
            record["certificate_name_found"] = name in record["extracted"]["visible_text"]
        results["public_pages"].append(record)
        print(label, record.get("http_status", record.get("error")), flush=True)
    record, text = fetch("eligibility_guide", "https://www.q-net.or.kr/crf006.do", {"gSite": "Q", "id": "crf00603"})
    if record.get("http_status") == 200:
        record["extracted"] = inspect_page(text)
        record["relevant_html_lines"] = [line.strip() for line in text.splitlines() if ("crf006" in line or "iframe" in line) and len(line) < 500][-40:]
    results["public_pages"].append(record)
    output = ROOT / ("official_source_results_authenticated.json" if key else "official_source_results.json")
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Evidence:", output, flush=True)


if __name__ == "__main__":
    main()
