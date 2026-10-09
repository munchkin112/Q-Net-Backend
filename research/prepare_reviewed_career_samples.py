"""검토한 표본 요약·관련 역할을 실제 공식 구간의 근거와 연결한다."""
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'research/preparation/recommendation'
# 개인별 추천 결과가 아니라 공식 직무 사실을 읽기 쉽게 정리한 표본 자료다.
REVIEWED_TEXT = {
 '1320': {'summary':'소프트웨어 개발과 정보시스템 운영에 필요한 지식·기술을 다루는 국가기술자격입니다.', 'summary_sections':['overview','career'], 'roles':[('소프트웨어 개발 담당','career','컴퓨터 시스템을 개발'),('정보시스템 운영 담당','career','운용')], 'excerpts':{'overview':'all','career':'first_paragraph'}},
 '1021': {'summary':'기계·구조물의 설계·제작과 기술지도 등 기계공학 실무를 다루는 국가기술자격입니다.', 'summary_sections':['duties'], 'roles':[('기계설계 담당','duties','설계'),('기계 제작 담당','duties','제작')], 'excerpts':{'duties':'all'}},
 '1150': {'summary':'전기설비의 설계·감리·유지관리·운용과 관련된 국가기술자격입니다.', 'summary_sections':['duties'], 'roles':[('전기설비 설계 담당','duties','설계도서 작성'),('전기설비 유지관리 담당','duties','유지관리')], 'excerpts':{'duties':'all'}},
 '1431': {'summary':'산업재해 예방계획, 작업환경 점검·개선과 안전교육 등 산업현장 안전관리 직무를 다루는 국가기술자격입니다.', 'summary_sections':['duties'], 'roles':[('산업현장 안전관리 담당','duties','산업재해 예방계획'),('안전교육·훈련 담당','duties','안전교육 및 훈련')], 'excerpts':{'duties':'all'}},
 '1390': {'summary':'토지의 경계·면적을 확인하기 위한 지적측량 계획과 측량 업무를 다루는 국가기술자격입니다.', 'summary_sections':['overview','duties'], 'roles':[('지적측량 담당','duties','지적측량업무')], 'excerpts':{'overview':'all','duties':'all'}},
 '9630': {'summary':'부동산 중개를 중심으로 관리대행·컨설팅 등의 업무와 관련된 국가전문자격입니다.', 'summary_sections':['duties'], 'roles':[('부동산 중개업무 담당','duties','부동산 중개업무'),('부동산 컨설팅 담당','duties','컨설팅')], 'excerpts':{'overview':'all','duties':'all'}},
 '9661': {'summary':'외국어로 국내 관광지를 설명하고 외국인 관광객의 여행을 안내하는 국가전문자격입니다. 이 종목은 영어 구분입니다.', 'summary_sections':['overview','duties'], 'roles':[('관광통역안내 담당','duties','여행을 안내')], 'excerpts':{'overview':'all','duties':'all'}},
 '9502': {'summary':'기계경비 업무를 수행하는 경비원에게 전문지식을 전수하고 지도·감독하는 국가전문자격입니다.', 'summary_sections':['overview'], 'roles':[('기계경비원 지도·감독 담당','overview','지도, 감독')], 'excerpts':{'overview':'security_duties_only'}},
}


def prepare_reviewed_samples():
    """자료 누락은 유지하고 요약·관련 역할별 source_id를 검증해 저장한다."""
    samples = json.loads((OUTPUT/'samples/collected_sections.json').read_text(encoding='utf-8'))
    candidates = json.loads((OUTPUT/'candidate_contexts.json').read_text(encoding='utf-8'))
    by_code = {item['qnet_code']:item for item in candidates}
    documents=[]
    reviewed=[]
    for record in samples:
        code=record['qnet_code']
        definition=REVIEWED_TEXT[code]
        source_ids={}
        for section,mode in definition['excerpts'].items():
            content=record['sections'].get(section)
            assert content, (code,section)
            if mode=='first_paragraph':content=content.split('\n')[0]
            if mode=='security_duties_only':
                marker='이러한 기계경비 업체의 경비원'
                assert marker in content
                content=content[content.index(marker):]
            assert '소관부처명' not in content and '합격률' not in content
            source_id=f'qnet:{code}:{section}'
            source_ids[section]=source_id
            documents.append({'document_id':source_id,'certificate_id':record['certificate_id'],'qnet_code':code,'certificate_name':record['name'],'section':section,'content':content,'source_url':record['source_url'],'retrieved_at':record['retrieved_at'],'document_title':record['name']+' 기본정보','content_sha256':hashlib.sha256(content.encode('utf-8')).hexdigest(),'raw_page_sha256':record['content_sha256'],'review_status':'assistant_reviewed_against_official_source','usage_scope':'credential_duties_not_current_employment_forecast'})
        roles=[]
        for role,section,anchor in definition['roles']:
            doc=next(d for d in documents if d['document_id']==source_ids[section])
            assert anchor in doc['content'],(code,role,anchor)
            roles.append({'name':role,'source_ids':[source_ids[section]],'evidence_anchor':anchor,'name_type':'normalized_task_role','note':'공식 업무를 역할명으로 정리한 표현이며 취업·채용·별도 법정 선임 요건을 보장하지 않음'})
        item={'certificate_id':record['certificate_id'],'qnet_code':code,'name':record['name'],'category':record['category'],'summary':definition['summary'],'summary_source_ids':[source_ids[x] for x in definition['summary_sections']],'related_jobs':roles,'sources':[{'id':source_id,'title':record['name']+' '+section,'url':record['source_url'],'retrieved_at':record['retrieved_at']} for section,source_id in source_ids.items()],'missing_official_sections':[section for section in ['overview','duties','career'] if not record['sections'].get(section)],'review_status':'assistant_reviewed_against_official_source','interest_category_codes':None,'personal_recommendation_reason':None}
        if code=='9661':item['summary_basis_note']='영어 구분은 기존 공식 종목 목록 이름으로 확인함.'
        reviewed.append(item)
        original=by_code[code]
        original['summary']=item['summary']
        original['summary_source_ids']=item['summary_source_ids']
        original['related_jobs']=roles
        original['career_evidence']=[d for d in documents if d['qnet_code']==code]
        original['evidence_status']='sample_official_evidence_reviewed'
    (OUTPUT/'reviewed_sample_contexts.json').write_text(json.dumps(reviewed,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUTPUT/'official_career_documents.jsonl').write_text(''.join(json.dumps(d,ensure_ascii=False)+'\n' for d in documents),encoding='utf-8')
    (OUTPUT/'candidate_contexts.json').write_text(json.dumps(candidates,ensure_ascii=False,indent=2),encoding='utf-8')
    report={'completed_at':datetime.now(timezone.utc).isoformat(),'task':3,'sample_count':len(reviewed),'categories':{'T':sum(x['category']=='T' for x in reviewed),'S':sum(x['category']=='S' for x in reviewed)},'official_evidence_documents':len(documents),'summaries_reviewed':len(reviewed),'normalized_related_role_count':sum(len(x['related_jobs']) for x in reviewed),'missing_official_sections':[{'name':x['name'],'sections':x['missing_official_sections']} for x in reviewed if x['missing_official_sections']],'remaining_candidate_evidence_pending':sum(x['evidence_status']=='career_source_collection_pending' for x in candidates),'fixed_interest_assignments':0,'llm_agent_implemented':False,'database_changed':False,'github_pushed':False,'reviewer':'assistant; not institution certification or human team review'}
    (OUTPUT/'step3_completion_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True,indent=2))


if __name__=='__main__':
    prepare_reviewed_samples()
