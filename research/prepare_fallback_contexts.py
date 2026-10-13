"""누락 본문을 공식 별표와 공통 직무 근거로 보완하며 적용 범위를 기록한다."""
import hashlib
import json
import re
from pathlib import Path
from research.collect_all_career_contexts import OUTPUT, save_json

FUNCTION_DUTIES = {
'대목수':'목조건조물의해체·조립및치목(治木:나무다듬기)과그에따른업무',
'소목수':'목조건조물의창호·닫집등과이와유사한구조물의제작·설치및보수와그에따른업무',
'가공석공':'석재의가공과그에따른업무', '쌓기석공':'석조물의축조·해체및보수와그에따른업무',
'화공':'단청(불화를포함한다)과그에따른업무',
'드잡이공':'드잡이(기울거나내려앉은구조물을해체하지않고도구등을이용하여바로잡는일을말한다)와그에따른업무',
'번와와공':'기와의해체및이기와그에따른업무',
'제작와공':'기와ㆍ전돌(塼乭:흙으로구워만든벽돌)등의제작과그에따른업무',
'한식미장공':'미장과그에따른업무', '철물공':'철물등의제작및보수와그에따른업무',
'목조각공':'목재를이용한조각,목조각물의보수와그에따른업무',
'석조각공':'석재를이용한조각,석조각물의보수와그에따른업무',
'칠공':'옻등의전통재료를이용한칠,칠의보수와그에따른업무',
'도금공':'도금,도금과관련된보수와그에따른업무', '표구공':'표구,표구물의보수와그에따른업무',
'조경공':'조경의시공과그에따른업무', '세척공':'세척과그에따른업무',
'훈증공':'재료나자재의살균·살충·방부등을위한훈증과그에따른업무',
'보존처리공':'보존처리와그에따른업무',
'식물보호공':'식물의보존·보호를위한병충해방제,수술,토양개량,보호시설설치및환경개선과그에따른업무',
'실측설계사보':'실측및설계도서작성과그에따른업무',
'박제및표본제작공':'박제·표본제작및보수와그에따른업무',
'모사공':'서화류의모사와그에따른업무', '온돌공':'온돌의해체·설치및보수와그에따른업무',
}
TECHNICIAN_DUTIES = {
'보수':'건축ㆍ토목공사의시공및감리',
'단청':'단청분야[불화(佛畵)를포함한다]의시공및감리',
'실측설계':'국가유산수리의실측설계도서의작성및감리',
'조경':'조경공사의조경계획과시공및감리',
'보존과학':'보존처리(동산문화유산은제외한다)시공및감리',
'식물보호':'식물의보존ㆍ보호를위한병충해방제,수술,토양개량,보호시설설치,환경개선및감리',
}


