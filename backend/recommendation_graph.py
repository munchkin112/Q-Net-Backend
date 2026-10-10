"""추천의 판단·도구 실행·검증·수정·오류 종료를 명시적인 엣지로 연결한다."""
import json
import time
from typing import TypedDict, Literal

from langchain_core.messages import BaseMessage, AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import START, END, StateGraph
from openai import OpenAIError, APITimeoutError, APIConnectionError
from pydantic import ValidationError

from backend.recommendation_prompts import RECOMMENDATION_SYSTEM_PROMPT, RECOMMENDATION_PROMPT_VERSION
from backend.recommendation_service import (
    validate_selection, validate_recommendation_input, SelectionValidationError, MAX_MODEL_CALLS, MAX_TOOL_CALLS,
    MAX_REPAIR, EXECUTION_BUDGET_SECONDS,
)
from backend.recommendation_tools import RecommendationDataUnavailable

MAX_RETRY = 1
MAX_CONTEXT_CHARACTERS = 60000  # 문자 수 정책이며 모델의 정확한 토큰 수를 뜻하지 않는다.
GRAPH_RECURSION_LIMIT = 60


class GraphError(TypedDict):
    code: str
    error_type: str
    node: str
    cause: str
    repair_action: str
    retryable: bool


class RecommendationState(TypedDict, total=False):
    """한 요청 안의 단기 기억. 영구 실행 기록은 이후 API/DB 저장 단계에서 담당한다."""
    profile: dict
    interest_codes: list[str]
    messages: list[BaseMessage]
    candidates: dict[str, dict]
    searched: bool
    response: AIMessage | None
    pending_calls: list[dict]
    current_call: dict | None
    seen_call_ids: list[str]
    tools_called: list[str]
    model_call_count: int
    tool_call_count: int
    retry_count: int
    repair_count: int
    error_count: int
    error: GraphError | None
    errors: list[GraphError]
    node_history: list[str]
    context_char_count: int
    started_at: float
    selection: dict | None
    result: dict | None
    status: Literal['running', 'completed', 'no_results', 'failed']


def record_error(state: RecommendationState, node: str, code: str, cause: str,
                 action: str = 'stop', retryable: bool = False, error_type: str | None = None) -> dict:
    """안전한 원인·정책만 기록한다. 원본 DB URL·키·모델 예외 문자열은 기록하지 않는다."""
    error: GraphError = {'code': code, 'error_type': error_type or code, 'node': node, 'cause': cause,
                         'repair_action': action, 'retryable': retryable}
    return {'error': error, 'errors': state['errors'] + [error], 'error_count': state['error_count'] + 1}


def route_error(state: RecommendationState) -> Literal['retry', 'repair', 'fallback']:
    """숫자와 오류 정책에 따른 분기는 Python이 결정한다."""
    error = state['error']
    if time.monotonic() - state['started_at'] >= EXECUTION_BUDGET_SECONDS:
        return 'fallback'
    if state['model_call_count'] >= MAX_MODEL_CALLS:
        return 'fallback'
    if error['retryable'] and state['retry_count'] < MAX_RETRY:
        if error['node'] == 'tools' and state['tool_call_count'] >= MAX_TOOL_CALLS:
            return 'fallback'
        return 'retry'
    if error['repair_action'] in ['repair_result', 'repair_tool_arguments'] and state['repair_count'] < MAX_REPAIR:
        return 'repair'
    return 'fallback'


def compact_tool_result(result: dict) -> dict:
    """LLM용 결정적 자료 요약이다. 공식 문단은 재작성·절단하지 않고 그대로 보존한다."""
    compacted = dict(result)
    if 'candidates' in result:
        fields = ['certificate_id', 'qnet_code', 'name', 'category', 'summary', 'summary_source_ids',
                  'related_jobs', 'usage_restrictions', 'review_status', 'related_jobs_status',
                  'usage_scope', 'evidence_documents', 'full_card_ready', 'interest_assignment_status']
        compacted['candidates'] = []
        for candidate in result['candidates']:
            compacted['candidates'].append({key: candidate[key] for key in fields if key in candidate})
    return compacted


