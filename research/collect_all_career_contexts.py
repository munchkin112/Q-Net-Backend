"""613종목 직무·진로 원문을 재개 가능한 방식으로 수집하며 DB는 변경하지 않는다."""
import argparse
import csv
import hashlib
import json
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx
from research.collect_career_samples import extract_career_sections

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'research/preparation/recommendation'
BATCH = OUTPUT / 'full_collection'
MAX_BYTES = 3_000_000
REJECTED_TEXT = ['통계자료', '합격률', '소관부처명', '컨텐츠 바로가기', '<html', '<script']


def save_json(path, data):
    """완료된 JSON만 교체하여 중단 후에도 다시 읽을 수 있게 한다."""
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def validate_career_content(text, sections, name, identity_confirmed=False):
    """다른 페이지·빈 구간·메뉴·통계 오염을 실제 자료와 구별한다."""
    exact = name in text
    family = re.sub(r'\([^)]*\)', '', name).strip()
    if not identity_confirmed and not exact and not (family and family in text):
        return 'identity_not_confirmed', ['certificate_name_missing'], 'unconfirmed'
    identity = 'official_wrapper_code_and_name' if identity_confirmed else ('exact_name_found' if exact else 'shared_family_name_only')
    present = [value for value in sections.values() if value]
    if not present:
        return 'empty', ['career_sections_missing'], identity
    issues = []
    for term in REJECTED_TEXT:
        if term == '통계자료':
            contaminated = any(term in value.splitlines() for value in present)
        else:
            contaminated = any(term in value for value in present)
        if contaminated:
            issues.append(term)
    if issues:
        return 'needs_content_review', ['unexpected_section_text:' + term for term in issues], identity
    if identity not in ['exact_name_found', 'official_wrapper_code_and_name']:
        return 'needs_content_review', ['shared_family_identity_requires_review'], identity
    return 'fetched', [], identity


def fetch_career_record(client, item):
    """일시적 실패만 1회 재시도하고 사실·출처·누락 상태를 함께 저장한다."""
    code = item['qnet_code']
    url = f'https://www.q-net.or.kr/crf005.do?id=crf00503s01&gSite=Q&jmCd={code}&jmInfoDivCcd=A0'
    record = {'certificate_id':item['certificate_id'], 'qnet_code':code, 'name':item['name'], 'category':item['category'], 'source_url':url, 'retrieved_at':datetime.now(timezone.utc).isoformat(), 'access_method':'official_html_page', 'review_status':'not_semantically_reviewed'}
    for attempt in range(2):
        record['retry_count'] = attempt
        try:
            with client.stream('GET', url) as response:
                record['http_status'] = response.status_code
                response.raise_for_status()
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw)>MAX_BYTES:
                        record.update(collection_status='failed', error_type='response_too_large', sections={})
                        return record
            raw = bytes(raw)
            try:
                html = raw.decode('utf-8')
                record['encoding'] = 'utf-8'
            except UnicodeDecodeError:
                html = raw.decode('euc-kr')
                record['encoding'] = 'euc-kr'
            text, sections = extract_career_sections(html, item['name'])
            status, issues, identity = validate_career_content(text, sections, item['name'])
            (BATCH / f'{code}.html').write_bytes(raw)
            (BATCH / f'{code}.txt').write_text(text, encoding='utf-8')
            record.update(collection_status=status, issues=issues, identity_check=identity, sections=sections, content_sha256=hashlib.sha256(raw).hexdigest())
            return record
        except (httpx.HTTPError, UnicodeDecodeError) as error:
            record.update(collection_status='failed', error_type=type(error).__name__, sections={})
            if isinstance(error,UnicodeDecodeError):return record
            if isinstance(error,httpx.HTTPStatusError) and error.response.status_code<500 and error.response.status_code!=429:return record
            if attempt==0:time.sleep(1)
    return record


