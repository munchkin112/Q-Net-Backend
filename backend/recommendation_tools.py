"""LLM이 선택하고 Python이 실행하는 읽기 전용 추천 자료 조회 도구다."""
import psycopg
from langchain_core.tools import tool
from pydantic import BaseModel, Field, ConfigDict

from backend.db.connection import database_connection
from backend.db.recommendation_repository import (
    list_recommendation_interests, search_recommendation_candidates,
)


class RecommendationDataUnavailable(RuntimeError):
    """DB 조회 실패와 빈 후보와 구별하고 외부에 연결 정보를 노출하지 않는다."""
    def __init__(self, message: str, *, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


class CandidateSearchInput(BaseModel):
    """LLM의 도구 인자를 제한한다. 관심 분야는 공식 자격증 분류 코드가 아니다."""
    model_config = ConfigDict(extra='forbid')
    interest_codes: list[str] = Field(min_length=1, max_length=24, description='사용자가 선택한 서비스 관심 분야 코드')
    search_terms: list[str] = Field(min_length=1, max_length=8, description='분야 설명·활동 예시에서 만든 구체적인 직무 검색어')
    limit: int = Field(default=20, ge=1, le=30, description='후보 조회 개수. 최종 추천 개수와 별개')
    offset: int = Field(default=0, ge=0, le=10000, description='동일 검색어로 다음 후보 묶음을 조회할 시작 위치')


@tool
def list_interest_categories() -> dict:
    """서비스 관심 분야 24개와 설명·활동 예시를 조회한다.

    분야의 의미를 확인하고 후보 검색어를 구성할 때 사용한다.
    공식 NCS 분류 결과나 자격증별 고정 매핑을 반환하지 않는다.
    """
    try:
        with database_connection() as connection:
            connection.execute('SET TRANSACTION READ ONLY')
            connection.execute("SET LOCAL statement_timeout = '20s'")
            choices = list_recommendation_interests(connection)
    except (psycopg.Error, RuntimeError) as error:
        retryable = isinstance(error, (psycopg.OperationalError, psycopg.errors.QueryCanceled))
        raise RecommendationDataUnavailable('관심 분야 DB 조회에 실패했습니다.', retryable=retryable) from None
    return {'status': 'available', 'items': choices, 'total_count': len(choices),
            'classification_type': 'project_interest', 'is_official_ncs_mapping': False}


@tool(args_schema=CandidateSearchInput)
def search_certificates(
    interest_codes: list[str], search_terms: list[str], limit: int = 20, offset: int = 0,
) -> dict:
    """관심 분야 탐색에 사용할 자격증 후보와 승인 요약·직업·공식 원문을 DB에서 조회한다.

    검색어는 관심 분야의 실제 활동과 관련된 구체적 단어를 사용한다.
    예: 정보통신 분야에서 '소프트웨어', '프로그래밍', '정보시스템'을 검색한다.
    interest_codes는 사용자 선택 확인용이며 그 번호로 자격증을 고정 분류하지 않는다.
    검색어 중 하나라도 이름·요약·근거 원문에 포함되면 후보가 되므로 적합성은 원문으로 판단한다.
    무관한 후보나 empty_search는 검색어를 조정할 수 있다. 전체 관련 자격증 없음으로 단정하지 않는다.
    has_more가 true이면 같은 검색어와 next_offset으로 다음 후보를 조회할 수 있다.
    결과는 코드순이며 순위·응시 가능 판정·최종 추천이 아니다. 빈 related_jobs를 추측해 채우지 않는다.
    DB 실패는 오류로 발생하며 빈 후보로 반환하지 않는다. 도구 내부에서 LLM이나 외부 API를 호출하지 않는다.
    """
    try:
        with database_connection() as connection:
            connection.execute('SET TRANSACTION READ ONLY')
            connection.execute("SET LOCAL statement_timeout = '20s'")
            return search_recommendation_candidates(connection, interest_codes, search_terms, limit, offset)
    except (psycopg.Error, RuntimeError) as error:
        retryable = isinstance(error, (psycopg.OperationalError, psycopg.errors.QueryCanceled))
        raise RecommendationDataUnavailable('추천 후보 DB 조회에 실패했습니다.', retryable=retryable) from None


RECOMMENDATION_TOOLS = [list_interest_categories, search_certificates]
