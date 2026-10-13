"""서비스 관심 분야와 LLM 판단용 후보 기초 자료를 로컬에 준비한다."""
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'research/preparation/recommendation'
# 명칭·예시는 사용자가 선택한 서비스 대분류이며 공식 자격증 분류표가 아니다.
INTEREST_CHOICES = [
 ('01','사업관리',['프로젝트 관리','해외 관리']),
 ('02','경영·회계·사무',['기획사무','총무','인사','회계']),
 ('03','금융·보험',['금융상품 개발','자산운용','보험조사']),
 ('04','교육·자연·사회과학',['평생교육','직업교육','과학연구']),
 ('05','법률·경찰·소방·교도·국방',['법률지원','보안','소방행정']),
 ('06','보건·의료',['보건지원','의료기술','임상보건']),
 ('07','사회복지·종교',['사회복지상담','보육','종교활동']),
 ('08','문화·예술·디자인·방송',['문화예술기획','시각디자인','방송제작']),
 ('09','운전·운송',['항공운송','철도운송','육상운송']),
 ('10','영업판매',['부동산서비스','일반영업','마케팅']),
 ('11','경비·청소',['시설경비','일반청소']),
 ('12','이용·숙박·여행·오락·스포츠',['관광숙박','스포츠기획']),
 ('13','음식서비스',['조리','식음료서비스']),
 ('14','건설',['건축구조','토목','건설공사관리']),
 ('15','기계',['기계설계','자동차 제조','금형공정']),
 ('16','재료',['금속재료','세라믹재료']),
 ('17','화학·바이오',['화학물질제조','바이오의약품 개발']),
 ('18','섬유·의복',['섬유제조','의류설계']),
 ('19','전기·전자',['전자기기개발','전기공사','반도체 제조']),
 ('20','정보통신',['SW엔지니어링','보안솔루션','IT컨설팅']),
 ('21','식품가공',['식품제조','음료제조']),
 ('22','인쇄·목재·가구·공예',['가구설계','제품공예']),
 ('23','환경·에너지·안전',['환경관리','신재생에너지','산업안전']),
 ('24','농림어업',['작물재배','축산','해양어업']),
]


def save_json(filename, data):
    """한국어 JSON 자료를 프로젝트 로컬에 저장한다."""
    (OUTPUT / filename).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def prepare_interest_data():
    """실제 코드·UUID를 유지하고 분야의 임의 확정 연결 없이 판단 자료를 만든다."""
    categories = [{'code': code, 'name': name, 'examples': examples, 'description': name + ' 관련 활동에 대한 관심', 'classification_type': 'project_interest', 'definition_source': 'user_confirmed_service_choices', 'is_official_ncs_certificate_mapping': False} for code, name, examples in INTEREST_CHOICES]
    catalog = json.loads((ROOT / 'research/preparation/catalog.json').read_text(encoding='utf-8'))
    with (OUTPUT / 'inventory_audit.csv').open(encoding='utf-8-sig', newline='') as handle:
        inventory = {row['qnet_code']: row for row in csv.DictReader(handle)}
    contexts = []
    for item in catalog:
        code = item['qnet_code']
        contexts.append({
            'certificate_id': inventory[code]['certificate_id'],
            'qnet_code': code, 'name': item['name'], 'category': item['category'],
            'qnet_job_context': {'job_name': item.get('job_name'), 'major_job_name': item.get('major_job_name'), 'source_url': item['source_url'], 'retrieved_at': item['last_synced_at']},
            'interest_category_codes': None,
            'interest_assignment_status': 'llm_evaluation_not_run',
            'summary': None, 'related_jobs': [], 'career_evidence': [],
            'evidence_status': 'career_source_collection_pending',
            'existing_exam_information': inventory[code]['exam_information_present'] == 'True',
            'existing_schedule_count': int(inventory[code]['schedule_count']),
        })
    policy = {
        'version': '2026-10-09', 'classification_type': 'project_interest',
        'scope': 'selection_policy_for_future_recommendation_agent; not an implemented agent',
        'input': ['selected_interest_categories', 'stored_user_profile', 'candidate_certificates_with_official_evidence'],
        'selection': {'max_items': 10, 'initial_display_count': 3, 'ranked': False, 'allow_less_than_three': True, 'no_candidates': 'no_results', 'more_button': 'expand_existing_results'},
        'rules': [
            '24개 분야는 서비스 관심 선택지이며 공식 NCS 분류 결과라고 표현하지 않는다.',
            '관심 분야 설명과 실제 자격증의 수행직무·진로 자료를 비교하여 관련성을 판단한다.',
            'Q-Net 직무분야는 참고 자료이며 서비스 관심 분야와 번호가 같다는 이유로 연결하지 않는다.',
            '분야 이름·키워드만 일치하는 자격증을 확정 추천하지 않는다. 여러 분야와 관련될 수 있다.',
            '관심 분야와 프로필을 함께 고려하여 개인별 추천 이유를 작성한다. 프로필은 자동 응시 가능 판정이 아니다.',
            '사용자 조건과의 연결 설명은 LLM 해석이고 자격증 직무·시험 사실은 공식 근거임을 구분한다.',
            '제공된 후보의 실제 certificate_id만 선택하고 중복 종목을 반환하지 않는다.',
            '이유에는 사용한 프로필 항목과 공식 근거 source_id를 연결한다.',
            '공식 직업·진로 근거가 없으면 관련 직업을 추측하지 않고 빈 배열 또는 확인 필요로 남긴다.',
            '공식 자료에 없는 응시자격·취업 보장·최신 수요 전망을 생성하지 않는다.',
            '후보가 0개이면 없음으로 안내하며 분야당 10개를 강제로 채우지 않는다.',
            '이번 준비 자료의 null 요약·빈 근거는 자료 준비 중이며 바로 추천 성공에 사용하지 않는다.'
        ],
        'python_validation': ['selected_interest_codes_exist', 'candidate_ids_exist', 'no_duplicate_certificates', 'item_count_at_most_10', 'source_ids_exist', 'profile_factors_exist'],
        'remaining_work': ['official_career_evidence_collection', 'LLM_tool_graph_implementation', 'POST /recommendations_connection'],
    }
    save_json('interest_categories.json', categories)
    save_json('candidate_contexts.json', contexts)
    save_json('recommendation_selection_policy.json', policy)
    assert len(categories) == 24
    assert {x['code'] for x in categories} == {f'{i:02d}' for i in range(1,25)}
    assert len(contexts) == len(inventory) == 613
    assert len({x['certificate_id'] for x in contexts}) == 613
    assert all(x['interest_category_codes'] is None for x in contexts)
    save_json('interest_preparation_validation.json', {'checked_at':datetime.now(timezone.utc).isoformat(),'category_count':len(categories),'candidate_count':len(contexts),'qnet_job_metadata_present':sum(bool(x['qnet_job_context']['job_name']) for x in contexts),'fixed_interest_assignments':0,'official_ncs_mapping_claims':0,'llm_execution_performed':False,'database_writes':False,'checks':'passed'})
    print('Prepared: 24 project interest choices; 613 real candidates; 0 fixed/official NCS assignments.')


if __name__ == '__main__':
    prepare_interest_data()
