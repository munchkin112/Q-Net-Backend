"""의미 검토 결과를 원문과 분리하고 사용 범위·보류 사유를 기록한다."""
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone

from research.collect_all_career_contexts import OUTPUT, save_json
from research.review_recommendation_semantics import get_review_documents

# 원문과 요약을 직접 대조하며 발견한 문제다. 모델이 통과시켜도 이 결정을 우선한다.
HELD_CODES = {
    '0670': '도시계획 설명이 지적기술사와 거의 동일함. 조경 고유 업무 근거 재확인 필요',
    '0690': '도시계획 설명이 조경기술사와 거의 동일함. 지적 고유 업무 근거 재확인 필요',
    '1104': '금속재료 종목에 선광·제련·정련 설명이 있어 종목별 업무 범위 재확인 필요',
    '0210': '개요는 2005~2006년 종목 통합 이력이며 현재 직무 설명을 뒷받침하지 않음',
    '1512': '개요는 제도 도입·인력 부족 배경 중심이며 구체적인 수행직무가 부족함',
    '7873': '확보 자료가 진출기관·1990년대 수요 전망 중심이며 직무 설명 근거 부족',
    '9501': '경비업 전체 종류의 설명을 일반경비지도사의 고유 수행직무로 사용할 수 없음',
    '9660': '양성과정·시험 합격에 따른 자격 부여 조건을 직무 설명으로 사용할 수 없음',
    '9663': '호텔 등급에 따른 직무 범위가 포함돼 현재 등급·법적 업무 범위 재확인 필요',
    '9705': '1차공통은 경영지도사 시험 구분이며 독립된 추천 자격으로 표시하지 않음',
    '9729': '1차공통은 기술지도사 시험 구분이며 독립된 추천 자격으로 표시하지 않음',
}
SCOPE_GROUPS = {
    'family_common': {'9696','9697','9698','9699','9700','9728','9701','9702','9703','9704','9758','9759',
                      '9711','9712','9713','9714','9715','9716','9739','9740','9741','9750','9751','9752','9753','9754','9755',
                      '1900','1910','2900','2910','1988','1989'},
    'former_name_in_source': {'2035','7931','7932','6300','6835'},
    'legal_claims_excluded': {'2121','7871','1390','2340','9500','9641','9640','9721','9722','9723','9737'},
}


