"""서비스 관심 선택지와 승인된 추천 근거를 조회한다. 최종 선정은 하지 않는다."""
from psycopg import Connection

MAX_CANDIDATE_LIMIT = 30
MAX_SEARCH_TERMS = 8
MAX_TERM_LENGTH = 60
MAX_SEARCH_OFFSET = 10000


def list_recommendation_interests(connection: Connection) -> list[dict]:
    """서비스 관심 선택지의 설명·예시를 코드 순으로 반환한다."""
    rows = connection.execute(
        'SELECT code,payload FROM recommendation_interest_categories ORDER BY code'
    ).fetchall()
    return [row['payload'] for row in rows]


def search_recommendation_candidates(
    connection: Connection, interest_codes: list[str], search_terms: list[str],
    limit: int = 20, offset: int = 0,
) -> dict:
    """승인 직무 요약·원문에서 검색어를 찾는다. 분야 코드는 선택 검증에만 사용한다."""
    if not 1 <= len(interest_codes) <= 24 or len(set(interest_codes)) != len(interest_codes):
        raise ValueError('관심 분야는 중복 없이 1~24개여야 합니다.')
    if not 1 <= len(search_terms) <= MAX_SEARCH_TERMS:
        raise ValueError('검색어는 1~8개여야 합니다.')
    terms = []
    for term in search_terms:
        value = term.strip()
        if not value or len(value) > MAX_TERM_LENGTH:
            raise ValueError('검색어는 공백 제외 1~60자여야 합니다.')
        if value not in terms:
            terms.append(value)
    if not 1 <= limit <= MAX_CANDIDATE_LIMIT or not 0 <= offset <= MAX_SEARCH_OFFSET:
        raise ValueError('조회 개수는 1~30개, 조회 시작 위치는 0~10000이어야 합니다.')
    choices = list_recommendation_interests(connection)
    by_code = {item['code']: item for item in choices}
    if any(code not in by_code for code in interest_codes):
        raise ValueError('존재하지 않는 서비스 관심 분야 코드입니다.')

    conditions = []
    parameters = []
    for term in terms:
        # strpos는 문자열 그대로 검색한다. '%'와 '_'도 와일드카드로 해석하지 않는다.
        # SQL 문장은 고정 구문만 조합하고 모든 검색어는 매개변수로 전달한다.
        conditions.append('''(strpos(lower(c.name), lower(%s)) > 0
            OR strpos(lower(r.payload->>'summary'), lower(%s)) > 0
            OR EXISTS (SELECT 1 FROM jsonb_array_elements(r.payload->'evidence_documents') AS document
                       WHERE strpos(lower(document->>'content'), lower(%s)) > 0))''')
        parameters.extend([term, term, term])
    query = '''SELECT r.payload FROM certificate_recommendation_contexts AS r
        JOIN certificates AS c ON c.id=r.certificate_id AND c.qnet_code=r.qnet_code
        WHERE r.payload->>'review_status' IN
            ('assistant_reviewed_summary_only','assistant_reviewed_summary_and_roles')
        AND jsonb_array_length(r.payload->'evidence_documents') > 0
        AND (''' + ' OR '.join(conditions) + ''')
        ORDER BY c.qnet_code LIMIT %s OFFSET %s'''
    # 한 개 더 읽어 다음 페이지가 있는지 확인한다. 순서는 코드순이며 추천 순위가 아니다.
    parameters.extend([limit + 1, offset])
    rows = connection.execute(query, parameters).fetchall()
    has_more = len(rows) > limit
    return {
        'status': 'found' if rows else 'empty_search',
        'selected_interest_categories': [by_code[code] for code in interest_codes],
        'search_terms': terms, 'selection_scope': 'searched_candidates_only',
        'candidates': [row['payload'] for row in rows[:limit]],
        'returned_count': min(len(rows), limit), 'has_more': has_more,
        'next_offset': offset + limit if has_more else None,
        'message': '검색된 후보이며 관심 분야 적합성·최종 추천은 아직 판단하지 않았습니다.'
                   if rows else '현재 검색어·조회 위치에서 후보를 찾지 못했습니다. 전체 후보 없음과 구분해주세요.',
    }
