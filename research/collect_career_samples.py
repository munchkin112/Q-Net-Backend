"""관심 분야 추천용 표본의 공식 개요·직무·진로 구간을 수집한다."""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx
from backend.exam_data import extract_plain_text

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'research/preparation/recommendation/samples'
CODES = ['1320', '1021', '1150', '1431', '1390', '9630', '9661', '9502']
HEADINGS = ['기본정보', '개요', '변천과정', '수행직무', '실시기관 홈페이지', '실시기관명', '진로 및 전망', '종목별 검정현황', '종목별 검정 현황', '기타사항', '소관부처명', '통계자료']


def extract_career_sections(html, name):
    """중첩 HTML을 실행 없이 정리하고 정확한 제목 사이의 본문만 추출한다."""
    text = html
    for _ in range(3):
        text = extract_plain_text(text)
    lines = text.splitlines()
    sections = {}
    selected = None
    for line in lines:
        if line in HEADINGS:
            selected = {'개요': 'overview', '수행직무': 'duties', '진로 및 전망': 'career'}.get(line)
            if selected:
                sections.setdefault(selected, [])
            continue
        if selected:
            if line == name + ' ' + {'overview': '개요', 'duties': '수행직무', 'career': '진로 및 전망'}[selected]:
                continue
            sections[selected].append(line)
    result = {key: '\n'.join(value).strip() or None for key, value in sections.items()}
    for key in ['overview', 'duties', 'career']:
        result.setdefault(key, None)
    return text, result


def collect_career_samples():
    """실제 종목 ID와 출처를 보존하고 오류·누락은 별도 상태로 기록한다."""
    OUTPUT.mkdir(parents=True, exist_ok=True)
    candidates = json.loads((OUTPUT.parent / 'candidate_contexts.json').read_text(encoding='utf-8'))
    by_code = {item['qnet_code']: item for item in candidates}
    samples = []
    with httpx.Client(timeout=15, follow_redirects=True) as client:
        for code in CODES:
            item = by_code[code]
            url = f'https://www.q-net.or.kr/crf005.do?id=crf00503s01&gSite=Q&jmCd={code}&jmInfoDivCcd=A0'
            record = {'certificate_id':item['certificate_id'], 'qnet_code':code, 'name':item['name'], 'category':item['category'], 'source_url':url, 'retrieved_at':datetime.now(timezone.utc).isoformat(), 'access_method':'official_html_page', 'review_status':'pending_content_review'}
            for attempt in range(2):
                try:
                    response = client.get(url)
                    response.raise_for_status()
                    raw = response.content
                    html = raw.decode('utf-8')
                    text, sections = extract_career_sections(html, item['name'])
                    # 제목 검증에 실패한 다른 페이지는 해당 자격증 근거로 쓰지 않는다.
                    if item['name'] not in text and not (code == '9661' and '관광통역안내사' in text) and not (code == '9502' and '경비지도사' in text):
                        record.update(collection_status='wrong_or_missing_certificate_content', sections={}, retry_count=attempt)
                        break
                    (OUTPUT / f'{code}.html').write_bytes(raw)
                    (OUTPUT / f'{code}.txt').write_text(text, encoding='utf-8')
                    record.update(http_status=response.status_code, content_sha256=hashlib.sha256(raw).hexdigest(), sections=sections, collection_status='fetched' if any(sections.values()) else 'empty', retry_count=attempt)
                    break
                except (httpx.HTTPError, UnicodeDecodeError) as error:
                    record.update(collection_status='failed', error_type=type(error).__name__, sections={}, retry_count=attempt)
                    if isinstance(error, httpx.HTTPStatusError) and error.response.status_code < 500 and error.response.status_code != 429:
                        break
            samples.append(record)
            print(code, record['collection_status'], {key:len(value or '') for key,value in record['sections'].items()}, flush=True)
    (OUTPUT / 'collected_sections.json').write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    collect_career_samples()
