"""공식 상세 페이지 식별값으로 보류 자료를 재검증하고 대체 경로를 확인한다."""
import hashlib
import json
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import httpx

from research.collect_all_career_contexts import OUTPUT, BATCH, build_collection_results, save_json, validate_career_content
from research.collect_career_samples import extract_career_sections


class CertificateIdentityParser(HTMLParser):
    """페이지가 실제 선택한 종목의 코드·이름을 숨김 필드에서 읽는다."""

    def __init__(self):
        super().__init__()
        self.fields = {}

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == 'input' and attributes.get('id') in ['jmCd', 'jmNm']:
            self.fields[attributes['id']] = attributes.get('value', '')


def validate_certificate_identity(html: str, code: str, name: str) -> bool:
    """다른 종목이 반환됐거나 메뉴에만 이름이 있으면 확인 성공으로 인정하지 않는다."""
    parser = CertificateIdentityParser()
    parser.feed(html)
    return parser.fields.get('jmCd') == code and parser.fields.get('jmNm') == name


def repair_career_contexts():
    """기존 원문을 보존하고 해결 여부·실제 미제공·추가 검토를 구분한다."""
    records = json.loads((OUTPUT / 'career_collection_results.json').read_text(encoding='utf-8'))
    items = json.loads((OUTPUT / 'candidate_contexts.json').read_text(encoding='utf-8'))
    repairs = []
    fallback_folder = OUTPUT / 'fallback_checks'
    fallback_folder.mkdir(exist_ok=True)
    with httpx.Client(timeout=15, follow_redirects=True) as client:
        for record in records:
            if record['collection_status'] == 'fetched':
                continue
            code = record['qnet_code']
            previous = record['collection_status']
            path = BATCH / f'{code}.identity.html'
            identity_url = f'https://www.q-net.or.kr/crf005.do?id=crf00503&gSite=Q&jmCd={code}'
            if not path.exists():
                response = client.get(identity_url)
                response.raise_for_status()
                path.write_bytes(response.content)
                time.sleep(0.15)
            confirmed = validate_certificate_identity(path.read_text(encoding='utf-8'), code, record['name'])
            record['identity_evidence'] = {'source_url':identity_url, 'content_sha256':hashlib.sha256(path.read_bytes()).hexdigest(), 'matched':confirmed, 'checked_at':datetime.now(timezone.utc).isoformat(), 'cached_file_saved_at':datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat()}
            text = (BATCH / f'{code}.txt').read_text(encoding='utf-8')
            status, issues, identity = validate_career_content(text, record['sections'], record['name'], identity_confirmed=confirmed)
            record.update(collection_status=status, issues=issues, identity_check=identity)
            if status == 'empty':
                # 상세 페이지가 호출하는 공식 시험정보 탭도 확인하되 시험과목을 직업 근거로 바꾸지 않는다.
                url = f'https://www.q-net.or.kr/crf005.do?id=crf00503s02&gSite=Q&jmCd={code}&jmInfoDivCcd=B0'
                raw_path = fallback_folder / f'{code}.exam.html'
                check_path = fallback_folder / f'{code}.json'
                if check_path.exists():
                    check = json.loads(check_path.read_text(encoding='utf-8'))
                else:
                    check = {'source_url':url,'retrieved_at':datetime.now(timezone.utc).isoformat()}
                    for attempt in range(2):
                        try:
                            response = client.get(url)
                            response.raise_for_status()
                            raw_path.write_bytes(response.content)
                            check.update(http_status=response.status_code, content_sha256=hashlib.sha256(response.content).hexdigest(), retry_count=attempt)
                            break
                        except httpx.HTTPError as error:
                            check.update(error_type=type(error).__name__, retry_count=attempt)
                            if isinstance(error,httpx.HTTPStatusError) and error.response.status_code<500 and error.response.status_code!=429:
                                break
                    save_json(check_path, check)
                    time.sleep(0.15)
                if raw_path.exists():
                    alternative_text, alternative_sections = extract_career_sections(raw_path.read_text(encoding='utf-8'), record['name'])
                    # 시험정보 탭에는 직무·진로 제목 구간이 없는지 별도로 기록한다.
                    check['career_sections_present'] = any(alternative_sections.values())
                    save_json(check_path, check)
                record['fallback_check'] = check
                record['availability_note'] = '확인한 기본정보 페이지의 직무·진로 미제공. 자격증 자체가 없거나 다른 공식 자료도 전부 없다는 뜻은 아님.'
            save_json(BATCH / f'{code}.json', record)
            repairs.append({'qnet_code':code, 'name':record['name'], 'previous_status':previous, 'current_status':status, 'identity_confirmed':confirmed, 'issues':issues})
            if len(repairs)%20 == 0:
                print('rechecked',len(repairs),flush=True)
    save_json(OUTPUT / 'career_repair_results.json',repairs)
    build_collection_results(items,{record['qnet_code']:record for record in records})


if __name__ == '__main__':
    repair_career_contexts()