def build_collection_results(items, records):
    """직접 검토한 표본은 유지하고 자동 수집은 검토 대기 상태로 통합한다."""
    documents=[]
    reviewed_documents=[json.loads(line) for line in (OUTPUT/'official_career_documents.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    reviewed_codes={d['qnet_code'] for d in reviewed_documents}
    documents.extend(reviewed_documents)
    rows=[]
    for item in items:
        record=records.get(item['qnet_code'])
        if not record:continue
        row={'qnet_code':item['qnet_code'],'name':item['name'],'category':item['category'],'collection_status':record['collection_status'],'overview_present':bool(record['sections'].get('overview')),'duties_present':bool(record['sections'].get('duties')),'career_present':bool(record['sections'].get('career')),'issues':' | '.join(record.get('issues',[])),'source_url':record['source_url']}
        rows.append(row)
        item['career_collection_status']=record['collection_status']
        item['missing_official_sections']=[key for key in ['overview','duties','career'] if not record['sections'].get(key)]
        if item['qnet_code'] in reviewed_codes:continue
        evidence=[]
        item['career_evidence']=[]
        item['summary']=None
        item['summary_source_ids']=[]
        item.pop('summary_type',None)
        item.pop('summary_review_status',None)
        if record['collection_status']=='fetched':
            for section, content in record['sections'].items():
                if not content:continue
                doc={'document_id':f"qnet:{item['qnet_code']}:{section}",'certificate_id':item['certificate_id'],'qnet_code':item['qnet_code'],'certificate_name':item['name'],'section':section,'content':content,'source_url':record['source_url'],'retrieved_at':record['retrieved_at'],'document_title':item['name']+' 기본정보','content_sha256':hashlib.sha256(content.encode('utf-8')).hexdigest(),'raw_page_sha256':record['content_sha256'],'review_status':'automatic_structure_checked_semantic_review_pending','usage_scope':'raw_career_context; historical_law_and_forecast_claims_need_review'}
                documents.append(doc);evidence.append(doc)
            item['career_evidence']=evidence
            item['evidence_status']='official_context_collected_review_pending'
            # 본문 원문만 발췌하며 개인별 추천 이유나 미확인 직업명은 생성하지 않는다.
            duties=record['sections'].get('duties')
            if duties:
                first_line=duties.split('\n')[0]
                if len(first_line)<=300:
                    item['summary']=first_line
                    item['summary_source_ids']=[f"qnet:{item['qnet_code']}:duties"]
                    item['summary_type']='official_duties_excerpt'
                    item['summary_review_status']='semantic_review_pending'
        else:
            item['evidence_status']='career_context_unavailable_or_needs_review'
    save_json(OUTPUT/'candidate_contexts.json',items)
    save_json(OUTPUT/'career_collection_results.json',list(records.values()))
    (OUTPUT/'all_official_career_documents.jsonl').write_text(''.join(json.dumps(d,ensure_ascii=False)+'\n' for d in documents),encoding='utf-8')
    with (OUTPUT/'career_collection_inventory.csv').open('w',encoding='utf-8-sig',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    states=Counter(r['collection_status'] for r in records.values())
    report={'completed_at':datetime.now(timezone.utc).isoformat(),'task':4,'target_count':len(items),'processed_count':len(records),'collection_status_counts':dict(states),'by_category':{category:dict(Counter(r['collection_status'] for r in records.values() if r['category']==category)) for category in ['T','S']},'overview_present':sum(bool(r['sections'].get('overview')) for r in records.values()),'duties_present':sum(bool(r['sections'].get('duties')) for r in records.values()),'career_present':sum(bool(r['sections'].get('career')) for r in records.values()),'official_documents':len(documents),'reviewed_sample_count':len(reviewed_codes),'reviewed_related_roles_preserved':sum(len(item['related_jobs']) for item in items if item['qnet_code'] in reviewed_codes),'unreviewed_duties_excerpts':sum(item.get('summary_type')=='official_duties_excerpt' for item in items),'fixed_interest_assignments':0,'database_changed':False,'github_pushed':False,'llm_called':False,'note':'전체 원문 수집·상태 기록 단계. 자동 수집 자료는 5번 의미 검증 전까지 검토 완료 아님.'}
    save_json(OUTPUT/'step4_completion_report.json',report)
    print(json.dumps(report,ensure_ascii=True,indent=2),flush=True)


def collect_all_career_contexts(limit=None):
    """직렬 호출과 짧은 간격으로 수집하고 종목별 체크포인트를 저장한다."""
    BATCH.mkdir(parents=True,exist_ok=True)
    items=json.loads((OUTPUT/'candidate_contexts.json').read_text(encoding='utf-8'))
    samples={r['qnet_code']:r for r in json.loads((OUTPUT/'samples/collected_sections.json').read_text(encoding='utf-8'))}
    records={}
    with httpx.Client(timeout=10,follow_redirects=True) as client:
        for index,item in enumerate(items):
            if limit is not None and index>=limit:break
            code=item['qnet_code'];checkpoint=BATCH/f'{code}.json'
            if checkpoint.exists():record=json.loads(checkpoint.read_text(encoding='utf-8'))
            elif code in samples:
                record=samples[code].copy();record['reused_sample']=True;record['identity_check']='sample_reviewed'
            else:
                record=fetch_career_record(client,item)
                time.sleep(0.15)
            if record['certificate_id']!=item['certificate_id']:raise ValueError('체크포인트 종목 ID 불일치')
            save_json(checkpoint,record)
            records[code]=record
            if (index+1)%25==0:print('processed',index+1,'statuses',dict(Counter(r['collection_status'] for r in records.values())),flush=True)
    build_collection_results(items,records)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--limit',type=int)
    collect_all_career_contexts(parser.parse_args().limit)
