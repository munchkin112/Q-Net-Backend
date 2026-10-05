"""공식 Q-Net XML API를 호출하고 최대 한 번 재시도한다."""

from datetime import datetime, timezone
import xml.etree.ElementTree as ET

import httpx


CATALOG_URL = "http://openapi.q-net.or.kr/api/service/rest/InquiryListNationalQualifcationSVC/getList"
TECHNICAL_SCHEDULE_URL = "http://openapi.q-net.or.kr/api/service/rest/InquiryTestInformationNTQSVC/getJMList"
EXAM_INFORMATION_URL = "http://openapi.q-net.or.kr/api/service/rest/InquiryInformationTradeNTQSVC/getList"
EXAM_FEE_URL = "http://openapi.q-net.or.kr/api/service/rest/InquiryTestInformationNTQSVC/getFeeList"
MAX_RETRY = 1
TIMEOUT_SECONDS = 20
MAX_RESPONSE_BYTES = 2_000_000


class OfficialAPIError(Exception):
    """실패 종류와 재시도 가능 여부를 함께 전달한다."""

    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.retry_count = 0


def parse_xml_items(xml_text: str) -> list[dict[str, str]]:
    """HTTP 성공과 별도로 공식 결과코드를 확인하고 item들을 딕셔너리로 변환한다."""
    if "<!DOCTYPE" in xml_text.upper() or "<!ENTITY" in xml_text.upper():
        raise OfficialAPIError("invalid_xml", "허용하지 않는 XML 선언입니다.")
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        raise OfficialAPIError("invalid_xml", "공식 응답을 XML로 읽을 수 없습니다.") from None
    code = root.findtext("./header/resultCode")
    if code is None:
        raise OfficialAPIError("invalid_response", "공식 결과코드가 없는 응답입니다.")
    if code != "00":
        # 인증 오류나 잘못된 요청은 재시도해도 해결되지 않는다.
        retryable = code == "99"
        raise OfficialAPIError("provider_error", f"공식 API 결과코드: {code}", retryable)
    if root.find("./body/items") is None:
        raise OfficialAPIError("invalid_response", "공식 응답에 목록 구조가 없습니다.")
    items = []
    for item in root.findall("./body/items/item"):
        values = {}
        for field in item:
            values[field.tag.lower()] = (field.text or "").strip()
        items.append(values)
    return items


def request_items(client: httpx.Client, url: str, params: dict | None = None) -> dict:
    """통신 실패는 한 번 재시도하며 정상 빈 목록은 그대로 반환한다."""
    for attempt in range(MAX_RETRY + 1):
        try:
            # stream으로 크기를 제한하여 너무 큰 외부 응답을 메모리에 쌓지 않는다.
            with client.stream("GET", url, params=params, timeout=TIMEOUT_SECONDS) as response:
                if response.status_code != 200:
                    retryable = response.status_code >= 500 or response.status_code == 429
                    raise OfficialAPIError("http_error", f"공식 API HTTP 상태: {response.status_code}", retryable)
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise OfficialAPIError("response_too_large", "공식 응답이 허용 크기를 초과했습니다.")
            try:
                xml_text = body.decode("utf-8-sig")
            except UnicodeDecodeError:
                raise OfficialAPIError("invalid_encoding", "공식 응답의 문자 인코딩을 확인할 수 없습니다.") from None
            items = parse_xml_items(xml_text)
            return {
                "items": items,
                "source_url": url,
                "retrieved_at": datetime.now(timezone.utc),
                "retry_count": attempt,
            }
        except httpx.TimeoutException:
            error = OfficialAPIError("timeout", "공식 API 응답시간을 초과했습니다.", True)
        except httpx.RequestError:
            error = OfficialAPIError("connection_error", "공식 API에 연결할 수 없습니다.", True)
        except OfficialAPIError as caught:
            error = caught
        error.retry_count = attempt
        if not error.retryable or attempt == MAX_RETRY:
            raise error
    raise RuntimeError("재시도 흐름을 확인해주세요.")


def fetch_catalog() -> dict:
    """공식 종목 목록을 조회한다. 인증 없는 성공은 제공자가 계속 보장하는 계약이 아니다."""
    with httpx.Client(follow_redirects=False) as client:
        return request_items(client, CATALOG_URL)


def fetch_technical_schedules(qnet_code: str) -> dict:
    """종목별 기술자격 일정을 조회한다. 전문자격·상시시험은 이 호출의 지원 범위가 아니다."""
    with httpx.Client(follow_redirects=False) as client:
        result = request_items(client, TECHNICAL_SCHEDULE_URL, {"jmCd": qnet_code})
    result["source_url"] = str(httpx.URL(TECHNICAL_SCHEDULE_URL, params={"jmCd": qnet_code}))
    return result


def fetch_exam_information(qnet_code: str) -> dict:
    """종목별 공식 자격정보 원문을 조회한다."""
    with httpx.Client(follow_redirects=False) as client:
        result = request_items(client, EXAM_INFORMATION_URL, {"jmCd": qnet_code})
    result["source_url"] = str(httpx.URL(EXAM_INFORMATION_URL, params={"jmCd": qnet_code}))
    return result


def fetch_exam_fees(qnet_code: str) -> dict:
    """기술자격 종목의 공식 응시수수료 원문을 조회한다."""
    with httpx.Client(follow_redirects=False) as client:
        result = request_items(client, EXAM_FEE_URL, {"jmCd": qnet_code})
    result["source_url"] = str(httpx.URL(EXAM_FEE_URL, params={"jmCd": qnet_code}))
    return result
