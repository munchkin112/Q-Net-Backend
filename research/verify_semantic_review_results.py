"""직무 요약 검토 자료의 식별·해시·역할 근거·제외·관심 표본을 확인한다."""
import hashlib
import json
from collections import Counter

from research.collect_all_career_contexts import OUTPUT, save_json
from research.prepare_semantic_review_results import HELD_CODES, prepare_semantic_review_results


def verify_semantic_review_results() -> None:
    """단순 구조 검사는 의미 검토와 구별하고 승인 파일의 재실행 안정성도 확인한다."""
    original = json.loads((OUTPUT / 'candidate_contexts.json').read_text(encoding='utf-8'))
    before_raw = (OUTPUT / 'candidate_contexts.json').read_bytes()
    before_documents = (OUTPUT / 'combined_career_documents.jsonl').read_bytes()
    ready_path = OUTPUT / 'reviewed_recommendation_contexts.json'
    before_ready = ready_path.read_bytes()
    prepare_semantic_review_results()
    assert before_raw == (OUTPUT / 'candidate_contexts.json').read_bytes()
    assert before_documents == (OUTPUT / 'combined_career_documents.jsonl').read_bytes()
    assert before_ready == ready_path.read_bytes(), '재실행 시 승인 데이터가 달라짐'
    decisions = json.loads((OUTPUT / 'step5_semantic_decisions.json').read_text(encoding='utf-8'))
    ready = json.loads(ready_path.read_text(encoding='utf-8'))
    documents = [json.loads(line) for line in before_documents.decode('utf-8').splitlines() if line]
    by_code = {item['qnet_code']: item for item in original}
    by_doc = {doc['document_id']: doc for doc in documents}
    assert len(by_code) == len(original) == len(decisions) == 613
    assert len(by_doc) == len(documents) == 1637
    for doc in documents:
        assert hashlib.sha256(doc['content'].encode()).hexdigest() == doc['content_sha256']
        assert doc['certificate_id'] == by_code[doc['qnet_code']]['certificate_id']
    for item in decisions:
        assert item['certificate_id'] == by_code[item['qnet_code']]['certificate_id']
    for item in ready:
        assert item['qnet_code'] not in HELD_CODES
        assert item['summary'] and '\n' not in item['summary']
        assert item['interest_category_codes'] is None
        for source_id in item['summary_source_ids']:
            assert by_doc[source_id]['qnet_code'] == item['qnet_code']
        for reference in item['summary_evidence']:
            assert reference['quote'] == by_doc[reference['document_id']]['content']
        for role in item['related_jobs']:
            assert all(source_id in by_doc for source_id in role['source_ids'])
            assert any(role['evidence_anchor'] in by_doc[source_id]['content'] for source_id in role['source_ids'])
    samples = json.loads((OUTPUT / 'reviewed_sample_contexts.json').read_text(encoding='utf-8'))
    by_ready = {item['qnet_code']: item for item in ready}
    for sample in samples:
        assert sample['summary'] == by_ready[sample['qnet_code']]['summary']
        assert sample['related_jobs'] == by_ready[sample['qnet_code']]['related_jobs']
    coverage = json.loads((OUTPUT / 'step5_reviewed_interest_coverage.json').read_text(encoding='utf-8'))
    assert len(coverage['coverage']) == 24 and not coverage['is_official_ncs_mapping']
    for row in coverage['coverage']:
        codes = [item['qnet_code'] for item in row['candidates']]
        assert len(codes) == len(set(codes)) <= 10
        assert all(code in by_ready for code in codes)
    rejected = json.loads((OUTPUT / 'step5_rejected_llm_interest_coverage.json').read_text(encoding='utf-8'))
    assert rejected['decision'] == 'rejected'
    result = {'passed': True, 'certificates': 613, 'source_documents_hash_checked': len(documents),
              'approved_summaries': len(ready), 'status_counts': dict(Counter(item['review_status'] for item in decisions)),
              'reviewed_roles': sum(len(item['related_jobs']) for item in ready), 'interest_choices_checked': 24,
              'raw_sources_preserved': True, 'idempotent': True, 'database_changed': False, 'github_pushed': False}
    save_json(OUTPUT / 'step5_semantic_verification.json', result)
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    verify_semantic_review_results()