def create_recommendation_graph(model, tools):
    """현재 프로필과 DB 조회 도구를 사용하는 요청별 그래프를 구성한다. 다른 사용자의 State를 공유하지 않는다."""
    bound_model = model.bind_tools(tools)
    tool_map = {tool.name: tool for tool in tools}

    def prepare(state: RecommendationState) -> dict:
        initial = {'messages': [], 'candidates': {}, 'searched': False, 'response': None,
                   'pending_calls': [], 'current_call': None, 'seen_call_ids': [], 'tools_called': [],
                   'model_call_count': 0, 'tool_call_count': 0, 'retry_count': 0, 'repair_count': 0,
                   'error_count': 0, 'error': None, 'errors': [], 'node_history': ['prepare'],
                   'context_char_count': 0, 'started_at': time.monotonic(),
                   'selection': None, 'result': None, 'status': 'running'}
        try:
            validate_recommendation_input(state.get('profile'), state.get('interest_codes'))
        except (ValueError, TypeError):
            initial.update(record_error(initial, 'prepare', 'invalid_input', '저장된 프로필과 관심 코드가 올바르지 않습니다.'))
            return initial
        initial['messages'] = [SystemMessage(content=RECOMMENDATION_SYSTEM_PROMPT), HumanMessage(content=json.dumps({
            'profile': state['profile'], 'interest_codes': state['interest_codes'],
            'execution_rules': '분야 설명을 확인한 뒤 실제 후보를 검색하세요. 모델 호출 최대 5회, '
                               '도구 실행 최대 6회입니다. 최종 응답은 JSON만 반환하세요. '
                               '근거는 후보의 evidence_documents에 있습니다.',
        }, ensure_ascii=False))]
        return initial

    def manage_context(state: RecommendationState) -> dict:
        update = {'node_history': state['node_history'] + ['context']}
        # 단일 탐색에서는 대화 요약 LLM을 추가하지 않는다. 도구 결과의 불필요한 메타데이터만 정리한다.
        size = sum(len(json.dumps({'content': message.content,
                                  'tool_calls': getattr(message, 'tool_calls', [])}, ensure_ascii=False))
                   for message in state['messages'])
        update['context_char_count'] = size
        if time.monotonic() - state['started_at'] >= EXECUTION_BUDGET_SECONDS:
            update.update(record_error(state, 'context', 'timeout', '추천 처리 시간 예산을 초과했습니다.'))
        elif size > MAX_CONTEXT_CHARACTERS:
            update.update(record_error(state, 'context', 'context_limit', '공식 근거를 보존한 요청이 컨텍스트 문자 제한을 초과했습니다.'))
        elif state['model_call_count'] >= MAX_MODEL_CALLS:
            update.update(record_error(state, 'context', 'execution_limit', '추천 모델 실행 횟수를 초과했습니다.'))
        return update

    def decide(state: RecommendationState) -> dict:
        update = {'node_history': state['node_history'] + ['decision'],
                  'model_call_count': state['model_call_count'] + 1}
        try:
            response = bound_model.invoke(list(state['messages']))
        except OpenAIError as error:
            temporary = isinstance(error, (APITimeoutError, APIConnectionError)) or getattr(error, 'status_code', 0) in [429, 500, 502, 503, 504]
            code = 'timeout' if isinstance(error, APITimeoutError) else 'model_unavailable'
            update.update(record_error(state, 'decision', code, '추천 모델 호출에 실패했습니다.',
                                       'retry_model' if temporary else 'stop', temporary))
            return update
        # JSON 해석 실패로 invalid_tool_calls에 담긴 호출도 같은 ID로 오류 결과를 전달해야 한다.
        update.update({'messages': state['messages'] + [response], 'response': response,
                       'pending_calls': list(response.tool_calls) + list(response.invalid_tool_calls)})
        return update

    def execute_tools(state: RecommendationState) -> dict:
        update = {'node_history': state['node_history'] + ['tools']}
        if time.monotonic() - state['started_at'] >= EXECUTION_BUDGET_SECONDS:
            update.update(record_error(state, 'tools', 'timeout', '추천 처리 시간 예산을 초과했습니다.'))
            return update
        if state['tool_call_count'] >= MAX_TOOL_CALLS:
            update.update(record_error(state, 'tools', 'execution_limit', '추천 도구 실행 횟수를 초과했습니다.'))
            return update
        # 재시도에서는 실패한 호출만 다시 실행한다. 이미 성공한 다른 도구는 반복하지 않는다.
        call = state['current_call']
        if call is None:
            call = state['pending_calls'][0]
            update['pending_calls'] = state['pending_calls'][1:]
            call_id = call.get('id')
            if not call_id or call_id in state['seen_call_ids']:
                update.update(record_error(state, 'tools', 'invalid_tool_call', '도구 호출 ID가 올바르지 않습니다.'))
                return update
            update['seen_call_ids'] = state['seen_call_ids'] + [call_id]
        update['current_call'] = call
        update['tool_call_count'] = state['tool_call_count'] + 1
        try:
            if call['name'] not in tool_map or call['name'] not in ['list_interest_categories', 'search_certificates']:
                raise ValueError('허용되지 않은 도구')
            if not isinstance(call['args'], dict):
                raise ValueError('도구 인자 형식 오류')
            if call['name'] == 'search_certificates' and set(call['args'].get('interest_codes', [])) != set(state['interest_codes']):
                raise ValueError('사용자 관심 코드 변경')
            update['tools_called'] = state['tools_called'] + [call['name']]
            tool_result = tool_map[call['name']].invoke(call['args'])
        except RecommendationDataUnavailable as error:
            update.update(record_error(state, 'tools', 'data_unavailable', '추천 자료 DB 조회에 실패했습니다.',
                                       'retry_tool' if error.retryable else 'stop', error.retryable))
            return update
        except (ValueError, TypeError, ValidationError):
            update.update(record_error(state, 'tools', 'invalid_tool_call', '도구 이름·인자 제한·선택 관심 코드를 확인해야 합니다.', 'repair_tool_arguments'))
            return update
        if call['name'] == 'search_certificates':
            if not isinstance(tool_result, dict) or tool_result.get('status') not in ['found', 'empty_search'] or not isinstance(tool_result.get('candidates'), list):
                update.update(record_error(state, 'tools', 'data_unavailable', '도구 응답의 후보 구조가 올바르지 않습니다.'))
                return update
            candidates = dict(state['candidates'])
            for candidate in tool_result['candidates']:
                if not isinstance(candidate, dict) or not candidate.get('certificate_id') or not isinstance(candidate.get('evidence_documents'), list):
                    update.update(record_error(state, 'tools', 'data_unavailable', '후보의 ID 또는 근거 구조가 올바르지 않습니다.'))
                    return update
                candidates[candidate['certificate_id']] = candidate
            update.update({'candidates': candidates, 'searched': True})
        update.update({'messages': state['messages'] + [ToolMessage(
            content=json.dumps(compact_tool_result(tool_result), ensure_ascii=False), tool_call_id=call['id'])],
                       'current_call': None})
        return update

    def validate_result(state: RecommendationState) -> dict:
        update = {'node_history': state['node_history'] + ['validate']}
        if time.monotonic() - state['started_at'] >= EXECUTION_BUDGET_SECONDS:
            update.update(record_error(state, 'validate', 'timeout', '추천 처리 시간 예산을 초과했습니다.'))
            return update
        try:
            selection = validate_selection(state['response'].content, state['candidates'], state['profile'], state['searched'])
        except SelectionValidationError as error:
            update.update(record_error(state, 'validate', 'invalid_result', str(error), 'repair_result',
                                       error_type=error.error_type))
            return update
        except (ValueError, TypeError, KeyError):
            update.update(record_error(state, 'validate', 'invalid_result', '실제 후보 ID·개수·중복·인용·프로필·JSON 구조를 확인해야 합니다.', 'repair_result'))
            return update
        update['selection'] = selection
        return update

    def repair(state: RecommendationState) -> dict:
        error = state['error']
        messages = list(state['messages'])
        if error['repair_action'] == 'repair_tool_arguments':
            messages.append(ToolMessage(content=json.dumps({'status': 'invalid_arguments', 'message': error['cause']},
                                                          ensure_ascii=False), tool_call_id=state['current_call']['id']))
        else:
            messages.append(HumanMessage(content='최종 결과 검증 실패: ' + error['cause'] + ' 제공된 실제 자료로 JSON을 수정하세요.'))
        return {'messages': messages, 'repair_count': state['repair_count'] + 1,
                'current_call': None, 'error': None, 'node_history': state['node_history'] + ['repair']}

    def retry(state: RecommendationState) -> dict:
        return {'retry_count': state['retry_count'] + 1, 'error': None,
                'node_history': state['node_history'] + ['retry']}

    def finish(state: RecommendationState) -> dict:
        selection = state['selection']
        history = state['node_history'] + ['finish']
        result = {'selection': selection, 'candidates': [state['candidates'][item['certificate_id']] for item in selection['items']],
                  'selection_scope': 'searched_candidates_only', 'prompt_version': RECOMMENDATION_PROMPT_VERSION,
                  'model_call_count': state['model_call_count'], 'tool_call_count': state['tool_call_count'],
                  'repair_count': state['repair_count'], 'retry_count': state['retry_count'],
                  'error_count': state['error_count'], 'errors': state['errors'], 'tools_called': state['tools_called'],
                  'node_history': history, 'context_char_count': state['context_char_count'],
                  'elapsed_ms': round((time.monotonic() - state['started_at']) * 1000)}
        return {'result': result, 'status': selection['status'], 'node_history': history}

    def fallback(state: RecommendationState) -> dict:
        # 이번 단계에는 대체 공식 자료 조회 도구가 없다. 미검증 후보를 성공으로 반환하지 않는다.
        return {'status': 'failed', 'result': None, 'node_history': state['node_history'] + ['fallback']}

    def route_prepared(state: RecommendationState) -> str:
        return 'fallback' if state['error'] else 'context'

    def route_context(state: RecommendationState) -> str:
        return 'fallback' if state['error'] else 'decision'

    def route_decision(state: RecommendationState) -> str:
        if state['error']:
            return route_error(state)
        return 'tools' if state['pending_calls'] else 'validate'

    def route_tools(state: RecommendationState) -> str:
        if state['error']:
            return route_error(state)
        return 'tools' if state['pending_calls'] else 'context'

    def route_validation(state: RecommendationState) -> str:
        return route_error(state) if state['error'] else 'finish'

    def route_repair(state: RecommendationState) -> str:
        return 'tools' if state['pending_calls'] else 'context'

    def route_retry(state: RecommendationState) -> str:
        return 'tools' if state['current_call'] else 'context'

    graph = StateGraph(RecommendationState)
    for name, node in [('prepare', prepare), ('context', manage_context), ('decision', decide),
                       ('tools', execute_tools), ('validate', validate_result), ('repair', repair),
                       ('retry', retry), ('finish', finish), ('fallback', fallback)]:
        graph.add_node(name, node)
    graph.add_edge(START, 'prepare')
    graph.add_conditional_edges('prepare', route_prepared, ['context', 'fallback'])
    graph.add_conditional_edges('context', route_context, ['decision', 'fallback'])
    graph.add_conditional_edges('decision', route_decision, ['tools', 'validate', 'retry', 'repair', 'fallback'])
    graph.add_conditional_edges('tools', route_tools, ['tools', 'context', 'retry', 'repair', 'fallback'])
    graph.add_conditional_edges('validate', route_validation, ['finish', 'repair', 'fallback'])
    graph.add_conditional_edges('repair', route_repair, ['tools', 'context'])
    graph.add_conditional_edges('retry', route_retry, ['tools', 'context'])
    graph.add_edge('finish', END)
    graph.add_edge('fallback', END)
    return graph.compile()
