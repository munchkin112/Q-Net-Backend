"""승인된 직무로 종목별 공통 추천 대상과 연관 직무를 구성한다."""
from uuid import UUID

from backend.db.connection import database_connection

MAX_AUDIENCE_ITEMS = 3
APPROVED_STATUSES = {'assistant_reviewed_summary_only', 'assistant_reviewed_summary_and_roles'}


def get_career_context(certificate_id: UUID) -> dict | None:
    """동일 종목 ID·코드의 승인 자료만 읽는다. 저장 자료가 없으면 빈 상태를 반환한다."""
    with database_connection() as connection:
        row = connection.execute('''SELECT c.id,c.qnet_code,c.name,c.category,r.payload
            FROM certificates c LEFT JOIN certificate_recommendation_contexts r
            ON r.certificate_id=c.id AND r.qnet_code=c.qnet_code WHERE c.id=%s''',
            (certificate_id,)).fetchone()
    if row is None:
        return None
    if row['payload'] is not None:
        return row['payload']
    return {'certificate_id': str(row['id']), 'qnet_code': row['qnet_code'],
            'name': row['name'], 'category': row['category'], 'related_jobs': [],
            'evidence_documents': [], 'review_status': 'unavailable'}


def build_career_information(context: dict) -> dict:
    """직무명을 새로 생성하지 않는다. 공통 설명은 해당 업무에 대한 관심을 표현한다."""
    jobs = []
    audience = []
    documents = {doc['document_id']: doc for doc in context.get('evidence_documents', [])}
    used_ids = set()
    if context.get('review_status') in APPROVED_STATUSES:
        for job in context.get('related_jobs', []):
            source_ids = job.get('source_ids', [])
            if not source_ids or any(source_id not in documents for source_id in source_ids):
                raise ValueError('직무 근거가 같은 종목의 공식 원문에 연결되어야 합니다.')
            anchor = job.get('evidence_anchor')
            if anchor and not any(anchor in documents[source_id]['content'] for source_id in source_ids):
                raise ValueError('직무 근거 인용을 원문에서 확인할 수 없습니다.')
            if any(not documents[source_id].get('source_url', '').startswith(('https://', 'http://'))
                   for source_id in source_ids):
                raise ValueError('공식 출처 URL을 확인할 수 없습니다.')
            if any(existing['name'] == job['name'] for existing in jobs):
                continue
            jobs.append({'name': job['name'], 'source_ids': source_ids,
                         'note': job.get('note', '공식 수행업무를 정리한 역할명입니다.')})
            used_ids.update(source_ids)
            if len(audience) < MAX_AUDIENCE_ITEMS:
                audience.append({'text': f"{job['name']} 관련 업무에 관심 있는 분",
                                 'source_ids': source_ids})
    sources = [{'document_id': doc['document_id'], 'source_url': doc['source_url'],
                'retrieved_at': doc.get('retrieved_at'), 'evidence_scope': doc.get('evidence_scope')}
               for doc in documents.values() if doc['document_id'] in used_ids]
    return {'certificate_id': str(context['certificate_id']), 'status': 'available' if jobs else 'unavailable',
            'recommended_for': audience, 'related_jobs': jobs, 'sources': sources,
            'usage_restrictions': context.get('usage_restrictions', []),
            'message': '종목별 공통 직무 안내이며 취업·응시자격·법적 업무권한을 보장하지 않습니다.'
                       if jobs else '검토된 직무 근거가 없어 추천 대상·직무를 추정하지 않았습니다.'}