def prepare_semantic_review_results() -> None:
    """원문은 보존하고 승인 요약·모델 보류·직업 근거 미확인을 별도로 저장한다."""
    candidates = json.loads((OUTPUT / 'candidate_contexts.json').read_text(encoding='utf-8'))
    model_report = json.loads((OUTPUT / 'step5_llm_semantic_reviews.json').read_text(encoding='utf-8'))
    model_reviews = {review['qnet_code']: review for batch in model_report['batches'] for review in batch['reviews']}
    samples = {item['qnet_code']: item for item in json.loads((OUTPUT / 'reviewed_sample_contexts.json').read_text(encoding='utf-8'))}
    # 직접 읽고 원문과 대조한 모델 요약만 승인 명단에 포함한다.
    approval_path = OUTPUT / 'assistant_summary_approvals.json'
    approvals = json.loads(approval_path.read_text(encoding='utf-8')) if approval_path.exists() else {}
    correction_path = OUTPUT / 'assistant_summary_corrections.json'
    corrections = json.loads(correction_path.read_text(encoding='utf-8')) if correction_path.exists() else {}
    role_path = OUTPUT / 'assistant_related_role_decisions_20261010.json'
    role_decisions = json.loads(role_path.read_text(encoding='utf-8')) if role_path.exists() else {}
    result = []
    ready = []
    for item in candidates:
        code = item['qnet_code']
        review = model_reviews.get(code)
        scopes = [name for name, codes in SCOPE_GROUPS.items() if code in codes]
        decision = {'certificate_id': item['certificate_id'], 'qnet_code': code, 'name': item['name'],
                    'category': item['category'], 'summary': None, 'summary_source_ids': [],
                    'summary_evidence': [], 'related_jobs': [], 'usage_restrictions': scopes,
                    'interest_category_codes': None, 'interest_assignment_status': 'not_an_official_mapping',
                    'model_validation_errors': review.get('validation_errors', []) if review else [],
                    'model_issues': review.get('issues', []) if review else [], 'database_ready': False}
        if code in HELD_CODES:
            decision.update(review_status='held', reason=HELD_CODES[code])
        elif code in samples:
            sample = samples[code]
            decision.update(summary=sample['summary'], summary_source_ids=sample['summary_source_ids'],
                            related_jobs=sample['related_jobs'], review_status='assistant_reviewed_summary_and_roles')
        elif not item.get('career_evidence'):
            decision.update(review_status='missing_evidence', reason='확인한 공식 경로에 직무 근거 없음')
        elif code in corrections:
            documents = get_review_documents(item)
            decision.update(summary=corrections[code], summary_source_ids=[doc['document_id'] for doc in documents],
                            summary_evidence=[{'document_id': doc['document_id'], 'quote': doc['content']} for doc in documents],
                            review_status='assistant_reviewed_summary_only', related_jobs_status='unavailable_not_inferred',
                            correction_method='assistant_rewritten_against_full_official_duties')
        elif review and review.get('summary') and approvals.get(code) == hashlib.sha256(review['summary'].encode()).hexdigest():
            # 모델이 인용을 바꾸어 쓴 경우도 보관한다. 직접 요약 사실을 대조한 원문 전체로 근거를 교체한다.
            documents = get_review_documents(item)
            decision.update(summary=review['summary'], summary_source_ids=[doc['document_id'] for doc in documents],
                            summary_evidence=[{'document_id': doc['document_id'], 'quote': doc['content']} for doc in documents],
                            review_status='assistant_reviewed_summary_only', related_jobs_status='unavailable_not_inferred')
        else:
            decision.update(review_status='review_pending', reason='모델 검토 또는 직접 요약 대조 미완료')
        if decision['summary']:
            by_id = {doc['document_id']: doc for doc in item['career_evidence']}
            # 기존 8개 직접 검토 표본은 유지하고, 원문 해시를 대조한 추가 검토만 연결한다.
            role_decision = role_decisions.get(code)
            if role_decision and code not in samples:
                hashes = {identifier: by_id[identifier]['content_sha256'] for identifier in decision['summary_source_ids']}
                if role_decision['source_hashes'] != hashes:
                    raise ValueError('관련 역할 검토 이후 원문 변경')
                decision['related_jobs'] = role_decision['related_jobs']
                decision['related_jobs_review'] = {key: role_decision[key] for key in
                    ('status', 'method', 'reviewed_at', 'reason')}
                if decision['related_jobs']:
                    decision['review_status'] = 'assistant_reviewed_summary_and_roles'
            assert all(source_id in by_id for source_id in decision['summary_source_ids'])
            for role in decision['related_jobs']:
                assert all(source_id in by_id for source_id in role['source_ids'])
                assert any(role['evidence_anchor'] in by_id[source_id]['content'] for source_id in role['source_ids'])
            decision['sources'] = [{key: doc.get(key) for key in ['document_id','source_url','retrieved_at','content_sha256','evidence_scope','law_effective_date']}
                                   for doc in item['career_evidence'] if doc['document_id'] in decision['summary_source_ids']]
            decision['database_ready'] = True
            decision['database_ready_scope'] = 'summary_and_evidence; jobs_only_when_reviewed'
            ready.append(decision)
        decision['full_card_ready'] = bool(decision['summary'] and decision['related_jobs'])
        result.append(decision)
    counts = Counter(item['review_status'] for item in result)
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'stage': 5,
              'scope': '직무 중심 요약·기존 직업 근거·공통 직무 적용. 최신 법적 권한·응시조건 검증 제외',
              'certificates': len(result), 'model_reviewed': len(model_reviews), 'review_status_counts': dict(counts),
              'approved_summaries': len(ready), 'with_reviewed_roles': sum(item['full_card_ready'] for item in result),
              'reviewed_role_count': sum(len(item['related_jobs']) for item in result),
              'additional_role_reviews': len(role_decisions),
              'held': [{'qnet_code': item['qnet_code'], 'name': item['name'], 'reason': item.get('reason')} for item in result if item['review_status']=='held'],
              'raw_documents_preserved': True, 'database_changed': False, 'github_pushed': False,
              'whole_raw_corpus_semantic_review_complete': False,
              'semantic_decisions_complete_for_current_summary_scope': not counts.get('review_pending', 0),
              'note': '직무 요약 승인과 직업 근거 승인은 구별한다. 빈 related_jobs를 확인된 직업으로 표시하지 않는다. 추가 역할은 모델 추출·독립 검토·원문 인용 검사 후 직접 대조했다.'}
    save_json(OUTPUT / 'step5_semantic_decisions.json', result)
    save_json(OUTPUT / 'reviewed_recommendation_contexts.json', ready)
    save_json(OUTPUT / 'step5_semantic_review_report.json', report)
    sample_path = OUTPUT / 'interest_coverage_review_samples.json'
    if sample_path.exists():
        sample_codes = json.loads(sample_path.read_text(encoding='utf-8'))
        interests = json.loads((OUTPUT / 'interest_categories.json').read_text(encoding='utf-8'))
        assert set(sample_codes) == {interest['code'] for interest in interests}
        by_code = {item['qnet_code']: item for item in ready}
        coverage = []
        for interest in interests:
            codes = sample_codes[interest['code']]
            assert len(codes) <= 10 and len(codes) == len(set(codes))
            assert all(code in by_code for code in codes)
            coverage.append({'code': interest['code'], 'name': interest['name'], 'checked_sample_count': len(codes),
                             'review_status': 'assistant_reviewed_against_official_duties',
                             'candidates': [by_code[code] for code in codes]})
        save_json(OUTPUT / 'step5_reviewed_interest_coverage.json', {
            'classification_type': 'project_interest_review_sample', 'is_official_ncs_mapping': False,
            'is_exhaustive_candidate_count': False, 'coverage': coverage,
            'note': '직접 직무 근거를 대조한 표본이다. 서비스의 고정 분류·개인별 추천·순위가 아니다. 1~2개 표본인 분야에 다른 자격이 없다는 결론도 아니다.'})
    with (OUTPUT / 'step5_semantic_review_inventory.csv').open('w', encoding='utf-8-sig', newline='') as handle:
        fields = ['qnet_code','name','review_status','summary','database_ready','full_card_ready','reason']
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(result)
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    prepare_semantic_review_results()
