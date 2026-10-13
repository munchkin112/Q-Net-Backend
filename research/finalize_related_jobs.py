"""직접 원문 대조한 역할 결정을 기록한다. 모델 결과를 자동 승인하는 수집기는 아니다."""
import json
from datetime import datetime, timezone

from research.review_related_jobs import DATA, NOTE, validate_audit

# 2026-10-10에 모델 제안과 원문을 직접 읽고 좁히거나 보완한 표현이다.
# 새 모델 결과로 재실행할 때는 아래 승인 파일을 덮어쓰지 말고 다시 검토한다.
CORRECTIONS = {
    '0060': '산업용 기계 기술업무 담당', '0094': '금속제련 기술개발 담당',
    '0551': '섬유 염색·가공 기술업무 담당', '0872': '공정설계·기계생산 기술업무 담당',
    '1938': '생태계 관리·복원 담당', '2035': '설비 예방·사후 정비 담당',
    '2441': '화재 원인 조사·판별 담당', '3643': '한복 생산·품질 관리 담당',
    '7970': '화약류 취급·발파 보조 담당', '9545': '멀티미디어 콘텐츠 기획·제작 담당',
    '1027': '하이브리드 자동차 부품 설계·성능평가 담당',
    '1988': '생물 분류·조사 담당', '1989': '생물 분류·조사 담당',
    '2971': '음식 조리·급식 관리 담당', '2973': '음식 조리·급식 관리 담당',
    '2974': '음식 조리·급식 관리 담당', '3170': '보일러 시공·취급 관리 담당',
    '3924': '미용 업무 담당', '3925': '이용 업무 담당',
    '6910': '선박 도면 작성 담당', '7834': '타워크레인 운전 담당',
    '9500': '노동관계 행정업무 담당', '9640': '관세 분류·세액 계산 담당',
    '9723': '행정 서류 작성·제출 담당', '9737': '산업재산권 상담·관리 담당',
    '9754': '청소년 보호·생활지도 담당', '9755': '청소년 보호·생활지도 담당',
    '9758': '기술 진단·지도 담당', '9759': '기술 진단·지도 담당',
}
for code in ('9696', '9697', '9698', '9699', '9700', '9728'):
    CORRECTIONS[code] = '농수산물 경매 업무 담당'


def record_decisions() -> None:
    """이번에 직접 대조한 모델 제안의 원문 전체와 승인·수정·보류 이유를 보관한다."""
    target = DATA / 'assistant_related_role_decisions_20261010.json'
    if target.exists():
        raise ValueError('기존 승인 결정을 덮어쓸 수 없음')
    model_report = json.loads((DATA / 'related_jobs_model_review_20261010.json').read_text(encoding='utf-8'))
    approved = {item['qnet_code']: item for item in json.loads((DATA / 'reviewed_recommendation_contexts.json').read_text(encoding='utf-8'))}
    original = {item['qnet_code']: item for item in json.loads((DATA / 'candidate_contexts.json').read_text(encoding='utf-8'))}
    reviews = model_report['reviews']
    expected = {code for code, item in approved.items() if not item['related_jobs']}
    if len(reviews) != len(expected) or {item['qnet_code'] for item in reviews} != expected:
        raise ValueError('직접 검토 대상 누락·중복')
    decisions = {}
    reviewed_at = datetime.now(timezone.utc).isoformat()
    for review in reviews:
        code = review['qnet_code']
        item = approved[code]
        documents = {doc['document_id']: doc for doc in original[code]['career_evidence']}
        source_hashes = {identifier: documents[identifier]['content_sha256'] for identifier in item['summary_source_ids']}
        roles = []
        reason = '모델 제안 역할의 업무 범위를 원문과 직접 대조함. 변형된 모델 인용은 승인하지 않고 원문 전체를 근거로 사용함.'
        if code == '0622':
            reason = '보관한 공식 개요는 컴퓨터 산업·인력 양성 배경이며 구체적 수행업무가 없어 직업 역할을 추정하지 않음.'
        elif code in CORRECTIONS:
            name = CORRECTIONS[code]
            identifier = item['summary_source_ids'][0]
            roles.append({'name': name, 'source_ids': [identifier],
                          'evidence_anchor': documents[identifier]['content'],
                          'name_type': 'normalized_task_role', 'note': NOTE})
            reason = '모델 제안의 과도한 범위·잘못된 분야 표현 또는 누락을 공식 원문 전체와 직접 대조해 수정·보완함.'
        else:
            if validate_audit(review, review['audit']):
                raise ValueError('독립 검토 형식 불일치')
            for audit in review['audit']['roles']:
                if not audit['supported']:
                    continue
                role = review['roles'][audit['index']]
                identifier = role['document_id']
                if identifier not in source_hashes:
                    raise ValueError('다른 종목 또는 미검토 출처 연결')
                roles.append({'name': role['name'], 'source_ids': [identifier],
                              'evidence_anchor': documents[identifier]['content'],
                              'name_type': 'normalized_task_role', 'note': NOTE})
        for role in roles:
            if 'family_common' in item['usage_restrictions']:
                role['name'] += ' (공통 직무)'
                role['note'] += '; 종목군의 공통 자료이며 해당 등급·세부 분야만의 고유 업무를 입증하지 않음'
            if 'former_name_in_source' in item['usage_restrictions']:
                role['note'] += '; 원문에 이전 종목명이 포함됨'
            if 'legal_claims_excluded' in item['usage_restrictions']:
                role['note'] += '; 현재 법적 권한·개업·선임 요건 판정에 사용하지 않음'
        decisions[code] = {'qnet_code': code, 'source_hashes': source_hashes, 'related_jobs': roles,
                           'status': 'reviewed_roles_available' if roles else 'reviewed_no_supported_role',
                           'method': 'gpt-4o-mini_draft_and_separate_audit_then_codex_assistant_source_comparison',
                           'reviewed_at': reviewed_at, 'reason': reason,
                           'model_validation_errors_preserved': review['validation_errors'],
                           'assistant_correction': code in CORRECTIONS,
                           'model_empty_or_rejected_preserved': not review['roles'] or any(not a['supported'] for a in review['audit']['roles'])}
    target.write_text(json.dumps(decisions, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'reviewed': len(decisions), 'with_roles': sum(bool(item['related_jobs']) for item in decisions.values()),
                      'roles': sum(len(item['related_jobs']) for item in decisions.values()), 'database_changed': False}))


if __name__ == '__main__':
    record_decisions()
