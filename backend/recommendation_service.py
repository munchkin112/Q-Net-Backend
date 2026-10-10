"""저장된 프로필로 조회 도구를 실행하고 LLM 선정 결과를 검증한다.

인증·프로필 읽기·API 응답 저장은 다음 작업에서 담당한다.
"""
from typing import Literal

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend import settings  # 실행 위치와 관계없이 backend/.env를 읽는다.
from backend.recommendation_prompts import (
    RECOMMENDATION_MODEL, RECOMMENDATION_TEMPERATURE,
)
from backend.recommendation_tools import RECOMMENDATION_TOOLS

MAX_MODEL_CALLS = 5
MAX_TOOL_CALLS = 6
MAX_REPAIR = 1
MODEL_TIMEOUT_SECONDS = 30
EXECUTION_BUDGET_SECONDS = 120


class RecommendationError(RuntimeError):
    """빈 결과와 구분할 내부 오류 코드다. 원본 연결·인증 정보는 노출하지 않는다."""
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class SelectionValidationError(ValueError):
    """최종 결과 검증의 원인을 제한된 오류 유형으로 구분한다."""
    def __init__(self, error_type: str, message: str):
        super().__init__(message)
        self.error_type = error_type


class Evidence(BaseModel):
    model_config = ConfigDict(extra='forbid')
    document_id: str = Field(min_length=1)
    quote: str = Field(min_length=1, max_length=1000)


class SelectedCertificate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    certificate_id: str
    reason: str = Field(min_length=1, max_length=1000)
    profile_factors: list[str] = Field(max_length=20)
    evidence: list[Evidence] = Field(min_length=1, max_length=10)


class Selection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['completed', 'no_results']
    items: list[SelectedCertificate] = Field(max_length=10)


def validate_selection(content: str, candidates: dict, profile: dict, searched: bool) -> dict:
    """실제 조회 ID·중복·인용·프로필 항목을 확인한다. 의미 적합성은 별도 평가가 필요하다."""
    if not searched:
        raise SelectionValidationError('missing_search', '최종 응답 전에 search_certificates로 실제 후보를 조회하세요.')
    try:
        selection = Selection.model_validate_json(content)
    except (ValidationError, TypeError):
        raise SelectionValidationError('invalid_schema', 'JSON 형식·필드·최대 10개·인용 필수 조건을 확인하세요.') from None
    if (selection.status == 'completed') != bool(selection.items):
        raise SelectionValidationError('status_mismatch', 'status와 items 개수를 일치시키세요.')
    selected_ids = set()
    for item in selection.items:
        if item.certificate_id not in candidates:
            raise SelectionValidationError('unknown_candidate', '조회된 후보의 실제 ID를 선택하세요.')
        if item.certificate_id in selected_ids:
            raise SelectionValidationError('duplicate_candidate', '후보 ID를 중복 없이 선택하세요.')
        selected_ids.add(item.certificate_id)
        candidate = candidates[item.certificate_id]
        documents = {document['document_id']: document for document in candidate['evidence_documents']}
        for evidence in item.evidence:
            document = documents.get(evidence.document_id)
            if not document:
                raise SelectionValidationError('wrong_source', '같은 후보의 실제 document_id를 사용하세요.')
            if not evidence.quote.strip() or evidence.quote not in document['content']:
                raise SelectionValidationError('quote_mismatch', '원문 그대로의 연속된 인용을 사용하세요.')
        for factor in item.profile_factors:
            if factor not in profile or profile[factor] is None or profile[factor] == '' or profile[factor] == []:
                raise SelectionValidationError('unknown_profile_factor', '실제로 값이 있는 프로필 항목만 사용하세요.')
    return selection.model_dump()


def validate_recommendation_input(profile: dict, interest_codes: list[str]) -> None:
    """저장된 프로필과 서비스 관심 코드만 받는다. 응시자격을 판단하지 않는다."""
    if not isinstance(profile, dict) or not profile:
        raise ValueError('저장된 프로필이 필요합니다.')
    if not isinstance(interest_codes, list) or not interest_codes or len(interest_codes) > 24:
        raise ValueError('관심 분야를 선택하세요.')
    if any(not isinstance(code, str) or code not in [f'{number:02}' for number in range(1, 25)] for code in interest_codes):
        raise ValueError('관심 분야 코드는 01~24입니다.')
    if len(set(interest_codes)) != len(interest_codes):
        raise ValueError('관심 분야를 중복 없이 선택하세요.')


def run_recommendation(profile: dict, interest_codes: list[str], *, model=None, tools=None) -> dict:
    """서버가 읽은 프로필을 LangGraph에 전달하고 검증된 결과 또는 구분된 오류를 반환한다."""
    # 그래프가 검증 함수를 재사용하므로 함수 안에서 가져와 순환 import를 피한다.
    from backend.recommendation_graph import create_recommendation_graph, GRAPH_RECURSION_LIMIT

    validate_recommendation_input(profile, interest_codes)
    available_tools = RECOMMENDATION_TOOLS if tools is None else tools
    if model is None:
        model = ChatOpenAI(model=RECOMMENDATION_MODEL, temperature=RECOMMENDATION_TEMPERATURE,
                           timeout=MODEL_TIMEOUT_SECONDS, max_retries=0)
    graph = create_recommendation_graph(model, available_tools)
    state = graph.invoke({'profile': profile, 'interest_codes': interest_codes},
                         {'recursion_limit': GRAPH_RECURSION_LIMIT})
    if state['status'] == 'failed':
        error = RecommendationError(state['error']['code'], state['error']['cause'])
        error.diagnostics = {key: state[key] for key in ['errors', 'error_count', 'retry_count',
                             'repair_count', 'model_call_count', 'tool_call_count', 'node_history']}
        raise error
    return state['result']