def prepare_fallback_contexts():
    """특정 종목·자격군 공통·깨끗한 구간만 구별하여 근거 문단으로 저장한다."""
    folder = OUTPUT / 'fallback_checks'
    items = json.loads((OUTPUT/'candidate_contexts.json').read_text(encoding='utf-8'))
    records = {r['qnet_code']:r for r in json.loads((OUTPUT/'career_collection_results.json').read_text(encoding='utf-8'))}
    manifests = {r['name']:r for r in json.loads((folder/'heritage_manifest.json').read_text(encoding='utf-8'))}
    docs = []
    for item in items:
        # 재실행 시 이전 대체 근거를 교체하여 같은 문단이 중복되지 않게 한다.
        item['career_evidence']=[doc for doc in item.get('career_evidence',[]) if not doc['document_id'].startswith('fallback:')]
    for item in items:
        record = records[item['qnet_code']]
        if record['collection_status']=='fetched': continue
        sections = {}
        scope = 'certificate_specific'
        if item['name'].startswith('국가유산수리'):
            role = re.search(r'\((.*)\)',item['name']).group(1)
            kind = 'heritage_functions' if '기능자' in item['name'] else 'heritage_technicians'
            mapping = FUNCTION_DUTIES if kind=='heritage_functions' else TECHNICIAN_DUTIES
            body = (folder/f'{kind}.current.txt').read_text(encoding='utf-8')
            excerpt = mapping[role]
            assert excerpt in re.sub(r'\s+','',body), '별표에 없는 업무 문구'
            manifest = manifests[kind]
            assert hashlib.sha256((folder/f'{kind}.current.pdf').read_bytes()).hexdigest()==manifest['content_sha256']
            sections={'duties':excerpt}
            source = {'url':manifest['source_url'],'retrieved_at':manifest['retrieved_at'],'raw_hash':manifest['content_sha256'],'file':f'fallback_checks/{kind}.current.pdf','review_status':'assistant_reviewed_against_official_source','version':manifest['law_effective_date']}
        elif item['name'].startswith(('경매사(','기술지도사(')):
            shared_code = '9698' if item['name'].startswith('경매사(') else '9729'
            shared = records[shared_code]
            sections = {'duties':shared['sections']['duties']}
            source = {'url':shared['source_url'],'retrieved_at':shared['retrieved_at'],'raw_hash':shared['content_sha256'],'file':f'full_collection/{shared_code}.html','review_status':'shared_family_evidence_review_pending'}
            scope = 'qualification_family_common_only'
        elif record['collection_status']=='needs_content_review':
            # 전망·합격률 설명을 제외하고 종목이 확인된 정상 직무 구간만 사용한다.
            for section in ['overview','duties']:
                value=record['sections'].get(section)
                if value and not any(term in value for term in ['합격률','소관부처명','<script']): sections[section]=value
            source={'url':record['source_url'],'retrieved_at':record['retrieved_at'],'raw_hash':record['content_sha256'],'file':f"full_collection/{item['qnet_code']}.html",'review_status':'automatic_structure_checked_semantic_review_pending'}
        else: continue
        for section,content in sections.items():
            doc={'document_id':f"fallback:{item['qnet_code']}:{section}",'certificate_id':item['certificate_id'],'qnet_code':item['qnet_code'],'certificate_name':item['name'],'section':section,'content':content,'source_url':source['url'],'retrieved_at':source['retrieved_at'],'document_title':item['name']+' 업무 근거','content_sha256':hashlib.sha256(content.encode('utf-8')).hexdigest(),'raw_page_sha256':source['raw_hash'],'raw_file':source['file'],'review_status':source['review_status'],'evidence_scope':scope,'usage_scope':'직무 설명만 사용. 응시자격·취업·선임 보장 없음'}
            if source.get('version'):doc['law_effective_date']=source['version']
            docs.append(doc)
            item.setdefault('career_evidence',[]).append(doc)
        item['evidence_status']='official_fallback_context_available'
        item['fallback_evidence_scope']=scope
        item['fallback_used']=True
        # 원문 발췌는 화면용 최종 요약이나 개인별 추천 이유가 아니다.
        item['summary']=sections.get('duties')
        item['summary_source_ids']=[f"fallback:{item['qnet_code']}:duties"] if sections.get('duties') else []
        item['summary_type']='official_fallback_duties_excerpt'
        item['summary_review_status']='semantic_review_pending' if scope!='certificate_specific' else source['review_status']
    save_json(OUTPUT/'candidate_contexts.json',items)
    (OUTPUT/'fallback_career_documents.jsonl').write_text(''.join(json.dumps(d,ensure_ascii=False)+'\n' for d in docs),encoding='utf-8')
    # 기본 수집 원문과 대체 원문은 별도 유지하고 검색 입력용 합본만 생성한다.
    base=(OUTPUT/'all_official_career_documents.jsonl').read_text(encoding='utf-8')
    (OUTPUT/'combined_career_documents.jsonl').write_text(base+''.join(json.dumps(d,ensure_ascii=False)+'\n' for d in docs),encoding='utf-8')
    print(json.dumps({'fallback_certificates':len({d['qnet_code'] for d in docs}),'fallback_documents':len(docs),'with_context':sum(bool(i['career_evidence']) for i in items),'without_context':sum(not i['career_evidence'] for i in items)},ensure_ascii=True))


if __name__=='__main__':
    prepare_fallback_contexts()
